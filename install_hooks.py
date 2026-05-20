#!/usr/bin/env python3
"""Install deterministic local Git hooks for ContextOS."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class HookInstallError(Exception):
    """Raised for clear, user-facing hook installation failures."""


HOOK_TEMPLATE = """#!/bin/sh
set -u

repo_root=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$repo_root" ]; then
  echo "ContextOS pre-commit: unable to resolve repository root" >&2
  exit 1
fi

verify_cli="$repo_root/verify_cli.py"
if [ ! -f "$verify_cli" ]; then
  echo "ContextOS pre-commit: verify_cli.py not found" >&2
  echo "Suggested remediation:" >&2
  echo "1. run this hook from a ContextOS repository" >&2
  echo "2. reinstall hooks with: python3 install_hooks.py --mode {mode}" >&2
  exit 1
fi

echo "ContextOS pre-commit: running verify_cli.py"
python3 "$verify_cli" \\
  --session "$repo_root/session.json" \\
  --policy "$repo_root/policy.yaml" \\
  --repo "$repo_root" \\
  --protected-mode {mode}
exit_code=$?

if [ "$exit_code" -ne 0 ]; then
  echo "ContextOS pre-commit: verification failed; commit blocked" >&2
  echo "Suggested remediation:" >&2
  echo "1. review the verification output above" >&2
  echo "2. regenerate the context packet if context is stale" >&2
  echo "3. run: ./contextos ingest context_packet.yaml" >&2
  echo "4. adjust staged changes or policy before retrying" >&2
  exit "$exit_code"
fi

echo "ContextOS pre-commit: verification passed"
"""


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
        raise HookInstallError(
            f"{' '.join(command)} failed with exit code {completed.returncode}: "
            f"{completed.stderr.strip() or 'no error output'}"
        )
    return completed.stdout.strip()


def repo_root(repo: Path) -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"], repo))


def render_hook(mode: str) -> str:
    if mode not in {"advisory", "enforce"}:
        raise HookInstallError("mode must be either advisory or enforce")
    return HOOK_TEMPLATE.format(mode=mode)


def install_hook(repo: Path, mode: str) -> Path:
    root = repo_root(repo)
    hook_path = root / ".git" / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(render_hook(mode), encoding="utf-8")
    os.chmod(hook_path, 0o755)
    return hook_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install the ContextOS deterministic pre-commit hook."
    )
    parser.add_argument(
        "--repo",
        default=Path.cwd(),
        type=Path,
        help="path to the git repository (default: current working directory)",
    )
    parser.add_argument(
        "--mode",
        choices=("advisory", "enforce"),
        default="enforce",
        help="protected path mode passed to verify_cli.py (default: enforce)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        hook_path = install_hook(args.repo, args.mode)
    except HookInstallError as error:
        print(f"install_hooks: ERROR: {error}", file=sys.stderr)
        return 2

    print("ContextOS hook installer")
    print(f"repo: {repo_root(args.repo)}")
    print(f"hook: {hook_path}")
    print(f"mode: {args.mode}")
    print("status: installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
