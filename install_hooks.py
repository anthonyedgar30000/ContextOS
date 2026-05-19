#!/usr/bin/env python3
"""Install ContextOS Git workflow hooks."""

from __future__ import annotations

import argparse
import shlex
import shutil
import stat
import subprocess
from pathlib import Path


HOOKS = {
    "pre-commit": "commit",
    "pre-push": "push",
}
MARKER = "# ContextOS managed hook"


HOOK_TEMPLATE = """#!/bin/sh
{marker}
set -u

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$repo_root" ]; then
  echo "ContextOS: unable to locate Git repository root." >&2
  exit 1
fi

cd "$repo_root" || exit 1

echo "ContextOS: verifying before {action}..."
python3 verifier.py verify --action {action} --policy {policy} --state {state} --audit-log {audit_log}
status=$?

if [ "$status" -ne 0 ]; then
  echo "" >&2
  echo "ContextOS blocked {action}." >&2
  echo "Resolve the findings above, then retry the Git operation." >&2
  echo "Suggested commands:" >&2
  echo "  git status" >&2
  echo "  git branch --show-current" >&2
  echo "  python3 verifier.py verify --action manual --policy {policy} --state {state} --audit-log {audit_log}" >&2
  exit "$status"
fi

exit 0
"""


def run_git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def install_hook(hooks_dir: Path, name: str, action: str, policy: Path, state: Path, audit_log: Path) -> None:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / name
    hook_body = HOOK_TEMPLATE.format(
        marker=MARKER,
        action=action,
        policy=shlex.quote(str(policy)),
        state=shlex.quote(str(state)),
        audit_log=shlex.quote(str(audit_log)),
    )

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if MARKER not in existing:
            backup_path = hook_path.with_name(f"{name}.contextos-backup")
            shutil.copy2(hook_path, backup_path)
            print(f"Backed up existing {name} hook to {backup_path}")

    hook_path.write_text(hook_body, encoding="utf-8")
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed .git/hooks/{name} -> ContextOS {action} gate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install ContextOS Git workflow hooks")
    parser.add_argument("--policy", default=".contextos/policy.yaml", type=Path, help="policy path hooks should verify")
    parser.add_argument("--state", default=".contextos/state_manifest.json", type=Path, help="state manifest path hooks should update")
    parser.add_argument("--audit-log", default="audit_log.jsonl", type=Path, help="audit log path hooks should append to")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(run_git(["rev-parse", "--show-toplevel"]))
    git_dir = Path(run_git(["rev-parse", "--git-dir"]))
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    hooks_dir = git_dir / "hooks"

    for hook_name, action in HOOKS.items():
        install_hook(hooks_dir, hook_name, action, args.policy, args.state, args.audit_log)

    print("ContextOS hooks installed.")
    print(f"Policy: {args.policy}")
    print("Commits and pushes now run local ContextOS verification first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
