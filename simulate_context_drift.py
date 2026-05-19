#!/usr/bin/env python3
"""Simulate ContextOS detecting repo/branch drift.

The script creates a temporary policy that intentionally expects the wrong
branch. It then runs the same verifier command shape used by hooks so the demo
shows a protected action being blocked without modifying real Git hooks.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    remote = git(["config", "--get", "remote.origin.url"])
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    wrong_branch = f"contextos-drift-demo-not-{branch}"

    with tempfile.TemporaryDirectory(prefix="contextos-drift-") as tmp:
        tmp_path = Path(tmp)
        policy_path = tmp_path / "policy.yaml"
        state_path = tmp_path / "state_manifest.json"
        audit_path = tmp_path / "audit_log.jsonl"
        policy_path.write_text(
            "expected:\n"
            f"  remote: \"{remote}\"\n"
            f"  branch: \"{wrong_branch}\"\n"
            "  commit: \"\"\n"
            "freshness:\n"
            "  max_age_seconds: 3600\n"
            "enforcement:\n"
            "  block_commit_on_divergence: true\n"
            "  block_push_on_divergence: true\n",
            encoding="utf-8",
        )

        print("ContextOS drift simulation")
        print(f"Actual branch:   {branch}")
        print(f"Policy branch:   {wrong_branch}")
        print("\nSimulating protected commit verification...")
        commit_result = subprocess.run(
            [
                "python3",
                "verifier.py",
                "verify",
                "--action",
                "commit",
                "--policy",
                str(policy_path),
                "--state",
                str(state_path),
                "--audit-log",
                str(audit_path),
            ],
            text=True,
        )
        print(f"Simulated commit gate exit code: {commit_result.returncode}")

        print("\nSimulating protected push verification...")
        push_result = subprocess.run(
            [
                "python3",
                "verifier.py",
                "verify",
                "--action",
                "push",
                "--policy",
                str(policy_path),
                "--state",
                str(state_path),
                "--audit-log",
                str(audit_path),
            ],
            text=True,
        )
        print(f"Simulated push gate exit code: {push_result.returncode}")
        print(f"\nAudit log written to: {audit_path}")
        return 0 if commit_result.returncode and push_result.returncode else 1


if __name__ == "__main__":
    raise SystemExit(main())
