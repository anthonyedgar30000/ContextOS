#!/usr/bin/env python3
"""ContextOS local command line interface."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from git_command_explanations import (
    GitCommandExplanationError,
    explain_git_command,
    render_markdown_explanation,
    render_terminal_explanation,
)


class ContextOSError(Exception):
    """Raised for clear, user-facing ContextOS command failures."""


@dataclass(frozen=True)
class ContextPacket:
    project: str
    repo: str
    branch: str
    task: str
    allowed_paths: tuple[str, ...]


REQUIRED_PACKET_FIELDS = ("project", "repo", "branch", "task", "allowed_paths")


def strip_yaml_comment(line: str) -> str:
    in_single_quote = False
    in_double_quote = False

    for index, character in enumerate(line):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif (
            character == "#"
            and not in_single_quote
            and not in_double_quote
            and (index == 0 or line[index - 1].isspace())
        ):
            return line[:index]

    return line


def parse_yaml_scalar(value: str, *, source: str) -> str:
    value = value.strip()
    if not value:
        raise ContextOSError(f"{source}: value cannot be empty")

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]

    if not value.strip():
        raise ContextOSError(f"{source}: value cannot be empty")
    return value.strip()


def parse_inline_yaml_list(value: str, *, source: str) -> list[str]:
    value = value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        raise ContextOSError(f"{source}: expected a YAML list")

    inner_value = value[1:-1].strip()
    if not inner_value:
        return []

    try:
        items = next(csv.reader([inner_value], skipinitialspace=True))
    except csv.Error as error:
        raise ContextOSError(f"{source}: invalid inline list: {error}") from error

    return [parse_yaml_scalar(item, source=source) for item in items]


def parse_context_packet_yaml(text: str) -> dict[str, object]:
    packet: dict[str, object] = {}
    active_list_key: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        without_comment = strip_yaml_comment(raw_line).rstrip()
        if not without_comment.strip():
            continue

        indent = len(without_comment) - len(without_comment.lstrip(" "))
        line = without_comment.strip()

        if indent == 0:
            active_list_key = None
            key, separator, value = line.partition(":")
            if not separator:
                raise ContextOSError(
                    f"context_packet.yaml line {line_number}: expected '<field>:'"
                )

            key = key.strip()
            if not key:
                raise ContextOSError(
                    f"context_packet.yaml line {line_number}: field name cannot be empty"
                )

            value = value.strip()
            if key == "allowed_paths":
                active_list_key = key
                packet[key] = (
                    parse_inline_yaml_list(
                        value,
                        source=f"context_packet.yaml line {line_number}",
                    )
                    if value
                    else []
                )
            else:
                packet[key] = parse_yaml_scalar(
                    value,
                    source=f"context_packet.yaml line {line_number}",
                )
            continue

        if active_list_key is None:
            raise ContextOSError(
                f"context_packet.yaml line {line_number}: unexpected nested value"
            )
        if not line.startswith("- "):
            raise ContextOSError(
                f"context_packet.yaml line {line_number}: expected '- <value>'"
            )
        packet.setdefault(active_list_key, [])
        packet[active_list_key].append(
            parse_yaml_scalar(
                line[2:],
                source=f"context_packet.yaml line {line_number}",
            )
        )

    return packet


def normalize_repo_path(path: str, *, source: str) -> str:
    raw_path = path.strip().replace("\\", "/")
    if raw_path.startswith("/"):
        raise ContextOSError(f"{source}: path must be repository-relative")

    normalized = raw_path.strip("/")
    if not normalized or normalized == ".":
        raise ContextOSError(f"{source}: path cannot be empty or repository root")
    if (
        normalized.startswith("../")
        or "/../" in normalized
        or normalized.endswith("/..")
    ):
        raise ContextOSError(f"{source}: path cannot contain '..'")
    if (
        normalized.startswith("./")
        or "/./" in normalized
        or normalized.endswith("/.")
    ):
        raise ContextOSError(f"{source}: path cannot contain '.' components")
    if any(part == "" for part in normalized.split("/")):
        raise ContextOSError(f"{source}: path cannot contain empty components")

    return normalized


def load_context_packet(path: Path) -> ContextPacket:
    try:
        packet = parse_context_packet_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContextOSError(f"context packet not found: {path}") from error

    missing_fields = [
        field
        for field in REQUIRED_PACKET_FIELDS
        if field not in packet
    ]
    if missing_fields:
        raise ContextOSError(
            "context packet missing required fields: " + ", ".join(missing_fields)
        )

    scalar_fields: dict[str, str] = {}
    for field in ("project", "repo", "branch", "task"):
        value = packet[field]
        if not isinstance(value, str) or not value.strip():
            raise ContextOSError(f"context packet field '{field}' must be a string")
        scalar_fields[field] = value.strip()

    allowed_paths = packet["allowed_paths"]
    if not isinstance(allowed_paths, list) or not allowed_paths:
        raise ContextOSError(
            "context packet field 'allowed_paths' must be a non-empty list"
        )

    normalized_allowed_paths = tuple(
        dict.fromkeys(
            normalize_repo_path(
                path,
                source="context packet allowed_paths",
            )
            for path in allowed_paths
            if isinstance(path, str)
        )
    )
    if len(normalized_allowed_paths) != len(allowed_paths):
        raise ContextOSError("context packet allowed_paths entries must be strings")

    return ContextPacket(
        project=scalar_fields["project"],
        repo=scalar_fields["repo"],
        branch=scalar_fields["branch"],
        task=scalar_fields["task"],
        allowed_paths=normalized_allowed_paths,
    )


def run_git(args: Sequence[str], repo: Path) -> str:
    command = ["git", *args]
    completed = subprocess.run(
        command,
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ContextOSError(
            f"{' '.join(command)} failed with exit code {completed.returncode}: "
            f"{completed.stderr.strip() or 'no error output'}"
        )
    return completed.stdout.strip()


def repo_root(repo: Path) -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"], repo))


def current_branch(repo: Path) -> str:
    branch = run_git(["branch", "--show-current"], repo)
    return branch or "(detached HEAD)"


def head_hash(repo: Path) -> str:
    return run_git(["rev-parse", "HEAD"], repo)


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def print_section(title: str, lines: Iterable[str]) -> None:
    print(title)
    rendered_lines = list(lines)
    if rendered_lines:
        for line in rendered_lines:
            print(f"  {line}")
    else:
        print("  (none)")


def validate_packet_location(
    packet: ContextPacket, actual_repo: str, actual_branch: str
) -> None:
    mismatch_reasons = []
    if packet.repo != actual_repo:
        mismatch_reasons.append(
            f"repo mismatch: expected {packet.repo}, actual {actual_repo}"
        )
    if packet.branch != actual_branch:
        mismatch_reasons.append(
            f"branch mismatch: expected {packet.branch}, actual {actual_branch}"
        )

    if mismatch_reasons:
        print("contextos ingest: FAILED")
        print_section("mismatch reasons:", mismatch_reasons)
        raise ContextOSError("context packet does not match current Git context")


def write_session_context(
    *,
    output_path: Path,
    packet: ContextPacket,
    actual_repo_root: Path,
    actual_branch: str,
    actual_head_hash: str,
) -> None:
    session_context = {
        "allowed_paths": list(packet.allowed_paths),
        "branch": actual_branch,
        "git_head_hash": actual_head_hash,
        "project": packet.project,
        "repo": packet.repo,
        "repo_root": str(actual_repo_root),
        "source": "chatgpt_context_packet",
        "task": packet.task,
        "timestamp": utc_timestamp(),
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(session_context, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise ContextOSError(
            f"could not write session context {output_path}: {error}"
        ) from error


def ingest(packet_path: Path, repo: Path) -> int:
    packet = load_context_packet(packet_path)
    actual_repo_root = repo_root(repo)
    actual_repo = actual_repo_root.name
    actual_branch = current_branch(actual_repo_root)
    actual_head_hash = head_hash(actual_repo_root)

    print("contextos ingest")
    print(f"packet: {packet_path}")
    print(f"repo: {actual_repo}")
    print(f"branch: {actual_branch}")

    validate_packet_location(packet, actual_repo, actual_branch)

    output_path = actual_repo_root / ".contextos" / "session_context.json"
    write_session_context(
        output_path=output_path,
        packet=packet,
        actual_repo_root=actual_repo_root,
        actual_branch=actual_branch,
        actual_head_hash=actual_head_hash,
    )

    print_section("allowed paths:", packet.allowed_paths)
    print(f"session context: {output_path}")
    print("contextos ingest: PASSED")
    return 0


def explain_git(command: Sequence[str], output_format: str) -> int:
    if not command:
        raise ContextOSError("explain-git requires a Git command")

    try:
        explanation = explain_git_command(command)
    except GitCommandExplanationError as error:
        raise ContextOSError(str(error)) from error

    if output_format == "terminal":
        print(render_terminal_explanation(explanation))
    elif output_format == "markdown":
        print(render_markdown_explanation(explanation))
    else:
        raise ContextOSError("format must be either terminal or markdown")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextos",
        description="ContextOS local execution context commands.",
    )
    parser.add_argument(
        "--repo",
        default=Path.cwd(),
        type=Path,
        help="path to the git repository (default: current working directory)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="ingest a reviewed ChatGPT context packet",
    )
    ingest_parser.add_argument(
        "context_packet",
        type=Path,
        help="path to context_packet.yaml",
    )
    explain_parser = subparsers.add_parser(
        "explain-git",
        help="explain a recommended Git command",
    )
    explain_parser.add_argument(
        "--format",
        choices=("terminal", "markdown"),
        default="terminal",
        help="output format (default: terminal)",
    )
    explain_parser.add_argument(
        "git_command",
        nargs=argparse.REMAINDER,
        help="Git command to explain, for example: git status",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "ingest":
            return ingest(args.context_packet, args.repo)
        if args.command == "explain-git":
            return explain_git(args.git_command, args.format)
    except ContextOSError as error:
        print(f"contextos: ERROR: {error}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
