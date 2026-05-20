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
import verify_cli


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


@dataclass(frozen=True)
class ExecutionPlanOverview:
    source_path: Path
    plan_task_name: str
    original_objective: str
    implementation_summary: str
    files_changed: str
    tests_run: str
    test_results: str
    policy_verification_result: str
    unresolved_issues: str
    recommended_next_action: str
    recommended_git_commands: tuple[str, ...]
    human_approval_required: str


@dataclass(frozen=True)
class RepoState:
    repo_root: Path
    current_branch: str
    current_head: str
    dirty_working_tree: bool
    staged_changes: tuple[str, ...]
    unstaged_changes: tuple[str, ...]
    untracked_files: tuple[str, ...]


@dataclass(frozen=True)
class StateSwitchRequest:
    target_repo: Path
    target_branch: str
    reason: str
    requested_by: str
    source_context: str
    expected_current_branch: str
    expected_current_head: str
    approved: bool


@dataclass(frozen=True)
class ExecutionFreshnessPlan:
    source_path: Path
    plan_task_name: str
    original_objective: str
    plan_timestamp: str
    expected_branch: str
    expected_head: str
    expected_files_scope: tuple[str, ...]
    last_verified_branch: str
    last_verified_head: str
    last_verified_status: str


@dataclass(frozen=True)
class ExecutionFreshnessResult:
    classification: str
    reasoning_summary: str
    mismatch_sources: tuple[str, ...]
    recommended_next_action: str
    replan_recommended: bool
    execution_blocked: bool


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
EXECUTION_SECTION_ALIASES = {
    "plan/task name": "plan_task_name",
    "plan task name": "plan_task_name",
    "task": "plan_task_name",
    "original objective": "original_objective",
    "objective": "original_objective",
    "implementation summary": "implementation_summary",
    "files changed": "files_changed",
    "tests run": "tests_run",
    "test results": "test_results",
    "policy/verification result": "policy_verification_result",
    "policy verification result": "policy_verification_result",
    "verification result": "policy_verification_result",
    "unresolved issues": "unresolved_issues",
    "recommended next action": "recommended_next_action",
    "recommended git command": "recommended_git_commands",
    "recommended git commands": "recommended_git_commands",
    "recommended git actions": "recommended_git_commands",
    "human approval required": "human_approval_required",
    "plan timestamp": "plan_timestamp",
    "execution plan timestamp": "plan_timestamp",
    "expected branch": "expected_branch",
    "expected current branch": "expected_branch",
    "expected head": "expected_head",
    "expected current head": "expected_head",
    "expected files/scope": "expected_files_scope",
    "expected files": "expected_files_scope",
    "expected scope": "expected_files_scope",
    "allowed files": "expected_files_scope",
    "allowed paths": "expected_files_scope",
    "last verified repo state": "last_verified_status",
    "last verified status": "last_verified_status",
    "last verified branch": "last_verified_branch",
    "last verified head": "last_verified_head",
    "last verified head hash": "last_verified_head",
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


def run_git_checked(args: Sequence[str], repo: Path) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


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


def verify(
    session_path: Path,
    policy_path: Path,
    repo: Path,
    report_path: Path | None,
    session_context_path: Path | None,
    protected_mode: str,
) -> int:
    return verify_cli.verify(
        session_path=session_path,
        policy_path=policy_path,
        repo=repo,
        report_path=report_path,
        session_context_path=session_context_path,
        protected_mode=protected_mode,
    )


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


def markdown_value(value: str) -> str:
    return value.strip() or "(not provided)"


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


def latest_path(paths: Sequence[Path]) -> Path | None:
    existing_paths = [path for path in paths if path.exists() and path.is_file()]
    if not existing_paths:
        return None
    return sorted(
        existing_paths,
        key=lambda path: (path.stat().st_mtime_ns, str(path)),
        reverse=True,
    )[0]


def execution_result_candidates(repo: Path) -> list[Path]:
    audit_root = repo / ".contextos" / "audit"
    return [
        repo / ".contextos" / "execution_result.md",
        *sorted((audit_root / "execution_results").glob("*.md")),
        *sorted((audit_root / "verification_reports").glob("*.md")),
    ]


def find_latest_execution_result(repo: Path) -> Path:
    latest = latest_path(execution_result_candidates(repo))
    if latest is None:
        raise ContextOSError(
            "No execution result found. Create one by writing "
            ".contextos/execution_result.md, saving a Cursor response to "
            ".contextos/audit/execution_results/, or saving a verification "
            "report to .contextos/audit/verification_reports/."
        )
    return latest


def normalized_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    heading = stripped.lstrip("#").strip()
    return heading.lower() if heading else None


def parse_markdown_sections(text: str) -> tuple[str | None, dict[str, str]]:
    title: str | None = None
    sections: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in text.splitlines():
        heading = normalized_heading(line)
        if heading is not None:
            if title is None and line.strip().startswith("# "):
                title = line.strip().lstrip("#").strip()
            current_key = EXECUTION_SECTION_ALIASES.get(heading)
            if current_key is not None:
                sections.setdefault(current_key, [])
            continue

        if current_key is not None:
            sections[current_key].append(line)

    return title, {
        key: "\n".join(lines).strip()
        for key, lines in sections.items()
    }


def strip_markdown_command(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("- "):
        stripped = stripped[2:].strip()
    if stripped.startswith("* "):
        stripped = stripped[2:].strip()
    return stripped.strip("`").strip()


def extract_recommended_git_commands(section_text: str) -> tuple[str, ...]:
    commands = []
    in_code_block = False
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        candidate = strip_markdown_command(line)
        if candidate.startswith("git "):
            commands.append(candidate)

    return tuple(dict.fromkeys(commands))


def parse_execution_plan_overview(path: Path) -> ExecutionPlanOverview:
    text = path.read_text(encoding="utf-8")
    title, sections = parse_markdown_sections(text)
    git_command_section = sections.get("recommended_git_commands", "")

    return ExecutionPlanOverview(
        source_path=path,
        plan_task_name=markdown_value(sections.get("plan_task_name", "") or title or ""),
        original_objective=markdown_value(sections.get("original_objective", "")),
        implementation_summary=markdown_value(sections.get("implementation_summary", "")),
        files_changed=markdown_value(sections.get("files_changed", "")),
        tests_run=markdown_value(sections.get("tests_run", "")),
        test_results=markdown_value(sections.get("test_results", "")),
        policy_verification_result=markdown_value(
            sections.get("policy_verification_result", "")
        ),
        unresolved_issues=markdown_value(sections.get("unresolved_issues", "")),
        recommended_next_action=markdown_value(
            sections.get("recommended_next_action", "")
        ),
        recommended_git_commands=extract_recommended_git_commands(git_command_section),
        human_approval_required=markdown_value(
            sections.get("human_approval_required", "")
        ),
    )


def render_git_command_explanations(commands: Sequence[str]) -> str:
    if not commands:
        return "- (none)"

    rendered = []
    for command in commands:
        try:
            explanation = explain_git_command(command)
        except GitCommandExplanationError as error:
            rendered.append(
                "\n".join(
                    [
                        f"### `{command}`",
                        "",
                        f"- Explanation: {error}",
                        "- Risk: (not available)",
                        "- Potential consequences: (not available)",
                        "- Changes state: (not available)",
                    ]
                )
            )
            continue

        rendered.append(
            "\n".join(
                [
                    f"### `{explanation.command}`",
                    "",
                    f"- Explanation: {explanation.explanation}",
                    f"- Risk: `{explanation.risk}`",
                    f"- Potential consequences: {explanation.consequences}",
                    f"- Changes state: {'yes' if explanation.changes_state else 'no'}",
                ]
            )
        )

    return "\n\n".join(rendered)


def git_status_summary(repo: Path) -> str:
    status = run_git(["status", "--porcelain=v1", "-b"], repo)
    return status or "## clean"


def render_last_plan_report(overview: ExecutionPlanOverview, repo: Path) -> str:
    return "\n".join(
        [
            "# Last executed Cursor plan overview",
            "",
            f"- Source: {overview.source_path}",
            f"- Current branch: {current_branch(repo)}",
            f"- Current HEAD hash: {head_hash(repo)}",
            "",
            "## Plan/task name",
            overview.plan_task_name,
            "",
            "## Original objective",
            overview.original_objective,
            "",
            "## Implementation summary",
            overview.implementation_summary,
            "",
            "## Files changed",
            overview.files_changed,
            "",
            "## Tests run",
            overview.tests_run,
            "",
            "## Test results",
            overview.test_results,
            "",
            "## Git status summary",
            "```text",
            git_status_summary(repo),
            "```",
            "",
            "## Policy/verification result",
            overview.policy_verification_result,
            "",
            "## Unresolved issues",
            overview.unresolved_issues,
            "",
            "## Recommended next action",
            overview.recommended_next_action,
            "",
            "## Recommended Git command explanations",
            render_git_command_explanations(overview.recommended_git_commands),
            "",
            "## Human approval required",
            overview.human_approval_required,
            "",
            "## Export constraints",
            "- No ChatGPT API call was made.",
            "- No Cursor API call was made.",
            "- No Git state was changed.",
            "- This report was generated from local files and local Git state.",
            "",
        ]
    )


def export_last_plan(repo: Path) -> int:
    root = repo_root(repo)
    source_path = find_latest_execution_result(root)
    overview = parse_execution_plan_overview(source_path)
    print(render_last_plan_report(overview, root))
    return 0


def parse_markdown_list_items(section_text: str) -> tuple[str, ...]:
    items = []
    in_code_block = False
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip("`").strip())
    if items:
        return tuple(dict.fromkeys(item for item in items if item))
    if section_text.strip() and section_text.strip() != "(not provided)":
        return (section_text.strip(),)
    return ()


def parse_execution_plan(path: Path) -> ExecutionFreshnessPlan:
    text = path.read_text(encoding="utf-8")
    title, sections = parse_markdown_sections(text)
    expected_scope = tuple(
        dict.fromkeys(
            normalize_repo_path(item, source="execution plan expected files/scope")
            for item in parse_markdown_list_items(sections.get("expected_files_scope", ""))
        )
    )

    return ExecutionFreshnessPlan(
        source_path=path,
        plan_task_name=markdown_value(sections.get("plan_task_name", "") or title or ""),
        original_objective=markdown_value(sections.get("original_objective", "")),
        plan_timestamp=markdown_value(sections.get("plan_timestamp", "")),
        expected_branch=markdown_value(sections.get("expected_branch", "")),
        expected_head=markdown_value(sections.get("expected_head", "")),
        expected_files_scope=expected_scope,
        last_verified_branch=markdown_value(sections.get("last_verified_branch", "")),
        last_verified_head=markdown_value(sections.get("last_verified_head", "")),
        last_verified_status=markdown_value(sections.get("last_verified_status", "")),
    )


def execution_plan_candidates(repo: Path) -> list[Path]:
    audit_root = repo / ".contextos" / "audit"
    return [
        repo / ".contextos" / "execution_plan.md",
        repo / ".contextos" / "execution_result.md",
        *sorted((audit_root / "execution_results").glob("*.md")),
        *sorted((audit_root / "verification_reports").glob("*.md")),
    ]


def find_latest_execution_plan(repo: Path) -> Path:
    latest = latest_path(execution_plan_candidates(repo))
    if latest is None:
        raise ContextOSError(
            "No execution plan found. Create one at .contextos/execution_plan.md "
            "or save a recent execution result under .contextos/audit/execution_results/."
        )
    return latest


def parse_plan_timestamp(timestamp: str) -> datetime | None:
    if timestamp == "(not provided)":
        return None
    normalized = timestamp.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plan_age_hours(timestamp: str) -> float | None:
    parsed = parse_plan_timestamp(timestamp)
    if parsed is None:
        return None
    age = datetime.now(timezone.utc) - parsed
    return age.total_seconds() / 3600


def path_in_scope(path: str, scope: Sequence[str]) -> bool:
    normalized = normalize_repo_path(path, source="git status")
    return any(normalized == item or normalized.startswith(f"{item}/") for item in scope)


def changed_paths_for_state(state: RepoState) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for path in {
                *state.staged_changes,
                *state.unstaged_changes,
                *state.untracked_files,
            }
            if not path == ".contextos" and not path.startswith(".contextos/")
        )
    )


def unauthorized_paths_for_plan(plan: ExecutionFreshnessPlan, state: RepoState) -> tuple[str, ...]:
    if not plan.expected_files_scope:
        return ()
    return tuple(
        path for path in changed_paths_for_state(state) if not path_in_scope(path, plan.expected_files_scope)
    )


def evaluate_execution_freshness(
    *,
    plan: ExecutionFreshnessPlan,
    state: RepoState,
    freshness_threshold_hours: int,
) -> ExecutionFreshnessResult:
    mismatches: list[str] = []
    unauthorized_paths = unauthorized_paths_for_plan(plan, state)
    application_changes_exist = bool(changed_paths_for_state(state))
    age_hours = plan_age_hours(plan.plan_timestamp)
    timestamp_stale = age_hours is None or age_hours > freshness_threshold_hours

    if plan.expected_branch != "(not provided)" and plan.expected_branch != state.current_branch:
        mismatches.append(
            f"branch mismatch: expected {plan.expected_branch}, current {state.current_branch}"
        )
    if plan.expected_head != "(not provided)" and plan.expected_head != state.current_head:
        mismatches.append("HEAD mismatch: current HEAD differs from execution plan")
    if plan.last_verified_branch != "(not provided)" and plan.last_verified_branch != state.current_branch:
        mismatches.append(
            "last verified branch mismatch: "
            f"expected {plan.last_verified_branch}, current {state.current_branch}"
        )
    if plan.last_verified_head != "(not provided)" and plan.last_verified_head != state.current_head:
        mismatches.append("last verified HEAD mismatch: repository evolved after verification")
    for path in unauthorized_paths:
        mismatches.append(f"unauthorized file modification: {path}")

    if mismatches:
        classification = "DIVERGED"
        reasoning_summary = "Execution context diverged from the plan state."
        recommended_next_action = "Stop execution, regenerate the plan, and rerun verification."
        return ExecutionFreshnessResult(
            classification=classification,
            reasoning_summary=reasoning_summary,
            mismatch_sources=tuple(dict.fromkeys(mismatches)),
            recommended_next_action=recommended_next_action,
            replan_recommended=True,
            execution_blocked=True,
        )

    if timestamp_stale:
        age_text = "unknown" if age_hours is None else f"{age_hours:.2f} hours"
        return ExecutionFreshnessResult(
            classification="STALE",
            reasoning_summary=(
                "Execution plan timestamp is outside the freshness threshold "
                f"({age_text}; threshold {freshness_threshold_hours} hours)."
            ),
            mismatch_sources=("execution plan timestamp exceeded freshness threshold",),
            recommended_next_action="Regenerate the context packet and execution plan before continuing.",
            replan_recommended=True,
            execution_blocked=True,
        )

    if application_changes_exist:
        return ExecutionFreshnessResult(
            classification="AGING",
            reasoning_summary=(
                "Branch and HEAD still match, but local changes exist. Assumptions may still hold."
            ),
            mismatch_sources=("local working tree has staged, unstaged, or untracked changes",),
            recommended_next_action="Review local changes and rerun verification before committing.",
            replan_recommended=False,
            execution_blocked=False,
        )

    return ExecutionFreshnessResult(
        classification="FRESH",
        reasoning_summary="Branch, HEAD, scope, timestamp, and working tree match the plan assumptions.",
        mismatch_sources=(),
        recommended_next_action="Continue with verification before commit.",
        replan_recommended=False,
        execution_blocked=False,
    )


def render_freshness_report(
    *,
    plan: ExecutionFreshnessPlan,
    state: RepoState,
    result: ExecutionFreshnessResult,
    freshness_threshold_hours: int,
) -> str:
    return "\n".join(
        [
            "# ContextOS execution freshness report",
            "",
            f"- Source plan: {plan.source_path}",
            f"- Plan/task name: {plan.plan_task_name}",
            f"- Original objective: {plan.original_objective}",
            f"- Execution plan timestamp: {plan.plan_timestamp}",
            f"- Freshness threshold hours: {freshness_threshold_hours}",
            "",
            "## Classification",
            result.classification,
            "",
            "## Reasoning summary",
            result.reasoning_summary,
            "",
            "## Exact mismatch sources",
            markdown_list(result.mismatch_sources),
            "",
            "## Current repository state",
            "",
            f"- Current branch: {state.current_branch}",
            f"- Current HEAD: {state.current_head}",
            f"- Dirty working tree: {'yes' if state.dirty_working_tree else 'no'}",
            "",
            "### Current changed files",
            markdown_list(changed_paths_for_state(state)),
            "",
            "## Expected plan state",
            "",
            f"- Expected branch: {plan.expected_branch}",
            f"- Expected HEAD: {plan.expected_head}",
            f"- Last verified branch: {plan.last_verified_branch}",
            f"- Last verified HEAD: {plan.last_verified_head}",
            "",
            "### Expected files/scope",
            markdown_list(plan.expected_files_scope),
            "",
            "## Last verified repo state",
            plan.last_verified_status,
            "",
            "## Recommended next action",
            result.recommended_next_action,
            "",
            "## Re-planning recommended",
            "yes" if result.replan_recommended else "no",
            "",
            "## Execution should be blocked",
            "yes" if result.execution_blocked else "no",
            "",
            "## Architectural rule",
            "Reasoning generated against one repo state should not automatically retain mutation authority after repo-state divergence.",
            "",
        ]
    )


def write_freshness_report(repo: Path, report: str) -> tuple[Path, Path]:
    report_path = repo / ".contextos" / "freshness_report.md"
    audit_dir = repo / ".contextos" / "audit" / "freshness_reports"
    audit_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{audit_timestamp()}_freshness_report.md"
    report_path.write_text(report, encoding="utf-8")
    audit_path.write_text(report, encoding="utf-8")
    return report_path, audit_path


def verify_freshness(
    *,
    repo: Path,
    plan_path: Path | None,
    freshness_threshold_hours: int,
) -> int:
    root = repo_root(repo)
    if plan_path is None:
        plan_path = find_latest_execution_plan(root)
    elif not plan_path.is_absolute():
        plan_path = root / plan_path

    plan = parse_execution_plan(plan_path)
    state = repo_state(root)
    result = evaluate_execution_freshness(
        plan=plan,
        state=state,
        freshness_threshold_hours=freshness_threshold_hours,
    )
    report = render_freshness_report(
        plan=plan,
        state=state,
        result=result,
        freshness_threshold_hours=freshness_threshold_hours,
    )
    report_path, audit_path = write_freshness_report(root, report)
    print(report)
    print("Freshness report:")
    print(f"  {report_path}")
    print("Audit copy:")
    print(f"  {audit_path}")
    return 0 if result.classification in {"FRESH", "AGING"} else 1


def repo_state(repo: Path) -> RepoState:
    root = repo_root(repo)
    status_lines = run_git(["status", "--porcelain=v1"], root).splitlines()
    staged_changes: list[str] = []
    unstaged_changes: list[str] = []
    untracked_files: list[str] = []

    for line in status_lines:
        if not line:
            continue
        status = line[:2]
        path = line[3:] if len(line) > 2 and line[2] == " " else line[2:].lstrip()
        if status == "??":
            untracked_files.append(path)
            continue
        if status[0] != " ":
            staged_changes.append(path)
        if status[1] != " ":
            unstaged_changes.append(path)

    return RepoState(
        repo_root=root,
        current_branch=current_branch(root),
        current_head=head_hash(root),
        dirty_working_tree=bool(status_lines),
        staged_changes=tuple(sorted(staged_changes)),
        unstaged_changes=tuple(sorted(unstaged_changes)),
        untracked_files=tuple(sorted(untracked_files)),
    )


def local_branch_exists(repo: Path, branch: str) -> bool:
    exit_code, _, _ = run_git_checked(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        repo,
    )
    return exit_code == 0


def remote_branch_exists(repo: Path, branch: str) -> bool:
    exit_code, _, _ = run_git_checked(
        ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
        repo,
    )
    return exit_code == 0


def proposed_switch_commands(state: RepoState, target_branch: str) -> tuple[str, ...]:
    if local_branch_exists(state.repo_root, target_branch):
        return (f"git switch {target_branch}",)
    if remote_branch_exists(state.repo_root, target_branch):
        return ("git fetch", f"git switch {target_branch}")
    return ("git fetch", f"git switch {target_branch}")


def switch_validation_reasons(
    request: StateSwitchRequest,
    state: RepoState,
) -> tuple[str, ...]:
    reasons = []
    if request.expected_current_branch != state.current_branch:
        reasons.append(
            "expected current branch "
            f"{request.expected_current_branch}, observed {state.current_branch}"
        )
    if request.expected_current_head != state.current_head:
        reasons.append(
            "expected current HEAD "
            f"{request.expected_current_head}, observed {state.current_head}"
        )
    if state.dirty_working_tree:
        reasons.append("working tree is dirty; automatic switching is blocked")
    return tuple(reasons)


def safe_read_only_commands() -> tuple[str, ...]:
    return (
        "git status",
        "git status --short --branch",
        "git diff --name-only",
        "git diff --cached --name-only",
        "git branch --show-current",
        "git rev-parse HEAD",
    )


def render_switch_report(
    *,
    request: StateSwitchRequest,
    state_before: RepoState,
    proposed_commands: Sequence[str],
    validation_reasons: Sequence[str],
    execution_status: str,
    state_after: RepoState | None,
) -> str:
    command_explanations = render_git_command_explanations(
        [*safe_read_only_commands(), *proposed_commands]
    )
    state_after_lines = (
        [
            f"- Current branch: {state_after.current_branch}",
            f"- Current HEAD: {state_after.current_head}",
        ]
        if state_after is not None
        else ["- (not executed)"]
    )

    return "\n".join(
        [
            "# ContextOS repo-state switch request",
            "",
            "## Request",
            "",
            f"- Target repo: {request.target_repo}",
            f"- Target branch: {request.target_branch}",
            f"- Reason: {request.reason}",
            f"- Requested by: {request.requested_by}",
            f"- Source context: {request.source_context}",
            f"- Expected current branch: {request.expected_current_branch}",
            f"- Expected current HEAD: {request.expected_current_head}",
            f"- Human approval provided: {'yes' if request.approved else 'no'}",
            "",
            "## Current Git state before request",
            "",
            f"- Repo root: {state_before.repo_root}",
            f"- Current branch: {state_before.current_branch}",
            f"- Current HEAD: {state_before.current_head}",
            f"- Dirty working tree: {'yes' if state_before.dirty_working_tree else 'no'}",
            "",
            "### Staged changes",
            markdown_list(state_before.staged_changes),
            "",
            "### Unstaged changes",
            markdown_list(state_before.unstaged_changes),
            "",
            "### Untracked files",
            markdown_list(state_before.untracked_files),
            "",
            "## Validation result",
            "",
            markdown_list(validation_reasons),
            "",
            "## Proposed Git commands",
            "",
            markdown_list(proposed_commands),
            "",
            "## Recommended safe read-only commands first",
            "",
            markdown_list(safe_read_only_commands()),
            "",
            "## Git command explanations",
            "",
            command_explanations,
            "",
            "## Execution status",
            "",
            execution_status,
            "",
            "## Git state after execution",
            "",
            "\n".join(state_after_lines),
            "",
            "## Human approval requirement",
            "",
            "State-changing Git commands require explicit human approval via `--approve`.",
            "",
        ]
    )


def write_state_switch_report(repo: Path, report: str) -> tuple[Path, Path]:
    report_path = repo / ".contextos" / "state_switch_report.md"
    audit_dir = repo / ".contextos" / "audit" / "state_switches"
    audit_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{audit_timestamp()}_state_switch_report.md"
    report_path.write_text(report, encoding="utf-8")
    audit_path.write_text(report, encoding="utf-8")
    return report_path, audit_path


def request_switch(
    *,
    target_repo: Path,
    target_branch: str,
    reason: str,
    requested_by: str,
    source_context: str,
    expected_current_branch: str,
    expected_current_head: str,
    approve: bool,
) -> int:
    state_before = repo_state(target_repo)
    request = StateSwitchRequest(
        target_repo=target_repo,
        target_branch=target_branch,
        reason=reason,
        requested_by=requested_by,
        source_context=source_context,
        expected_current_branch=expected_current_branch,
        expected_current_head=expected_current_head,
        approved=approve,
    )
    proposed_commands = proposed_switch_commands(state_before, target_branch)
    validation_reasons = switch_validation_reasons(request, state_before)
    execution_status = "Not executed. Explicit human approval is required."
    state_after: RepoState | None = None
    exit_code = 0

    if approve:
        if validation_reasons:
            execution_status = (
                "Not executed. Validation failed; state-changing commands were blocked."
            )
            exit_code = 1
        elif proposed_commands != (f"git switch {target_branch}",):
            execution_status = (
                "Not executed. Target branch is not available locally; review "
                "`git fetch` and retry after confirming remote state."
            )
            exit_code = 1
        else:
            switch_exit, _, switch_error = run_git_checked(
                ["switch", target_branch],
                state_before.repo_root,
            )
            if switch_exit != 0:
                execution_status = (
                    "Execution failed. git switch returned: "
                    f"{switch_error or 'no error output'}"
                )
                exit_code = 1
            else:
                state_after = repo_state(state_before.repo_root)
                if state_after.current_branch != target_branch:
                    execution_status = (
                        "Execution failed. Current branch does not match target branch."
                    )
                    exit_code = 1
                else:
                    execution_status = "Executed. Current branch verified after switch."

    report = render_switch_report(
        request=request,
        state_before=state_before,
        proposed_commands=proposed_commands,
        validation_reasons=validation_reasons,
        execution_status=execution_status,
        state_after=state_after,
    )
    report_path, audit_path = write_state_switch_report(state_before.repo_root, report)
    print(report)
    print("State switch report:")
    print(f"  {report_path}")
    print("Audit copy:")
    print(f"  {audit_path}")
    return exit_code


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
    verify_parser = subparsers.add_parser(
        "verify",
        help="run deterministic ContextOS verification",
    )
    verify_parser.add_argument(
        "--session",
        default=Path("session.json"),
        type=Path,
        help="path to session.json (default: session.json)",
    )
    verify_parser.add_argument(
        "--policy",
        default=Path("policy.yaml"),
        type=Path,
        help="path to policy.yaml (default: policy.yaml)",
    )
    verify_parser.add_argument(
        "--report",
        type=Path,
        help="write a markdown audit report to this path",
    )
    verify_parser.add_argument(
        "--session-context",
        type=Path,
        help=(
            "path to session_context.json "
            "(default: <repo>/.contextos/session_context.json)"
        ),
    )
    verify_parser.add_argument(
        "--protected-mode",
        choices=("advisory", "enforce"),
        default="advisory",
        help="warn or fail when staged changes touch protected paths",
    )
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
    subparsers.add_parser(
        "export-last-plan",
        help="export the latest local Cursor execution result for ChatGPT review",
    )
    switch_parser = subparsers.add_parser(
        "request-switch",
        help="request a validated repo/branch state switch",
    )
    switch_parser.add_argument("--target-repo", required=True, type=Path)
    switch_parser.add_argument("--target-branch", required=True)
    switch_parser.add_argument("--reason", required=True)
    switch_parser.add_argument("--requested-by", required=True)
    switch_parser.add_argument("--source-context", required=True)
    switch_parser.add_argument("--expected-current-branch", required=True)
    switch_parser.add_argument("--expected-current-head", required=True)
    switch_parser.add_argument(
        "--approve",
        action="store_true",
        help="execute the state-changing switch if validation passes",
    )
    freshness_parser = subparsers.add_parser(
        "verify-freshness",
        help="classify whether an execution plan still matches current repo state",
    )
    freshness_parser.add_argument(
        "--plan",
        type=Path,
        help="path to execution plan markdown (default: latest local execution plan/result)",
    )
    freshness_parser.add_argument(
        "--freshness-threshold-hours",
        type=int,
        default=24,
        help="maximum age before a plan is classified STALE (default: 24)",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "verify":
            return verify(
                session_path=args.session,
                policy_path=args.policy,
                repo=args.repo,
                report_path=args.report,
                session_context_path=args.session_context,
                protected_mode=args.protected_mode,
            )
        if args.command == "ingest":
            return ingest(args.context_packet, args.repo)
        if args.command == "explain-git":
            return explain_git(args.git_command, args.format)
        if args.command == "create-issue":
            return create_issue(args.packet, args.repo, args.output)
        if args.command == "export-last-plan":
            return export_last_plan(args.repo)
        if args.command == "request-switch":
            return request_switch(
                target_repo=args.target_repo,
                target_branch=args.target_branch,
                reason=args.reason,
                requested_by=args.requested_by,
                source_context=args.source_context,
                expected_current_branch=args.expected_current_branch,
                expected_current_head=args.expected_current_head,
                approve=args.approve,
            )
        if args.command == "verify-freshness":
            return verify_freshness(
                repo=args.repo,
                plan_path=args.plan,
                freshness_threshold_hours=args.freshness_threshold_hours,
            )
    except ContextOSError as error:
        print(f"contextos: ERROR: {error}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
