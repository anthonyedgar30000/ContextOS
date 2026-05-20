#!/usr/bin/env python3
"""Minimal deterministic verification CLI.

The CLI reads a session JSON file and a small policy YAML file, inspects the
current git working tree, and fails if any changed file is outside the policy's
allowed paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


class VerificationError(Exception):
    """Raised for user-facing verification failures."""


@dataclass(frozen=True)
class Policy:
    allowed_paths: tuple[str, ...]


@dataclass(frozen=True)
class GitStatusEntry:
    code: str
    path: str
    original_path: str | None = None


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


def parse_yaml_scalar(value: str, line_number: int) -> str:
    value = value.strip()
    if not value:
        raise VerificationError(f"policy.yaml line {line_number}: empty path entry")

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]

    return normalize_repo_path(value, f"policy.yaml line {line_number}")


def parse_inline_yaml_list(value: str, line_number: int) -> list[str]:
    value = value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        raise VerificationError(
            f"policy.yaml line {line_number}: allowed_paths must be a YAML list"
        )

    inner_value = value[1:-1].strip()
    if not inner_value:
        return []

    try:
        items = next(csv.reader([inner_value], skipinitialspace=True))
    except csv.Error as error:
        raise VerificationError(
            f"policy.yaml line {line_number}: invalid inline list: {error}"
        ) from error

    return [parse_yaml_scalar(item, line_number) for item in items]


def parse_policy_yaml(text: str) -> Policy:
    allowed_paths: list[str] = []
    in_allowed_paths = False
    found_allowed_paths = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        without_comment = strip_yaml_comment(raw_line).rstrip()
        if not without_comment.strip():
            continue

        indent = len(without_comment) - len(without_comment.lstrip(" "))
        line = without_comment.strip()

        if indent == 0:
            in_allowed_paths = False
            key, separator, value = line.partition(":")
            if separator and key.strip() == "allowed_paths":
                found_allowed_paths = True
                in_allowed_paths = True
                if value.strip():
                    allowed_paths.extend(parse_inline_yaml_list(value, line_number))
            continue

        if in_allowed_paths:
            if not line.startswith("- "):
                raise VerificationError(
                    f"policy.yaml line {line_number}: expected '- <path>'"
                )
            allowed_paths.append(parse_yaml_scalar(line[2:], line_number))

    if not found_allowed_paths:
        raise VerificationError("policy.yaml must contain an allowed_paths list")
    if not allowed_paths:
        raise VerificationError("policy.yaml allowed_paths list cannot be empty")

    return Policy(allowed_paths=tuple(dict.fromkeys(allowed_paths)))


def normalize_repo_path(path: str, source: str) -> str:
    raw_path = path.strip().replace("\\", "/")
    if raw_path.startswith("/"):
        raise VerificationError(f"{source}: path must be repository-relative")

    normalized = raw_path.strip("/")
    if not normalized or normalized == ".":
        raise VerificationError(f"{source}: path cannot be empty or repository root")
    if normalized.startswith("../") or "/../" in normalized or normalized.endswith("/.."):
        raise VerificationError(f"{source}: path cannot contain '..'")
    if normalized.startswith("./") or "/./" in normalized or normalized.endswith("/."):
        raise VerificationError(f"{source}: path cannot contain '.' components")

    parts = normalized.split("/")
    if any(part == "" for part in parts):
        raise VerificationError(f"{source}: path cannot contain empty components")

    return normalized


def load_session(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as session_file:
            return json.load(session_file)
    except FileNotFoundError as error:
        raise VerificationError(f"session file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise VerificationError(
            f"session file is not valid JSON: {path}:{error.lineno}:{error.colno}"
        ) from error


def load_policy(path: Path) -> Policy:
    try:
        return parse_policy_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise VerificationError(f"policy file not found: {path}") from error


def run_git(args: Sequence[str], repo: Path, *, binary: bool = False) -> str | bytes:
    command = ["git", *args]
    completed = subprocess.run(
        command,
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (
            completed.stderr.decode("utf-8", errors="replace")
            if binary
            else completed.stderr
        )
        raise VerificationError(
            f"{' '.join(command)} failed with exit code {completed.returncode}: "
            f"{stderr.strip() or 'no error output'}"
        )
    return completed.stdout


def parse_git_status_z(raw_status: bytes) -> list[GitStatusEntry]:
    entries: list[GitStatusEntry] = []
    fields = raw_status.split(b"\0")
    index = 0

    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue

        decoded = field.decode("utf-8", errors="surrogateescape")
        if len(decoded) < 4:
            raise VerificationError(f"unexpected git status entry: {decoded!r}")

        code = decoded[:2]
        path = decoded[3:]
        original_path = None

        if "R" in code or "C" in code:
            if index >= len(fields) or not fields[index]:
                raise VerificationError(
                    f"missing source path for git status entry: {decoded!r}"
                )
            original_path = fields[index].decode("utf-8", errors="surrogateescape")
            index += 1

        entries.append(GitStatusEntry(code=code, path=path, original_path=original_path))

    return entries


def changed_paths_from_status(entries: Iterable[GitStatusEntry]) -> set[str]:
    paths: set[str] = set()
    for entry in entries:
        paths.add(normalize_repo_path(entry.path, "git status"))
        if entry.original_path is not None:
            paths.add(normalize_repo_path(entry.original_path, "git status"))
    return paths


def changed_paths_from_diff(diff_output: str) -> set[str]:
    paths: set[str] = set()
    for line in diff_output.splitlines():
        if line.strip():
            paths.add(normalize_repo_path(line, "git diff --name-only"))
    return paths


def is_allowed(path: str, allowed_paths: Sequence[str]) -> bool:
    return any(
        path == allowed_path or path.startswith(f"{allowed_path}/")
        for allowed_path in allowed_paths
    )


def print_section(title: str, lines: Iterable[str]) -> None:
    print(title)
    rendered_lines = list(lines)
    if rendered_lines:
        for line in rendered_lines:
            print(f"  {line}")
    else:
        print("  (none)")


def render_status_entries(entries: Iterable[GitStatusEntry]) -> list[str]:
    rendered = []
    for entry in entries:
        if entry.original_path is None:
            rendered.append(f"{entry.code} {entry.path}")
        else:
            rendered.append(f"{entry.code} {entry.original_path} -> {entry.path}")
    return sorted(rendered)


def verify(session_path: Path, policy_path: Path, repo: Path) -> int:
    load_session(session_path)
    policy = load_policy(policy_path)

    raw_status = run_git(["status", "--porcelain=v1", "-z"], repo, binary=True)
    diff_output = run_git(["diff", "--name-only"], repo)

    status_entries = parse_git_status_z(raw_status)
    changed_paths = changed_paths_from_status(status_entries)
    changed_paths.update(changed_paths_from_diff(diff_output))

    disallowed_paths = sorted(
        path for path in changed_paths if not is_allowed(path, policy.allowed_paths)
    )

    print(f"session: {session_path}")
    print(f"policy: {policy_path}")
    print(f"repo: {repo}")
    print_section("allowed paths:", policy.allowed_paths)
    print_section(
        "$ git status --porcelain=v1 -z:",
        render_status_entries(status_entries),
    )
    print_section(
        "$ git diff --name-only:",
        sorted(changed_paths_from_diff(diff_output)),
    )

    if disallowed_paths:
        print()
        print("verification: FAILED")
        print_section("changed files outside allowed paths:", disallowed_paths)
        return 1

    print()
    print("verification: PASSED")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify git changes are limited to policy-allowed paths."
    )
    parser.add_argument(
        "--session",
        default="session.json",
        type=Path,
        help="path to session.json (default: session.json)",
    )
    parser.add_argument(
        "--policy",
        default="policy.yaml",
        type=Path,
        help="path to policy.yaml (default: policy.yaml)",
    )
    parser.add_argument(
        "--repo",
        default=Path.cwd(),
        type=Path,
        help="path to the git repository (default: current working directory)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return verify(args.session, args.policy, args.repo)
    except VerificationError as error:
        print(f"verification: ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
