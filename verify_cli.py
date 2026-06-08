#!/usr/bin/env python3
"""Minimal deterministic verification CLI.

The CLI reads a session JSON file and a small policy YAML file, inspects the
current git working tree, and fails if any changed file is outside the policy's
allowed paths.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


class VerificationError(Exception):
    """Raised for user-facing verification failures."""


@dataclass(frozen=True)
class Policy:
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class Session:
    expected_branch: str | None = None


@dataclass(frozen=True)
class SessionContext:
    branch: str
    git_head_hash: str


@dataclass(frozen=True)
class GitStatusEntry:
    code: str
    path: str
    original_path: str | None = None


@dataclass(frozen=True)
class ProtectedPathViolation:
    path: str
    pattern: str


@dataclass(frozen=True)
class ContextFreshness:
    classification: str
    reasons: tuple[str, ...]


GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


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


def parse_inline_yaml_list(
    value: str, line_number: int, key: str = "allowed_paths"
) -> list[str]:
    value = value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        raise VerificationError(
            f"policy.yaml line {line_number}: {key} must be a YAML list"
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


def parse_policy_list_item(key: str, value: str, line_number: int) -> str:
    try:
        return parse_yaml_scalar(value, line_number)
    except VerificationError as error:
        raise VerificationError(f"policy.yaml {key}: {error}") from error


def parse_policy_yaml(text: str) -> Policy:
    lists: dict[str, list[str]] = {"allowed_paths": [], "protected_paths": []}
    active_list_key: str | None = None
    found_allowed_paths = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        without_comment = strip_yaml_comment(raw_line).rstrip()
        if not without_comment.strip():
            continue

        indent = len(without_comment) - len(without_comment.lstrip(" "))
        line = without_comment.strip()

        if indent == 0:
            active_list_key = None
            key, separator, value = line.partition(":")
            key = key.strip()
            if separator and key in lists:
                if key == "allowed_paths":
                    found_allowed_paths = True
                active_list_key = key
                if value.strip():
                    lists[key].extend(parse_inline_yaml_list(value, line_number, key))
            continue

        if active_list_key is not None:
            if not line.startswith("- "):
                raise VerificationError(
                    f"policy.yaml line {line_number}: expected '- <path>'"
                )
            lists[active_list_key].append(
                parse_policy_list_item(active_list_key, line[2:], line_number)
            )

    if not found_allowed_paths:
        raise VerificationError("policy.yaml must contain an allowed_paths list")
    if not lists["allowed_paths"]:
        raise VerificationError("policy.yaml allowed_paths list cannot be empty")

    return Policy(
        allowed_paths=tuple(dict.fromkeys(lists["allowed_paths"])),
        protected_paths=tuple(dict.fromkeys(lists["protected_paths"])),
    )


def parse_session_json(data: object) -> Session:
    if not isinstance(data, dict) or "expected_branch" not in data:
        return Session()

    expected_branch = data["expected_branch"]
    if not isinstance(expected_branch, str) or not expected_branch.strip():
        raise VerificationError(
            "session.json expected_branch must be a non-empty string"
        )

    return Session(expected_branch=expected_branch.strip())


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


def load_session(path: Path) -> Session:
    try:
        with path.open("r", encoding="utf-8") as session_file:
            return parse_session_json(json.load(session_file))
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


def parse_session_context_json(data: object) -> SessionContext:
    if not isinstance(data, dict):
        raise VerificationError("session_context.json must contain a JSON object")

    branch = data.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        raise VerificationError(
            "session_context.json branch must be a non-empty string"
        )

    git_head_hash = data.get("git_head_hash")
    if not isinstance(git_head_hash, str) or not git_head_hash.strip():
        raise VerificationError(
            "session_context.json git_head_hash must be a non-empty string"
        )

    return SessionContext(
        branch=branch.strip(),
        git_head_hash=git_head_hash.strip(),
    )


def load_session_context(path: Path) -> SessionContext | None:
    if not path.exists():
        return None

    try:
        return parse_session_context_json(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise VerificationError(
            "session_context.json is not valid JSON: "
            f"{path}:{error.lineno}:{error.colno}"
        ) from error


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


def repo_root(repo: Path) -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"], repo).strip())


def current_branch(repo: Path) -> str:
    branch = run_git(["branch", "--show-current"], repo).strip()
    return branch or "(detached HEAD)"


def git_head_hash(repo: Path) -> str:
    return run_git(["rev-parse", "HEAD"], repo).strip()


def try_run_git(args: Sequence[str], repo: Path) -> str | None:
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
        raise VerificationError(f"unexpected git rev-list output: {counts!r}")

    try:
        behind_count = int(parts[1])
    except ValueError as error:
        raise VerificationError(f"unexpected git rev-list output: {counts!r}") from error

    if behind_count == 0:
        return None

    commit_label = "commit" if behind_count == 1 else "commits"
    return f"local branch is behind {upstream} by {behind_count} {commit_label}"


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


def staged_paths_from_diff(diff_output: str) -> list[str]:
    return sorted(changed_paths_from_diff(diff_output))


def is_allowed(path: str, allowed_paths: Sequence[str]) -> bool:
    return any(
        path == allowed_path or path.startswith(f"{allowed_path}/")
        for allowed_path in allowed_paths
    )


def matches_protected_pattern(path: str, pattern: str) -> bool:
    return (
        path == pattern
        or path.startswith(f"{pattern}/")
        or fnmatch.fnmatchcase(path, pattern)
    )


def protected_path_violations(
    staged_paths: Sequence[str], protected_paths: Sequence[str]
) -> list[ProtectedPathViolation]:
    violations = []
    for path in staged_paths:
        for pattern in protected_paths:
            if matches_protected_pattern(path, pattern):
                violations.append(ProtectedPathViolation(path=path, pattern=pattern))
    return sorted(violations, key=lambda violation: (violation.path, violation.pattern))


def protected_path_violation_reason(violation: ProtectedPathViolation) -> str:
    return (
        f"protected path violation: {violation.path} "
        f"matches {violation.pattern}"
    )


def render_protected_violations(
    violations: Iterable[ProtectedPathViolation],
) -> list[str]:
    return [protected_path_violation_reason(violation) for violation in violations]


def colorize(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


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


def branch_mismatch_reason(
    expected_branch: str | None, actual_branch: str
) -> str | None:
    if expected_branch is None or expected_branch == actual_branch:
        return None
    return f"branch mismatch: expected {expected_branch}, actual {actual_branch}"


def unauthorized_file_reason(path: str) -> str:
    return f"unauthorized file: {path} (not under allowed_paths)"


def print_architecture_drift_notice(
    *,
    include_scope_message: bool = False,
    include_guardrail_message: bool = False,
) -> None:
    print()
    print("ARCHITECTURE DRIFT DETECTED")
    if include_scope_message:
        print("Observed change exceeds Intent Contract scope.")
    if include_guardrail_message:
        print("Guardrail decision: Human review required.")


def context_freshness(
    *,
    session_context: SessionContext | None,
    actual_branch: str,
    actual_head_hash: str,
    behind_reason: str | None,
) -> ContextFreshness:
    reasons = []
    is_detached = actual_branch == "(detached HEAD)"
    if session_context is not None:
        if session_context.branch != actual_branch:
            reasons.append(f"session created on {session_context.branch}")
            reasons.append(f"current branch is {actual_branch}")
        if session_context.git_head_hash != actual_head_hash:
            reasons.append("HEAD changed after ingestion")

    if is_detached:
        reasons.append("current repository is in detached HEAD state")
    if behind_reason is not None:
        reasons.append(behind_reason)

    if is_detached:
        classification = "DIVERGED"
    elif session_context is not None and (
        session_context.branch != actual_branch
        or session_context.git_head_hash != actual_head_hash
    ):
        classification = "STALE"
    elif behind_reason is not None:
        classification = "AGING"
    else:
        classification = "FRESH"

    return ContextFreshness(
        classification=classification,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def print_context_freshness(freshness: ContextFreshness) -> None:
    print()
    print(f"CONTEXT {freshness.classification}")
    if freshness.reasons:
        print("Reason:")
        print()
        for reason in freshness.reasons:
            print(f"- {reason}")
        print()
        print("Suggested remediation:")
        print()
        print("1. regenerate context packet")
        print("2. run contextos ingest")
        print("3. revalidate before commit")


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def markdown_list(items: Iterable[str]) -> str:
    rendered_items = list(items)
    if not rendered_items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in rendered_items)


def markdown_code_block(lines: Iterable[str]) -> str:
    rendered_lines = list(lines)
    body = "\n".join(rendered_lines) if rendered_lines else "(none)"
    return f"```text\n{body}\n```"


def render_audit_report(
    *,
    timestamp: str,
    repo: Path,
    expected_branch: str | None,
    actual_branch: str,
    changed_paths: Sequence[str],
    allowed_paths: Sequence[str],
    violations: Sequence[str],
    status_summary: Sequence[str],
    stale_reasons: Sequence[str] = (),
    protected_violations: Sequence[str] = (),
    architecture_drift_detected: bool = False,
) -> str:
    return "\n".join(
        [
            "# Verification Audit Report",
            "",
            f"- Timestamp: {timestamp}",
            f"- Repo: {repo}",
            f"- Branch: {actual_branch}",
            f"- Expected Branch: {expected_branch or '(not specified)'}",
            "",
            "## Intent Contract Scope Decision",
            (
                "ARCHITECTURE DRIFT DETECTED"
                if architecture_drift_detected
                else "Within Intent Contract scope"
            ),
            "",
            "## Changed Files",
            markdown_list(changed_paths),
            "",
            "## Allowed Files",
            markdown_list(allowed_paths),
            "",
            "## Violations",
            markdown_list(violations),
            "",
            "## Context Freshness",
            markdown_list(stale_reasons),
            "",
            "## Protected Path Violations",
            markdown_list(protected_violations),
            "",
            "## Git Status Summary",
            markdown_code_block(status_summary),
            "",
        ]
    )


def write_audit_report(
    *,
    path: Path,
    repo: Path,
    expected_branch: str | None,
    actual_branch: str,
    changed_paths: Sequence[str],
    allowed_paths: Sequence[str],
    violations: Sequence[str],
    status_summary: Sequence[str],
    stale_reasons: Sequence[str] = (),
    protected_violations: Sequence[str] = (),
    architecture_drift_detected: bool = False,
) -> None:
    report = render_audit_report(
        timestamp=utc_timestamp(),
        repo=repo,
        expected_branch=expected_branch,
        actual_branch=actual_branch,
        changed_paths=changed_paths,
        allowed_paths=allowed_paths,
        violations=violations,
        status_summary=status_summary,
        stale_reasons=stale_reasons,
        protected_violations=protected_violations,
        architecture_drift_detected=architecture_drift_detected,
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
    except OSError as error:
        raise VerificationError(
            f"could not write audit report {path}: {error}"
        ) from error


def verify(
    session_path: Path,
    policy_path: Path,
    repo: Path,
    report_path: Path | None = None,
    session_context_path: Path | None = None,
    protected_mode: str = "advisory",
) -> int:
    if protected_mode not in {"advisory", "enforce"}:
        raise VerificationError(
            "protected mode must be either 'advisory' or 'enforce'"
        )

    actual_repo_root = repo_root(repo)
    if not session_path.is_absolute():
        session_path = actual_repo_root / session_path
    if not policy_path.is_absolute():
        policy_path = actual_repo_root / policy_path
    if report_path is not None and not report_path.is_absolute():
        report_path = actual_repo_root / report_path
    session = load_session(session_path)
    policy = load_policy(policy_path)

    actual_branch = current_branch(actual_repo_root)
    if session_context_path is None:
        session_context_path = actual_repo_root / ".contextos" / "session_context.json"
    session_context = load_session_context(session_context_path)
    actual_head_hash = git_head_hash(actual_repo_root) if session_context else ""
    freshness = context_freshness(
        session_context=session_context,
        actual_branch=actual_branch,
        actual_head_hash=actual_head_hash,
        behind_reason=local_branch_behind_reason(actual_repo_root),
    )
    freshness_details = [
        f"classification: {freshness.classification}",
        *freshness.reasons,
    ]

    raw_status = run_git(
        ["status", "--porcelain=v1", "-z"],
        actual_repo_root,
        binary=True,
    )
    diff_output = run_git(["diff", "--name-only"], actual_repo_root)
    staged_diff_output = run_git(["diff", "--cached", "--name-only"], actual_repo_root)

    status_entries = parse_git_status_z(raw_status)
    changed_paths = changed_paths_from_status(status_entries)
    changed_paths.update(changed_paths_from_diff(diff_output))
    sorted_changed_paths = sorted(changed_paths)
    status_summary = render_status_entries(status_entries)
    staged_paths = staged_paths_from_diff(staged_diff_output)
    protected_violations = protected_path_violations(
        staged_paths,
        policy.protected_paths,
    )
    rendered_protected_violations = render_protected_violations(protected_violations)

    disallowed_paths = sorted(
        path for path in changed_paths if not is_allowed(path, policy.allowed_paths)
    )
    mismatch_reasons = [
        reason
        for reason in [branch_mismatch_reason(session.expected_branch, actual_branch)]
        if reason is not None
    ]
    mismatch_reasons.extend(unauthorized_file_reason(path) for path in disallowed_paths)
    protected_block_reasons = (
        rendered_protected_violations if protected_mode == "enforce" else []
    )
    architecture_drift_detected = (
        freshness.classification != "FRESH"
        or bool(mismatch_reasons)
        or bool(protected_block_reasons)
    )

    print(f"session: {session_path}")
    print(f"policy: {policy_path}")
    print(f"repo: {actual_repo_root}")
    print(f"session context: {session_context_path}")
    print_section(
        "branch:",
        [
            f"expected: {session.expected_branch or '(not specified)'}",
            f"actual: {actual_branch}",
        ],
    )
    print_section("allowed paths:", policy.allowed_paths)
    print_section("protected paths:", policy.protected_paths)
    print_section(
        "$ git status --porcelain=v1 -z:",
        status_summary,
    )
    print_section(
        "$ git diff --name-only:",
        sorted(changed_paths_from_diff(diff_output)),
    )
    print_section(
        "$ git diff --cached --name-only:",
        staged_paths,
    )

    if protected_violations:
        print()
        if protected_mode == "enforce":
            print(f"protected paths: {colorize('FAILED', RED)}")
        else:
            print(f"protected paths: {colorize('WARNING', RED)}")
        print(f"protected mode: {protected_mode}")
        print_section("protected path violations:", rendered_protected_violations)
        print("Guardrail decision: Human review required.")
    else:
        print()
        print(f"protected paths: {colorize('PASSED', GREEN)}")
        print(f"protected mode: {protected_mode}")
        print_section("protected path violations:", [])

    if report_path is not None:
        write_audit_report(
            path=report_path,
            repo=actual_repo_root,
            expected_branch=session.expected_branch,
            actual_branch=actual_branch,
            changed_paths=sorted_changed_paths,
            allowed_paths=policy.allowed_paths,
            violations=[
                *freshness.reasons,
                *mismatch_reasons,
                *protected_block_reasons,
            ],
            status_summary=status_summary,
            stale_reasons=freshness_details,
            protected_violations=rendered_protected_violations,
            architecture_drift_detected=architecture_drift_detected,
        )
        print(f"audit report: {report_path}")

    print_context_freshness(freshness)
    if freshness.classification != "FRESH":
        print_architecture_drift_notice(include_guardrail_message=True)
        return 1

    if mismatch_reasons:
        print_architecture_drift_notice(
            include_scope_message=True,
            include_guardrail_message=True,
        )
        print_section("mismatch reasons:", mismatch_reasons)
        print_section("unauthorized files:", disallowed_paths)
        print(f"verification: {colorize('FAILED', RED)}")
        return 1

    if protected_block_reasons:
        print_architecture_drift_notice(include_guardrail_message=True)
        print_section("mismatch reasons:", protected_block_reasons)
        print(f"verification: {colorize('FAILED', RED)}")
        return 1

    print()
    print_section("mismatch reasons:", [])
    print_section("unauthorized files:", [])
    print(f"verification: {colorize('PASSED', GREEN)}")
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
    parser.add_argument(
        "--report",
        nargs="?",
        const=Path(".contextos/audit/verification_reports/latest.md"),
        type=Path,
        help=(
            "write a markdown audit report to this path "
            "(default when flag is present: .contextos/audit/verification_reports/latest.md)"
        ),
    )
    parser.add_argument(
        "--session-context",
        type=Path,
        help=(
            "path to session_context.json "
            "(default: <repo>/.contextos/session_context.json)"
        ),
    )
    parser.add_argument(
        "--protected-mode",
        choices=("advisory", "enforce"),
        default="advisory",
        help="warn or fail when staged changes touch protected paths",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return verify(
            args.session,
            args.policy,
            args.repo,
            args.report,
            args.session_context,
            args.protected_mode,
        )
    except VerificationError as error:
        print(f"verification: ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
