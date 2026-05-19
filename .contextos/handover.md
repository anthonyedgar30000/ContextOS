# ContextOS Handover

This file is a lightweight handover note for AI-assisted development sessions.
It captures the local context that ContextOS expects before authoritative Git
state changes occur.

## Current policy anchor

- Repository identity: `workspace`
- Branch: `cursor/contextos-verify-0186`
- Commit pinning: disabled for normal prototype development
- Active task: extend ContextOS into an AI-native safety layer for Cursor
  freelancers and solo developers

## AI handoff awareness

- Originating task: ContextOS AI context governance phase
- Originating branch: `cursor/contextos-verify-0186`
- Repo assumptions:
  - local-first only
  - no external services, databases, or enterprise workflow systems
  - Git tracks code state; ContextOS tracks AI execution context
  - AI-generated workspace state is not authoritative until committed and pushed
- Expected scope:
  - `verifier.py`
  - `install_hooks.py`
  - `README.md`
  - `.contextos/*`
  - `demo_freelancer_context_switch/*`
- Unresolved warnings: none at handoff
- Stale assumptions to re-check:
  - current branch before commit/push
  - remote feature branch tracking status
  - whether task scope still matches requested files

## Operator checklist

1. Run `python3 verifier.py verify --action manual --mode advisory` after changing context.
2. Run `git status` before commit or push.
3. Confirm changed files are inside `.contextos/session_context.json` scope.
4. Re-run verification if protected paths, dependency files, or configs changed.
5. Resync Cursor context if the verifier reports `STALE` or `DIVERGED`.

## Principle

Cursor may suggest changes, but ContextOS verifies contextual legitimacy before
authoritative Git state changes occur.
