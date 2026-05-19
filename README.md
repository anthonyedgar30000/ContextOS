# ContextOS

ContextOS is a lightweight governance layer for AI-assisted development
workflows. The MVP is local-first: it reads files from the repository, asks Git
for the current state, writes JSON audit events, and blocks protected Git
actions when context is not legitimate.

Architecture principle:

> Cursor may suggest changes, but ContextOS verifies contextual legitimacy before
> authoritative Git state changes occur.

## Architecture

ContextOS uses a small set of local files:

- `verifier.py` - CLI entry point for `contextos verify` behavior.
- `install_hooks.py` - installs Git hook gates into `.git/hooks/`.
- `.contextos/policy.yaml` - expected repository, branch, freshness, and
  enforcement policy.
- `.contextos/state_manifest.json` - last successful verification context.
- `.contextos/handover.md` - human/AI handover notes for the active context.
- `audit_log.jsonl` - append-only JSON Lines audit log.
- `simulate_context_drift.py` - demo script for branch/repo drift detection.

There are no services, databases, or frameworks. Git state is collected with
`subprocess` calls to `git`.

## Install hooks

From the repository root:

```bash
python3 install_hooks.py
```

This installs:

- `.git/hooks/pre-commit`
- `.git/hooks/pre-push`

The hooks run these commands:

```bash
python3 verifier.py verify --action commit
python3 verifier.py verify --action push
```

If the verifier exits non-zero, Git blocks the commit or push and prints a short
remediation checklist.

## Manual verification

Run:

```bash
python3 verifier.py verify --action manual
```

Optional paths:

```bash
python3 verifier.py verify   --action manual   --policy ./.contextos/policy.yaml   --state ./.contextos/state_manifest.json   --audit-log ./audit_log.jsonl
```

For shell ergonomics, you can add an alias:

```bash
alias contextos="python3 /path/to/ContextOS/verifier.py"
contextos verify --action manual
```

## Policy model

`.contextos/policy.yaml` intentionally uses a small YAML subset: simple
key/value pairs and one level of nested mappings.

```yaml
expected:
  remote: "https://github.com/example/contextos"
  branch: "main"
  commit: ""
freshness:
  max_age_seconds: 3600
enforcement:
  block_commit_on_divergence: true
  block_push_on_divergence: true
  block_commit_on_stale: false
  block_push_on_stale: false
  block_commit_when_dirty: false
  block_push_when_dirty: true
```

Empty expected values are ignored. Keeping `expected.commit` empty is practical
for active development; setting it pins verification to a specific commit.

## Status model

The verifier prints one status:

- `VALID` - repo and policy are aligned.
- `STALE` - repo is valid, but context freshness expired or was verified for a
  different local context.
- `DIVERGED` - repo or branch mismatch detected.
- `BLOCKED` - policy violation or protected action denied.

Only `BLOCKED` returns a non-zero exit code.

## Enforcement flow

1. A developer runs `git commit` or `git push`.
2. Git runs the installed ContextOS hook.
3. The hook calls `python3 verifier.py verify --action commit` or `push`.
4. The verifier reads `.contextos/policy.yaml` and `.contextos/state_manifest.json`.
5. The verifier collects Git remote, branch, commit hash, and dirty-tree state.
6. The verifier writes a structured event to `audit_log.jsonl` and updates the
   state manifest.
7. `BLOCKED` exits non-zero, so Git denies the protected action.

## Context freshness tracking

`.contextos/state_manifest.json` stores:

```json
{
  "last_status": "VALID",
  "last_verification_timestamp": "2026-05-19T00:00:00+00:00",
  "last_verified_action": "manual",
  "last_verified_branch": "main",
  "last_verified_commit": "abc123",
  "last_verified_repo": "https://github.com/example/contextos"
}
```

A context becomes `STALE` when the last verification timestamp is older than
`freshness.max_age_seconds`, or when the manifest was verified for a different
branch or repo.

## Example failure scenarios

### Branch drift

Policy expects `main`, but Git is on `feature/demo`.

- Manual verification reports `DIVERGED`.
- Commit/push verification reports `BLOCKED` when divergence blocking is enabled.
- Remediation: run `git status`, verify current branch, then resync Cursor
  context or update policy intentionally.

### Commit pin violation

Policy sets `expected.commit`, but the checkout is at a different commit.

- Verification reports `BLOCKED`.
- Remediation: check out the expected commit, or intentionally update the policy
  pin after reviewing context.

### Stale context

The state manifest is older than `freshness.max_age_seconds`.

- Verification reports `STALE`.
- If `block_commit_on_stale` or `block_push_on_stale` is enabled, protected
  actions are denied as `BLOCKED`.
- Remediation: resync Cursor context and run manual verification.

### Dirty push

The working tree has uncommitted changes and `block_push_when_dirty` is enabled.

- Push verification reports `BLOCKED`.
- Remediation: run `git status`, commit/stash/revert local changes, then retry.

## Audit log examples

Each verification appends one JSON event to `audit_log.jsonl`.

Successful verification:

```json
{"action":"manual","command":"verify","detected_status":"VALID","error":null,"expected":{"branch":"main","commit":"","remote":"https://github.com/example/contextos"},"git":{"branch":"main","commit":"abc123","dirty":false,"remote":"https://github.com/example/contextos"},"mismatches":[],"policy_path":".contextos/policy.yaml","state_path":".contextos/state_manifest.json","status":"VALID","timestamp":"2026-05-19T00:00:00+00:00","tool":"contextos"}
```

Blocked protected action:

```json
{"action":"commit","command":"verify","detected_status":"DIVERGED","error":null,"expected":{"branch":"main","commit":"","remote":"https://github.com/example/contextos"},"git":{"branch":"feature/demo","commit":"def456","dirty":true,"remote":"https://github.com/example/contextos"},"mismatches":[{"actual":"feature/demo","expected":"main","field":"branch","severity":"DIVERGED"}],"policy_path":".contextos/policy.yaml","state_path":".contextos/state_manifest.json","status":"BLOCKED","timestamp":"2026-05-19T00:00:00+00:00","tool":"contextos"}
```

## Demo: simulate context drift

Run:

```bash
python3 simulate_context_drift.py
```

The demo creates a temporary policy that intentionally expects the wrong branch,
runs commit and push verification against it, and shows ContextOS blocking both
protected actions. It writes demo audit output to a temporary directory and does
not install or modify real Git hooks.
