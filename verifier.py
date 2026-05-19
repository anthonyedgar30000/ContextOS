#!/usr/bin/env python3
"""ContextOS local policy verifier and AI execution-context gate."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
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
SEVERITY_WARN = "WARN"

CONTEXT_FRESH = "FRESH"
CONTEXT_AGING = "AGING"
CONTEXT_STALE = "STALE"
CONTEXT_DIVERGED = "DIVERGED"

PROTECTED_ACTIONS = {"commit", "push"}
DEFAULT_POLICY_PATH = Path(".contextos/policy.yaml")
DEFAULT_STATE_PATH = Path(".contextos/state_manifest.json")
DEFAULT_SESSION_PATH = Path(".contextos/session_context.json")
DEFAULT_AUDIT_LOG_PATH = Path("audit_log.jsonl")

DEPENDENCY_CONFIG_DEFAULTS = [
    "requirements*.txt",
    "**/requirements*.txt",
    "package.json",
    "**/package.json",
    "pyproject.toml",
    "**/pyproject.toml",
    "Dockerfile",
    "**/Dockerfile",
    ".env*",
    "**/.env*",
    "*config*.json",
    "**/*config*.json",
    "*config*.yaml",
    "**/*config*.yaml",
    "*config*.yml",
    "**/*config*.yml",
]


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


def context_color(score: str) -> str:
    if score == CONTEXT_FRESH:
        return Colors.GREEN
    if score == CONTEXT_AGING:
        return Colors.YELLOW
    return Colors.RED


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def run_git(args: list[str], check: bool = True) -> str:
    result = subprocess.run(["git", *args], check=check, capture_output=True, text=True)
    return result.stdout.strip()


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def load_policy(path: Path) -> dict[str, Any]:
    """Load the small YAML subset used by ContextOS policy files.

    Supported forms are top-level scalars, top-level lists, and one level of
    nested mappings. This keeps ContextOS dependency-free for freelancers.
    """
    policy: dict[str, Any] = {}
    current_key: str | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            if ":" not in stripped:
                raise ValueError(f"Invalid policy line {line_number}: missing ':'")
            key, raw_value = stripped.split(":", 1)
            current_key = key
            if raw_value.strip() == "":
                policy[key] = {}
            else:
                policy[key] = parse_scalar(raw_value)
            continue

        if indent != 2 or current_key is None:
            raise ValueError(f"Invalid policy line {line_number}: unsupported indentation")

        if stripped.startswith("- "):
            if not isinstance(policy.get(current_key), list):
                policy[current_key] = []
            policy[current_key].append(parse_scalar(stripped[2:]))
            continue

        if ":" not in stripped:
            raise ValueError(f"Invalid policy line {line_number}: missing ':'")
        if not isinstance(policy.get(current_key), dict):
            policy[current_key] = {}
        key, raw_value = stripped.split(":", 1)
        policy[current_key][key] = parse_scalar(raw_value)

    return policy


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def project_identity_from_policy(policy_path: Path) -> str:
    normalized = policy_path
    if normalized.name == "policy.yaml" and normalized.parent.name == ".contextos":
        target_root = normalized.parent.parent
        if str(target_root) not in {"", "."}:
            return target_root.name
    return Path.cwd().name


def porcelain_changes() -> tuple[list[dict[str, str]], str]:
    raw = run_git(["status", "--porcelain"], check=True)
    changes: list[dict[str, str]] = []
    for line in raw.splitlines():
        if not line:
            continue
        code = line[:2]
        path_text = line[3:]
        paths = [path_text]
        if " -> " in path_text:
            old, new = path_text.split(" -> ", 1)
            paths = [old, new]
        for path in paths:
            changes.append({"code": code, "path": path})
    return changes, raw


def upstream_counts() -> dict[str, int | None]:
    upstream = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
    if not upstream:
        return {"behind": None, "ahead": None}
    counts = run_git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], check=False)
    if not counts:
        return {"behind": None, "ahead": None}
    left, right = counts.split()
    return {"behind": int(left), "ahead": int(right)}


def collect_git_state(policy_path: Path) -> dict[str, Any]:
    changes, raw_status = porcelain_changes()
    return {
        "repo_identity": project_identity_from_policy(policy_path),
        "remote": run_git(["config", "--get", "remote.origin.url"]),
        "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": run_git(["rev-parse", "HEAD"]),
        "dirty": bool(raw_status),
        "changes": changes,
        "changed_files": sorted({item["path"] for item in changes}),
        "raw_status": raw_status,
        "upstream": upstream_counts(),
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


def as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def mismatch(field: str, expected: Any, actual: Any, severity: str, reason: str) -> dict[str, Any]:
    return {
        "field": field,
        "expected": expected,
        "actual": actual,
        "severity": severity,
        "reason": reason,
    }


def expected_branch_value(expected: dict[str, Any]) -> tuple[str, Any]:
    if expected.get("branch") not in (None, ""):
        return "branch", expected.get("branch")
    return "protected_branch", expected.get("protected_branch")


def path_matches(path: str, pattern: str) -> bool:
    normalized = path.strip("/")
    pattern = pattern.strip()
    if not pattern:
        return False
    clean_pattern = pattern.strip("/")
    if clean_pattern.endswith("/"):
        return normalized.startswith(clean_pattern.strip("/") + "/")
    return fnmatch.fnmatch(normalized, clean_pattern) or fnmatch.fnmatch("/" + normalized, pattern)


def matching_paths(paths: list[str], patterns: list[str]) -> list[str]:
    return sorted({path for path in paths for pattern in patterns if path_matches(path, pattern)})


def in_expected_scope(path: str, expected_files: list[str], expected_dirs: list[str]) -> bool:
    if any(path_matches(path, pattern) for pattern in expected_files):
        return True
    normalized = path.strip("/")
    for directory in expected_dirs:
        clean = directory.strip("/")
        if any(char in clean for char in "*?["):
            if path_matches(path, clean):
                return True
        elif normalized == clean or normalized.startswith(clean.rstrip("/") + "/"):
            return True
    return False


def changed_file_signature(git_state: dict[str, Any]) -> str:
    payload = {
        "commit": git_state["commit"],
        "raw_status": git_state["raw_status"],
        "changed_files": git_state["changed_files"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def action_severity(action_name: str, default: str) -> str:
    action_name = str(action_name or default).lower()
    if action_name == "block":
        return STATUS_BLOCKED
    if action_name == "warn":
        return SEVERITY_WARN
    return default


def session_findings(
    policy: dict[str, Any],
    session: dict[str, Any],
    git_state: dict[str, Any],
) -> list[dict[str, Any]]:
    expected = policy.get("expected") if isinstance(policy.get("expected"), dict) else {}
    findings: list[dict[str, Any]] = []

    session_repo = session.get("current_repo")
    expected_repo = expected.get("repo_identity") or git_state["repo_identity"]
    if session_repo and expected_repo and str(session_repo) != str(expected_repo):
        findings.append(
            mismatch(
                "session.current_repo",
                expected_repo,
                session_repo,
                STATUS_DIVERGED,
                f"The model was thinking about {session_repo}",
            )
        )

    session_branch = session.get("current_branch")
    if session_branch and str(session_branch) != str(git_state["branch"]):
        findings.append(
            mismatch(
                "session.current_branch",
                git_state["branch"],
                session_branch,
                STATUS_DIVERGED,
                "AI session branch assumption differs from Git branch",
            )
        )

    return findings


def policy_findings(policy: dict[str, Any], git_state: dict[str, Any]) -> list[dict[str, Any]]:
    expected = policy.get("expected") or {}
    if not isinstance(expected, dict):
        return [mismatch("policy.expected", "mapping", type(expected).__name__, STATUS_BLOCKED, "policy is malformed")]

    findings: list[dict[str, Any]] = []
    expected_identity = expected.get("repo_identity")
    if expected_identity not in (None, "") and str(git_state["repo_identity"]) != str(expected_identity):
        findings.append(mismatch("repo_identity", expected_identity, git_state["repo_identity"], STATUS_DIVERGED, "target identity mismatch"))

    expected_remote = expected.get("remote")
    if expected_remote not in (None, "") and str(git_state["remote"]) != str(expected_remote):
        findings.append(mismatch("remote", expected_remote, git_state["remote"], STATUS_DIVERGED, "Git remote mismatch"))

    branch_field, branch_value = expected_branch_value(expected)
    if branch_value not in (None, "") and str(git_state["branch"]) != str(branch_value):
        findings.append(mismatch(branch_field, branch_value, git_state["branch"], STATUS_DIVERGED, "Git branch mismatch"))

    expected_commit = expected.get("commit")
    if expected_commit not in (None, "") and str(git_state["commit"]) != str(expected_commit):
        findings.append(mismatch("commit", expected_commit, git_state["commit"], STATUS_BLOCKED, "commit pin violation"))

    return findings


def freshness_and_scope_findings(
    policy: dict[str, Any],
    state: dict[str, Any],
    session: dict[str, Any],
    git_state: dict[str, Any],
    action: str,
    current_time: datetime,
) -> list[dict[str, Any]]:
    freshness = policy.get("freshness") if isinstance(policy.get("freshness"), dict) else {}
    enforcement = policy.get("enforcement") if isinstance(policy.get("enforcement"), dict) else {}
    changed_files = git_state["changed_files"]
    findings: list[dict[str, Any]] = []

    max_age_seconds = as_int(freshness.get("max_age_seconds"), 3600)
    aging_seconds = as_int(freshness.get("aging_seconds"), max(1, max_age_seconds // 2))
    last_verification = parse_time(session.get("last_verification_time") or state.get("last_verification_timestamp"))
    if max_age_seconds > 0:
        if last_verification is None:
            findings.append(mismatch("context_freshness", f"<= {max_age_seconds}s", "never verified", STATUS_STALE, "AI context has not been verified"))
        else:
            age_seconds = int((current_time - last_verification).total_seconds())
            if age_seconds > max_age_seconds:
                findings.append(mismatch("context_freshness", f"<= {max_age_seconds}s", f"{age_seconds}s", STATUS_STALE, "AI context freshness expired"))
            elif age_seconds > aging_seconds:
                findings.append(mismatch("context_freshness", f"<= {aging_seconds}s", f"{age_seconds}s", SEVERITY_WARN, "AI context is aging"))

    if git_state["dirty"]:
        findings.append(mismatch("working_tree", "clean or reviewed", "dirty", SEVERITY_WARN, "unstaged or staged changes are present"))

    upstream = git_state.get("upstream", {})
    behind = upstream.get("behind")
    if isinstance(behind, int) and behind > 0:
        findings.append(mismatch("remote_tracking", "0 commits behind", f"{behind} commits behind", STATUS_STALE, "branch is behind upstream"))

    expected_files = as_list(session.get("expected_files"))
    expected_dirs = as_list(session.get("expected_directories"))
    if changed_files and (expected_files or expected_dirs):
        outside_scope = [path for path in changed_files if not in_expected_scope(path, expected_files, expected_dirs)]
        if outside_scope:
            severity = action_severity(enforcement.get("scope_violation_action"), STATUS_BLOCKED)
            findings.append(
                mismatch(
                    "task_scope",
                    {"files": expected_files, "directories": expected_dirs},
                    outside_scope,
                    severity,
                    "modified files outside declared AI task scope",
                )
            )

    protected_paths = as_list(policy.get("protected_paths"))
    protected_touched = matching_paths(changed_files, protected_paths)
    if protected_touched:
        signature = changed_file_signature(git_state)
        verified_signature = session.get("last_verified_change_signature")
        severity = STATUS_BLOCKED if action in PROTECTED_ACTIONS and signature != verified_signature else STATUS_STALE
        findings.append(
            mismatch(
                "protected_paths",
                "explicit re-verification before commit/push",
                protected_touched,
                severity,
                "high consequence file touched",
            )
        )

    dependency_patterns = as_list(policy.get("dependency_config_paths")) or DEPENDENCY_CONFIG_DEFAULTS
    dependency_touched = matching_paths(changed_files, dependency_patterns)
    if dependency_touched:
        severity = action_severity(enforcement.get("dependency_config_action"), STATUS_STALE)
        findings.append(
            mismatch(
                "dependency_config_mutation",
                "reviewed dependency/config boundary",
                dependency_touched,
                severity,
                "dependency or config file changed",
            )
        )

    return findings


def context_score(findings: list[dict[str, Any]]) -> str:
    severities = {item["severity"] for item in findings}
    if STATUS_DIVERGED in severities:
        return CONTEXT_DIVERGED
    if STATUS_BLOCKED in severities or STATUS_STALE in severities:
        return CONTEXT_STALE
    if SEVERITY_WARN in severities:
        return CONTEXT_AGING
    return CONTEXT_FRESH


def final_status_from_findings(policy: dict[str, Any], findings: list[dict[str, Any]], action: str) -> tuple[str, str]:
    enforcement = policy.get("enforcement") if isinstance(policy.get("enforcement"), dict) else {}
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
        require_verification = as_bool(enforcement.get(f"require_verification_before_{action}"), True)
        block_on_divergence = as_bool(enforcement.get(f"block_{action}_on_divergence"), True)
        block_on_stale = as_bool(enforcement.get(f"block_{action}_on_stale"), False)
        if require_verification:
            if detected_status == STATUS_DIVERGED and block_on_divergence:
                final_status = STATUS_BLOCKED
            elif detected_status == STATUS_STALE and block_on_stale:
                final_status = STATUS_BLOCKED
    return final_status, detected_status


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_state(path: Path, action: str, status: str, score: str, git_state: dict[str, Any], timestamp: datetime) -> None:
    state = {
        "last_verification_timestamp": timestamp.isoformat(),
        "last_verified_repo_identity": git_state["repo_identity"],
        "last_verified_branch": git_state["branch"],
        "last_verified_repo": git_state["remote"],
        "last_verified_action": action,
        "last_verified_commit": git_state["commit"],
        "last_context_score": score,
        "last_status": status,
    }
    ensure_parent(path)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_session_context(
    path: Path,
    session: dict[str, Any],
    policy: dict[str, Any],
    action: str,
    score: str,
    git_state: dict[str, Any],
    findings: list[dict[str, Any]],
    timestamp: datetime,
) -> None:
    expected = policy.get("expected") if isinstance(policy.get("expected"), dict) else {}
    updated = dict(session)
    updated.setdefault("current_repo", expected.get("repo_identity") or git_state["repo_identity"])
    updated.setdefault("current_branch", git_state["branch"])
    updated.setdefault("active_task", "Manual ContextOS verification")
    updated.setdefault("expected_files", [])
    updated.setdefault("expected_directories", [])
    updated.setdefault("expected_technologies", [])
    updated["timestamp"] = updated.get("timestamp") or timestamp.isoformat()
    updated["last_verification_time"] = timestamp.isoformat()
    updated["last_verified_action"] = action
    updated["last_verified_change_signature"] = changed_file_signature(git_state)
    updated["last_context_score"] = score
    updated["unresolved_warnings"] = [item for item in findings if item["severity"] == SEVERITY_WARN]
    updated["stale_assumptions"] = [item for item in findings if item["severity"] in {STATUS_STALE, STATUS_DIVERGED}]
    ensure_parent(path)
    path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_audit_event(
    audit_log_path: Path,
    *,
    status: str,
    detected_status: str,
    context_score_value: str,
    mode: str,
    action: str,
    policy_path: Path,
    state_path: Path,
    session_path: Path,
    git_state: dict[str, Any] | None,
    expected: dict[str, Any],
    session: dict[str, Any],
    findings: list[dict[str, Any]],
    error: str | None = None,
    timestamp: datetime,
) -> None:
    event = {
        "timestamp": timestamp.isoformat(),
        "tool": "contextos",
        "command": "verify",
        "action": action,
        "mode": mode,
        "status": status,
        "detected_status": detected_status,
        "context_freshness": context_score_value,
        "policy_path": str(policy_path),
        "state_path": str(state_path),
        "session_path": str(session_path),
        "git": git_state,
        "expected": expected,
        "session": session,
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
    context_score_value: str,
    mode: str,
    action: str,
    git_state: dict[str, Any] | None,
    session: dict[str, Any],
    findings: list[dict[str, Any]],
    error: str | None,
) -> None:
    use_color = supports_color()
    print(colorize("ContextOS AI context verification", Colors.BOLD, use_color))
    print(f"Mode: {mode}")
    print(f"Action: {action}")
    print(f"Status: {colorize(status, status_color(status), use_color)}")
    print(f"Context: {colorize(context_score_value, context_color(context_score_value), use_color)}")
    if detected_status != status:
        print(f"Detected: {detected_status}")

    if session:
        print("AI session:")
        print(f"  task:   {session.get('active_task', 'unknown')}")
        print(f"  repo:   {session.get('current_repo', 'unknown')}")
        print(f"  branch: {session.get('current_branch', 'unknown')}")

    if git_state:
        upstream = git_state.get("upstream", {})
        behind = upstream.get("behind")
        ahead = upstream.get("ahead")
        tracking = "unknown" if behind is None else f"behind {behind}, ahead {ahead}"
        print("Git:")
        print(f"  identity: {git_state['repo_identity']}")
        print(f"  repo:     {git_state['remote']}")
        print(f"  branch:   {git_state['branch']}")
        print(f"  commit:   {git_state['commit']}")
        print(f"  tree:     {human_bool(bool(git_state['dirty']))}")
        print(f"  upstream: {tracking}")

    if findings:
        print("Reasons:")
        for item in findings:
            print(
                "  - {reason}: {field} expected {expected!r}, found {actual!r} [{severity}]".format(
                    reason=item["reason"],
                    field=item["field"],
                    expected=item["expected"],
                    actual=item["actual"],
                    severity=item["severity"],
                )
            )
    else:
        print("Reasons: none")

    if error:
        print(f"Error: {error}")

    print("Suggested remediation:")
    print("  1. Run git status")
    print("  2. Verify current branch")
    print("  3. Re-run verification")
    print("  4. Update task scope or resync Cursor context")

    if mode == "advisory" and status == STATUS_BLOCKED:
        print(colorize("Advisory mode: this would block in enforce mode, but the Git operation may continue.", Colors.YELLOW, use_color))
    elif status == STATUS_BLOCKED:
        print(colorize(f"ContextOS blocked {action}: AI context legitimacy check failed.", Colors.RED, use_color))
    elif context_score_value == CONTEXT_DIVERGED:
        print(colorize("ContextOS detected AI/Git context divergence.", Colors.YELLOW, use_color))
    elif context_score_value == CONTEXT_STALE:
        print(colorize("ContextOS detected stale AI execution context.", Colors.YELLOW, use_color))
    elif context_score_value == CONTEXT_AGING:
        print(colorize("ContextOS warnings present; review before consequential execution.", Colors.YELLOW, use_color))
    else:
        print(colorize("ContextOS verification passed.", Colors.GREEN, use_color))


def verify(policy_path: Path, audit_log_path: Path, state_path: Path, session_path: Path, action: str, mode: str) -> int:
    git_state: dict[str, Any] | None = None
    policy: dict[str, Any] = {}
    session: dict[str, Any] = {}
    status = STATUS_BLOCKED
    detected_status = STATUS_BLOCKED
    score = CONTEXT_DIVERGED
    findings: list[dict[str, Any]] = []
    error: str | None = None
    timestamp = now_utc()

    try:
        policy = load_policy(policy_path)
        state = load_json(state_path)
        session = load_json(session_path)
        git_state = collect_git_state(policy_path)
        findings.extend(policy_findings(policy, git_state))
        findings.extend(session_findings(policy, session, git_state))
        findings.extend(freshness_and_scope_findings(policy, state, session, git_state, action, timestamp))
        score = context_score(findings)
        status, detected_status = final_status_from_findings(policy, findings, action)
        write_state(state_path, action, status, score, git_state, timestamp)
        write_session_context(session_path, session, policy, action, score, git_state, findings, timestamp)
        session = load_json(session_path)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        error = str(exc)
        status = STATUS_BLOCKED
        detected_status = STATUS_BLOCKED
        score = CONTEXT_DIVERGED
        findings = [mismatch("verification_error", "successful verification", error, STATUS_BLOCKED, "verification failed")]

    expected = policy.get("expected") if isinstance(policy.get("expected"), dict) else {}
    write_audit_event(
        audit_log_path,
        status=status,
        detected_status=detected_status,
        context_score_value=score,
        mode=mode,
        action=action,
        policy_path=policy_path,
        state_path=state_path,
        session_path=session_path,
        git_state=git_state,
        expected=expected,
        session=session,
        findings=findings,
        error=error,
        timestamp=timestamp,
    )
    print_report(
        status=status,
        detected_status=detected_status,
        context_score_value=score,
        mode=mode,
        action=action,
        git_state=git_state,
        session=session,
        findings=findings,
        error=error,
    )
    return 1 if mode == "enforce" and status == STATUS_BLOCKED else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contextos", description="ContextOS CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="verify Git state against AI execution context")
    verify_parser.add_argument("--action", choices=["manual", "commit", "push"], default="manual")
    verify_parser.add_argument("--mode", choices=["advisory", "enforce"], default="enforce")
    verify_parser.add_argument("--policy", default=DEFAULT_POLICY_PATH, type=Path)
    verify_parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG_PATH, type=Path)
    verify_parser.add_argument("--state", default=DEFAULT_STATE_PATH, type=Path)
    verify_parser.add_argument("--session", default=DEFAULT_SESSION_PATH, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        return verify(args.policy, args.audit_log, args.state, args.session, args.action, args.mode)
    parser.error(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
