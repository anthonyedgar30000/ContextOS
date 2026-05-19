#!/usr/bin/env python3
"""ContextOS local policy verifier."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_VALID = "VALID"
STATUS_STALE = "STALE"
STATUS_DIVERGED = "DIVERGED"
STATUS_BLOCKED = "BLOCKED"


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
    return value


def load_policy(path: Path) -> dict[str, Any]:
    """Load the small YAML subset used by policy.yaml.

    This intentionally supports only simple key/value mappings and one level of
    nested mappings so the prototype stays dependency-free.
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


def collect_git_state() -> dict[str, Any]:
    return {
        "remote": run_git(["config", "--get", "remote.origin.url"]),
        "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": run_git(["rev-parse", "HEAD"]),
        "dirty": bool(run_git(["status", "--porcelain"])),
    }


def classify(policy: dict[str, Any], git_state: dict[str, Any]) -> tuple[str, list[str]]:
    expected = policy.get("expected") or {}
    if not isinstance(expected, dict):
        return STATUS_BLOCKED, ["policy.expected must be a mapping"]

    mismatches: list[str] = []
    for field in ("remote", "branch", "commit"):
        expected_value = expected.get(field)
        if expected_value in (None, ""):
            continue
        if str(git_state[field]) != str(expected_value):
            mismatches.append(field)

    if policy.get("require_clean_tree", True) and git_state["dirty"]:
        return STATUS_BLOCKED, [*mismatches, "dirty"]
    if "remote" in mismatches or "branch" in mismatches:
        return STATUS_DIVERGED, mismatches
    if "commit" in mismatches:
        return STATUS_STALE, mismatches
    return STATUS_VALID, mismatches


def write_audit_event(
    audit_log_path: Path,
    status: str,
    policy_path: Path,
    git_state: dict[str, Any] | None,
    expected: dict[str, Any],
    mismatches: list[str],
    error: str | None = None,
) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": "contextos",
        "command": "verify",
        "status": status,
        "policy_path": str(policy_path),
        "git": git_state,
        "expected": expected,
        "mismatches": mismatches,
        "error": error,
    }
    with audit_log_path.open("a", encoding="utf-8") as audit_log:
        audit_log.write(json.dumps(event, sort_keys=True) + "\n")


def verify(policy_path: Path, audit_log_path: Path) -> int:
    git_state: dict[str, Any] | None = None
    policy: dict[str, Any] = {}
    status = STATUS_BLOCKED
    mismatches: list[str] = []
    error: str | None = None

    try:
        policy = load_policy(policy_path)
        git_state = collect_git_state()
        status, mismatches = classify(policy, git_state)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        error = str(exc)
        status = STATUS_BLOCKED
        mismatches = ["verification_error"]

    expected = policy.get("expected") if isinstance(policy.get("expected"), dict) else {}
    write_audit_event(audit_log_path, status, policy_path, git_state, expected, mismatches, error)
    print(status)
    return 1 if status == STATUS_BLOCKED else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contextos", description="ContextOS CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="verify the current repo against policy.yaml")
    verify_parser.add_argument(
        "--policy",
        default="policy.yaml",
        type=Path,
        help="path to the local policy file",
    )
    verify_parser.add_argument(
        "--audit-log",
        default="audit_log.jsonl",
        type=Path,
        help="path to append structured audit events",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "verify":
        return verify(args.policy, args.audit_log)

    parser.error(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
