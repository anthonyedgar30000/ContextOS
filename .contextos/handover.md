# ContextOS Handover

This file is a lightweight handover note for AI-assisted development sessions.
It captures the local context that ContextOS expects before authoritative Git
state changes occur.

## Current policy anchor

- Repository: `https://github.com/anthonyedgar30000/ContextOS`
- Branch: `cursor/contextos-verify-0186`
- Commit pinning: disabled for normal prototype development

## Operator checklist

1. Run `python3 verifier.py verify --action manual` after changing context.
2. Run `git status` before commit or push.
3. Confirm the branch matches `.contextos/policy.yaml`.
4. Resync Cursor context if the verifier reports `STALE` or `DIVERGED`.

## Principle

Cursor may suggest changes, but ContextOS verifies contextual legitimacy before
authoritative Git state changes occur.
