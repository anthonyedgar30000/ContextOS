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


@dataclass(frozen=True)
class IssuePacket:
    project: str
    repo: str
    branch: str
    task: str
    objective: str
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    assumptions: tuple[str, ...]
    risks: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


@dataclass(frozen=True)
class IssueFreshness:
    timestamp: str
    current_branch: str
    current_head_hash: str
    classification: str
    reasons: tuple[str, ...]


REQUIRED_PACKET_FIELDS = ("project", "repo", "branch", "task", "allowed_paths")
REQUIRED_ISSUE_PACKET_FIELDS = (
    "project",
    "repo",
    "branch",
    "task",
    "objective",
    "allowed_paths",
    "protected_paths",
    "assumptions",
    "risks",
    "acceptance_criteria",
)
ISSUE_PACKET_LIST_FIELDS = {
    "allowed_paths",
    "protected_paths",
    "assumptions",
    "risks",
    "acceptance_criteria",
}


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


def parse_simple_yaml(
    text: str,
    *,
    source_name: str,
    list_fields: set[str],
) -> dict[str, object]:
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
                    f"{source_name} line {line_number}: expected '<field>:'"
                )

            key = key.strip()
            if not key:
                raise ContextOSError(
                    f"{source_name} line {line_number}: field name cannot be empty"
                )

            value = value.strip()
            if key in list_fields:
                active_list_key = key
                packet[key] = (
                    parse_inline_yaml_list(
                        value,
                        source=f"{source_name} line {line_number}",
                    )
                    if value
                    else []
                )
            else:
                packet[key] = parse_yaml_scalar(
                    value,
                    source=f"{source_name} line {line_number}",
                )
            continue

        if active_list_key is None:
            raise ContextOSError(
                f"{source_name} line {line_number}: unexpected nested value"
            )
        if not line.startswith("- "):
            raise ContextOSError(
                f"{source_name} line {line_number}: expected '- <value>'"
            )
        packet.setdefault(active_list_key, [])
        packet[active_list_key].append(
            parse_yaml_scalar(
                line[2:],
                source=f"{source_name} line {line_number}",
            )
        )

    return packet


def parse_context_packet_yaml(text: str) -> dict[str, object]:
    return parse_simple_yaml(
        text,
        source_name="context_packet.yaml",
        list_fields={"allowed_paths"},
    )


def parse_issue_packet_yaml(text: str) -> dict[str, object]:
    return parse_simple_yaml(
        text,
        source_name="issue_packet.yaml",
        list_fields=ISSUE_PACKET_LIST_FIELDS,
    )


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


def require_scalar(packet: dict[str, object], field: str, source_name: str) -> str:
    value = packet[field]
    if not isinstance(value, str) or not value.strip():
        raise ContextOSError(f"{source_name} field '{field}' must be a string")
    return value.strip()


def require_string_list(
    packet: dict[str, object],
    field: str,
    source_name: str,
    *,
    normalize_paths: bool = False,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    value = packet[field]
    if not isinstance(value, list):
        raise ContextOSError(f"{source_name} field '{field}' must be a list")
    if require_non_empty and not value:
        raise ContextOSError(f"{source_name} field '{field}' must be non-empty")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ContextOSError(f"{source_name} field '{field}' entries must be strings")

    if normalize_paths:
        return tuple(
            dict.fromkeys(
                normalize_repo_path(
                    item,
                    source=f"{source_name} {field}",
                )
                for item in value
            )
        )

    return tuple(dict.fromkeys(item.strip() for item in value))


def load_issue_packet(path: Path) -> IssuePacket:
    try:
        packet = parse_issue_packet_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContextOSError(f"issue packet not found: {path}") from error

    missing_fields = [
        field for field in REQUIRED_ISSUE_PACKET_FIELDS if field not in packet
    ]
    if missing_fields:
        raise ContextOSError(
            "issue packet missing required fields: " + ", ".join(missing_fields)
        )

    return IssuePacket(
        project=require_scalar(packet, "project", "issue packet"),
        repo=require_scalar(packet, "repo", "issue packet"),
        branch=require_scalar(packet, "branch", "issue packet"),
        task=require_scalar(packet, "task", "issue packet"),
        objective=require_scalar(packet, "objective", "issue packet"),
        allowed_paths=require_string_list(
            packet,
            "allowed_paths",
            "issue packet",
            normalize_paths=True,
            require_non_empty=True,
        ),
        protected_paths=require_string_list(
            packet,
            "protected_paths",
            "issue packet",
            normalize_paths=True,
        ),
        assumptions=require_string_list(packet, "assumptions", "issue packet"),
        risks=require_string_list(packet, "risks", "issue packet"),
        acceptance_criteria=require_string_list(
            packet,
            "acceptance_criteria",
            "issue packet",
            require_non_empty=True,
        ),
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


def try_run_git(args: Sequence[str], repo: Path) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def upstream_branch(repo: Path) -> str | None:
    return try_run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        repo,
    )


def local_branch_behind_reason(repo: Path) -> str | None:
    upstream = upstream_branch(repo)
    if upstream is None:
        return None

    counts = try_run_git(
        ["rev-list", "--left-right", "--count", f"HEAD...{upstream}"],
        repo,
    )
    if counts is None:
        return None

    parts = counts.split()
    if len(parts) != 2:
        raise ContextOSError(f"unexpected git rev-list output: {counts!r}")

    try:
        behind_count = int(parts[1])
    except ValueError as error:
        raise ContextOSError(f"unexpected git rev-list output: {counts!r}") from error

    if behind_count == 0:
        return None

    commit_label = "commit" if behind_count == 1 else "commits"
    return f"local branch is behind {upstream} by {behind_count} {commit_label}"


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def audit_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y%m%dT%H%M%SZ")
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


def markdown_list(items: Sequence[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def issue_freshness(packet: IssuePacket, repo: Path) -> IssueFreshness:
    current = current_branch(repo)
    current_head = head_hash(repo)
    reasons = []
    is_detached = current == "(detached HEAD)"
    behind_reason = local_branch_behind_reason(repo)

    if packet.branch != current:
        reasons.append(f"issue packet expects branch {packet.branch}")
        reasons.append(f"current branch is {current}")
    if is_detached:
        reasons.append("current repository is in detached HEAD state")
    if behind_reason is not None:
        reasons.append(behind_reason)

    if is_detached:
        classification = "DIVERGED"
    elif packet.branch != current:
        classification = "STALE"
    elif behind_reason is not None:
        classification = "AGING"
    else:
        classification = "FRESH"

    return IssueFreshness(
        timestamp=utc_timestamp(),
        current_branch=current,
        current_head_hash=current_head,
        classification=classification,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def render_issue_markdown(packet: IssuePacket, freshness: IssueFreshness) -> str:
    return "\n".join(
        [
            f"# {packet.task}",
            "",
            "## Task summary",
            "",
            f"- Project: {packet.project}",
            f"- Repository: {packet.repo}",
            f"- Expected branch: {packet.branch}",
            f"- Objective: {packet.objective}",
            "",
            "## Context freshness",
            "",
            f"- Timestamp: {freshness.timestamp}",
            f"- Current branch: {freshness.current_branch}",
            f"- Current HEAD hash: {freshness.current_head_hash}",
            f"- Freshness classification: {freshness.classification}",
            "",
            "### Freshness reasons",
            markdown_list(freshness.reasons),
            "",
            "## Allowed mutation scope",
            markdown_list(packet.allowed_paths),
            "",
            "## Protected paths",
            markdown_list(packet.protected_paths),
            "",
            "## Assumptions",
            markdown_list(packet.assumptions),
            "",
            "## Risks",
            markdown_list(packet.risks),
            "",
            "## Acceptance criteria",
            markdown_list(packet.acceptance_criteria),
            "",
            "## Required verification steps",
            "",
            "1. Confirm the current branch matches the expected branch.",
            "2. Run `python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode enforce`.",
            "3. Review protected path warnings or failures.",
            "4. Attach or reference the markdown audit report if verification fails.",
            "",
            "## Coordination model",
            "",
            "- ChatGPT prepares or reviews the issue packet.",
            "- GitHub Issue stores the human-readable handoff.",
            "- Cursor performs repo-local analysis and implementation.",
            "- Cursor response is posted as a GitHub comment/report after human review.",
            "- ChatGPT reviews the report and any resulting PR.",
            "",
            "## Authority boundary",
            "",
            "Reasoning systems may propose and summarize work. Humans remain the approval authority for issue creation, implementation acceptance, and merge decisions.",
            "",
            "## GitHub API status",
            "",
            "No GitHub API call was made by ContextOS. This markdown was generated locally for review before posting.",
            "",
        ]
    )


def write_issue_audit_artifacts(
    *,
    repo: Path,
    packet_path: Path,
    issue_markdown: str,
    output_path: Path,
) -> tuple[Path, Path]:
    audit_root = repo / ".contextos" / "audit"
    packet_dir = audit_root / "issue_packets"
    issue_dir = audit_root / "generated_issues"
    packet_dir.mkdir(parents=True, exist_ok=True)
    issue_dir.mkdir(parents=True, exist_ok=True)

    stamp = audit_timestamp()
    packet_snapshot = packet_dir / f"{stamp}_issue_packet.yaml"
    generated_issue = issue_dir / f"{stamp}_issue.md"

    packet_snapshot.write_text(packet_path.read_text(encoding="utf-8"), encoding="utf-8")
    generated_issue.write_text(issue_markdown, encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(issue_markdown, encoding="utf-8")
    return packet_snapshot, generated_issue


def create_issue(packet_path: Path, repo: Path, output_path: Path | None) -> int:
    root = repo_root(repo)
    if not packet_path.is_absolute():
        packet_path = root / packet_path
    packet = load_issue_packet(packet_path)
    freshness = issue_freshness(packet, root)
    issue_markdown = render_issue_markdown(packet, freshness)

    if output_path is None:
        output_path = root / ".contextos" / "audit" / "generated_issue.md"
    elif not output_path.is_absolute():
        output_path = root / output_path

    packet_snapshot, generated_issue = write_issue_audit_artifacts(
        repo=root,
        packet_path=packet_path,
        issue_markdown=issue_markdown,
        output_path=output_path,
    )

    print(issue_markdown)
    print("Generated issue markdown:")
    print(f"  {output_path}")
    print("Audit artifacts:")
    print(f"  issue packet: {packet_snapshot}")
    print(f"  generated issue: {generated_issue}")
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
    create_issue_parser = subparsers.add_parser(
        "create-issue",
        help="generate local GitHub Issue markdown from an issue packet",
    )
    create_issue_parser.add_argument(
        "--packet",
        default=Path(".contextos/issue_packet.yaml"),
        type=Path,
        help="path to issue_packet.yaml (default: .contextos/issue_packet.yaml)",
    )
    create_issue_parser.add_argument(
        "--output",
        type=Path,
        help="path for generated issue markdown (default: .contextos/audit/generated_issue.md)",
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
        if args.command == "create-issue":
            return create_issue(args.packet, args.repo, args.output)
    except ContextOSError as error:
        print(f"contextos: ERROR: {error}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
