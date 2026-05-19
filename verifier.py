#!/usr/bin/env python3
"""ContextOS local policy verifier and Git workflow gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_VALID = "VALID"
STATUS_STALE = "STALE"
STATUS_DIVERGED = "DIVERGED"
STATUS_BLOCKED = "BLOCKED"
PROTECTED_ACTIONS = {"commit", "push"}
DEFAULT_POLICY_PATH = Path(".contextos/policy.yaml")
DEFAULT_STATE_PATH = Path(".contextos/state_manifest.json")
DEFAULT_AUDIT_LOG_PATH = Path("audit_log.jsonl")


class Colors:
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colorize(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{color}{text}{Colors.RESET}"


def status_color(status: str) -> str:
    if status == STATUS_VALID:
        return Colors.GREEN
    if status == STATUS_STALE:
        return Colors.YELLOW
    return Colors.RED


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def run_git(args: list[str]) -> str:
    """Run a Git command and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def load_policy(path: Path) -> dict[str, Any]:
    """Load the small YAML subset used by ContextOS policy files.

    The MVP intentionally supports only simple key/value mappings and one level
    of nested mappings so verification stays dependency-free and local-first.
    """
    policy: dict[str, Any] = {}
    current_section: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        if ":" not in line:
            raise ValueError(f"Invalid policy line {line_number}: missing ':'")

        key, raw_value = line.strip().split(":", 1)
        value = parse_scalar(raw_value)

        if indent == 0:
            if raw_value.strip() == "":
                current_section = {}
                policy[key] = current_section
            else:
                policy[key] = value
                current_section = None
        elif indent == 2 and current_section is not None:
            current_section[key] = value
        else:
            raise ValueError(f"Invalid policy line {line_number}: unsupported indentation")

    return policy


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def collect_git_state() -> dict[str, Any]:
    return {
        "remote": run_git(["config", "--get", "remote.origin.url"]),
        "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": run_git(["rev-parse", "HEAD"]),
        "dirty": bool(run_git(["status", "--porcelain"])),
    }


def as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def as_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def mismatch(field: str, expected: Any, actual: Any, severity: str = STATUS_DIVERGED) -> dict[str, Any]:
    return {
        "field": field,
        "expected": expected,
        "actual": actual,
        "severity": severity,
    }


def freshness_findings(
    policy: dict[str, Any],
    state: dict[str, Any],
    git_state: dict[str, Any],
    current_time: datetime,
) -> list[dict[str, Any]]:
    freshness = policy.get("freshness") or {}
    if not isinstance(freshness, dict):
        freshness = {}

    max_age_seconds = as_int(freshness.get("max_age_seconds"), 3600)
    if max_age_seconds <= 0:
        return []

    findings: list[dict[str, Any]] = []
    timestamp_value = state.get("last_verification_timestamp")
    if not timestamp_value:
        findings.append(mismatch("context_freshness", f"<= {max_age_seconds}s", "never verified", STATUS_STALE))
    else:
        try:
            last_verified = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
            age_seconds = int((current_time - last_verified).total_seconds())
            if age_seconds > max_age_seconds:
                findings.append(
                    mismatch("context_freshness", f"<= {max_age_seconds}s", f"{age_seconds}s", STATUS_STALE)
                )
        except ValueError:
            findings.append(mismatch("context_freshness", "valid timestamp", timestamp_value, STATUS_STALE))

    last_branch = state.get("last_verified_branch")
    if last_branch and last_branch != git_state["branch"]:
        findings.append(mismatch("last_verified_branch", git_state["branch"], last_branch, STATUS_STALE))

    last_repo = state.get("last_verified_repo")
    if last_repo and last_repo != git_state["remote"]:
        findings.append(mismatch("last_verified_repo", git_state["remote"], last_repo, STATUS_STALE))

    return findings


def classify(
    policy: dict[str, Any],
    state: dict[str, Any],
    git_state: dict[str, Any],
    action: str,
    current_time: datetime,
) -> tuple[str, str, list[dict[str, Any]]]:
    expected = policy.get("expected") or {}
    if not isinstance(expected, dict):
        return STATUS_BLOCKED, STATUS_BLOCKED, [mismatch("policy.expected", "mapping", type(expected).__name__, STATUS_BLOCKED)]

    enforcement = policy.get("enforcement") or {}
    if not isinstance(enforcement, dict):
        enforcement = {}

    findings: list[dict[str, Any]] = []
    for field in ("remote", "branch"):
        expected_value = expected.get(field)
        if expected_value in (None, ""):
            continue
        if str(git_state[field]) != str(expected_value):
            findings.append(mismatch(field, expected_value, git_state[field], STATUS_DIVERGED))

    expected_commit = expected.get("commit")
    if expected_commit not in (None, "") and str(git_state["commit"]) != str(expected_commit):
        findings.append(mismatch("commit", expected_commit, git_state["commit"], STATUS_BLOCKED))

    block_dirty_on_push = as_bool(enforcement.get("block_push_when_dirty"), True)
    block_dirty_on_commit = as_bool(enforcement.get("block_commit_when_dirty"), False)
    legacy_require_clean = as_bool(policy.get("require_clean_tree"), False)
    should_block_dirty = git_state["dirty"] and (
        legacy_require_clean
        or (action == "push" and block_dirty_on_push)
        or (action == "commit" and block_dirty_on_commit)
    )
    if should_block_dirty:
        findings.append(mismatch("working_tree", "clean", "dirty", STATUS_BLOCKED))

    findings.extend(freshness_findings(policy, state, git_state, current_time))

    if any(item["severity"] == STATUS_BLOCKED for item in findings):
        detected_status = STATUS_BLOCKED
    elif any(item["severity"] == STATUS_DIVERGED for item in findings):
        detected_status = STATUS_DIVERGED
    elif any(item["severity"] == STATUS_STALE for item in findings):
        detected_status = STATUS_STALE
    else:
        detected_status = STATUS_VALID

    final_status = detected_status
    if action in PROTECTED_ACTIONS:
        block_on_divergence = as_bool(enforcement.get(f"block_{action}_on_divergence"), True)
        block_on_stale = as_bool(enforcement.get(f"block_{action}_on_stale"), False)
        if detected_status == STATUS_DIVERGED and block_on_divergence:
            final_status = STATUS_BLOCKED
        elif detected_status == STATUS_STALE and block_on_stale:
            final_status = STATUS_BLOCKED

    return final_status, detected_status, findings


def ensure_parent(path: Path) -> None:
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)


def write_state(path: Path, action: str, status: str, git_state: dict[str, Any], timestamp: datetime) -> None:
    state = {
        "last_verification_timestamp": timestamp.isoformat(),
        "last_verified_branch": git_state["branch"],
        "last_verified_repo": git_state["remote"],
        "last_verified_action": action,
        "last_verified_commit": git_state["commit"],
        "last_status": status,
    }
    ensure_parent(path)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_audit_event(
    audit_log_path: Path,
    *,
    status: str,
    detected_status: str,
    action: str,
    policy_path: Path,
    state_path: Path,
    git_state: dict[str, Any] | None,
    expected: dict[str, Any],
    findings: list[dict[str, Any]],
    error: str | None = None,
    timestamp: datetime,
) -> None:
    event = {
        "timestamp": timestamp.isoformat(),
        "tool": "contextos",
        "command": "verify",
        "action": action,
        "status": status,
        "detected_status": detected_status,
        "policy_path": str(policy_path),
        "state_path": str(state_path),
        "git": git_state,
        "expected": expected,
        "mismatches": findings,
        "error": error,
    }
    ensure_parent(audit_log_path)
    with audit_log_path.open("a", encoding="utf-8") as audit_log:
        audit_log.write(json.dumps(event, sort_keys=True) + "\n")


def human_bool(value: bool) -> str:
    return "dirty" if value else "clean"


def print_report(
    *,
    status: str,
    detected_status: str,
    action: str,
    git_state: dict[str, Any] | None,
    findings: list[dict[str, Any]],
    error: str | None,
) -> None:
    use_color = supports_color()
    print(colorize("ContextOS verification", Colors.BOLD, use_color))
    print(f"Action: {action}")
    print(f"Status: {colorize(status, status_color(status), use_color)}")
    if detected_status != status:
        print(f"Detected: {detected_status}")

    if git_state:
        print("Git:")
        print(f"  repo:   {git_state['remote']}")
        print(f"  branch: {git_state['branch']}")
        print(f"  commit: {git_state['commit']}")
        print(f"  tree:   {human_bool(bool(git_state['dirty']))}")

    if findings:
        print("Mismatches:")
        for item in findings:
            print(
                "  - {field}: expected {expected!r}, found {actual!r} ({severity})".format(
                    field=item["field"],
                    expected=item["expected"],
                    actual=item["actual"],
                    severity=item["severity"],
                )
            )
    else:
        print("Mismatches: none")

    if error:
        print(f"Error: {error}")

    print("Remediation:")
    print("  - Run git status")
    print("  - Verify current branch")
    print("  - Resync Cursor context")

    if status == STATUS_BLOCKED:
        print(colorize(f"ContextOS blocked {action}: contextual legitimacy check failed.", Colors.RED, use_color))
    elif status == STATUS_DIVERGED:
        print(colorize("ContextOS detected repo or branch drift.", Colors.YELLOW, use_color))
    elif status == STATUS_STALE:
        print(colorize("ContextOS detected stale context freshness.", Colors.YELLOW, use_color))
    else:
        print(colorize("ContextOS verification passed.", Colors.GREEN, use_color))


def verify(policy_path: Path, audit_log_path: Path, state_path: Path, action: str) -> int:
    git_state: dict[str, Any] | None = None
    policy: dict[str, Any] = {}
    status = STATUS_BLOCKED
    detected_status = STATUS_BLOCKED
    findings: list[dict[str, Any]] = []
    error: str | None = None
    timestamp = now_utc()

    try:
        policy = load_policy(policy_path)
        state = load_state(state_path)
        git_state = collect_git_state()
        status, detected_status, findings = classify(policy, state, git_state, action, timestamp)
        write_state(state_path, action, status, git_state, timestamp)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        error = str(exc)
        status = STATUS_BLOCKED
        detected_status = STATUS_BLOCKED
        findings = [mismatch("verification_error", "successful verification", error, STATUS_BLOCKED)]

    expected = policy.get("expected") if isinstance(policy.get("expected"), dict) else {}
    write_audit_event(
        audit_log_path,
        status=status,
        detected_status=detected_status,
        action=action,
        policy_path=policy_path,
        state_path=state_path,
        git_state=git_state,
        expected=expected,
        findings=findings,
        error=error,
        timestamp=timestamp,
    )
    print_report(
        status=status,
        detected_status=detected_status,
        action=action,
        git_state=git_state,
        findings=findings,
        error=error,
    )
    return 1 if status == STATUS_BLOCKED else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contextos", description="ContextOS CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="verify the current repo against ContextOS policy")
    verify_parser.add_argument(
        "--action",
        choices=["manual", "commit", "push"],
        default="manual",
        help="protected workflow action being verified",
    )
    verify_parser.add_argument(
        "--policy",
        default=DEFAULT_POLICY_PATH,
        type=Path,
        help="path to the local policy file",
    )
    verify_parser.add_argument(
        "--audit-log",
        default=DEFAULT_AUDIT_LOG_PATH,
        type=Path,
        help="path to append structured audit events",
    )
    verify_parser.add_argument(
        "--state",
        default=DEFAULT_STATE_PATH,
        type=Path,
        help="path to the local context freshness manifest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "verify":
        return verify(args.policy, args.audit_log, args.state, args.action)

    parser.error(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
