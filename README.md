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

## Governed target application: JillyPickles

This repository also includes `JillyPickles/`, a tiny target application used to
demonstrate why ContextOS sits at the Git boundary.

JillyPickles has one visible health contract:

- `environment` must be `production`.
- `feature_flags.pickle_ordering_enabled` must be `true`.
- `routes.order` must be `/pickles/order`.

A stale assistant context can confuse the current product with an old
"cucumber cart" experiment and produce this bad change:

```json
{
  "environment": "legacy-demo",
  "feature_flags": {"pickle_ordering_enabled": false},
  "routes": {"order": "/old-cucumber-cart"}
}
```

When that config reaches the app, `python3 JillyPickles/app.py` prints `BROKEN`
and exits non-zero.

### JillyPickles ContextOS files

The governed target keeps its own local context files:

- `JillyPickles/.contextos/policy.yaml`
- `JillyPickles/.contextos/state_manifest.json`
- `JillyPickles/.contextos/handover.md`
- `JillyPickles/audit_log.jsonl` is created when target verification runs.

The policy includes:

- expected repo identity: `JillyPickles`
- expected Git remote
- protected branch: `main`
- required verification before commit and push
- freshness timeout: `900` seconds

The same root `verifier.py` and `install_hooks.py` are reused. The JillyPickles
hooks are installed by pointing the installer at target-specific paths:

```bash
python3 install_hooks.py \
  --policy JillyPickles/.contextos/policy.yaml \
  --state JillyPickles/.contextos/state_manifest.json \
  --audit-log JillyPickles/audit_log.jsonl
```

The generated hooks still call the shared verifier:

```bash
python3 verifier.py verify --action commit --policy JillyPickles/.contextos/policy.yaml --state JillyPickles/.contextos/state_manifest.json --audit-log JillyPickles/audit_log.jsonl
python3 verifier.py verify --action push --policy JillyPickles/.contextos/policy.yaml --state JillyPickles/.contextos/state_manifest.json --audit-log JillyPickles/audit_log.jsonl
```

### Execution boundary

Cursor may generate changes, but ContextOS verifies contextual legitimacy before
Git becomes authoritative and before GitOps or deployment systems reconcile
operational state.

The boundary is intentionally local:

1. Cursor or a developer edits files.
2. Git tries to commit or push.
3. Git hooks call ContextOS.
4. ContextOS compares Git state and target context policy.
5. `BLOCKED` exits non-zero, so Git refuses the operation.
6. The broken app state never becomes authoritative Git state.

### Demo Flow A: governance disabled

Run:

```bash
JillyPickles/run_demo_without_contextos.sh
```

Expected output shape:

```text
=== Flow A: governance disabled ===
1) Start from a healthy JillyPickles app.
HEALTHY: customers can order pickles.

2) Stale context applies an obsolete cucumber-cart config.

3) The app is now visibly broken.
BROKEN:
  - environment must be production for the storefront demo
  - pickle ordering feature flag is disabled
  - order route must be /pickles/order

4) With governance disabled, no verifier runs before Git.
   Simulated git commit: succeeds
   Simulated git push:   succeeds
   Result: broken JillyPickles config can become authoritative state.
```

### Demo Flow B: ContextOS enabled

Run:

```bash
JillyPickles/run_demo_with_contextos.sh
```

Expected output shape:

```text
=== Flow B: ContextOS enabled ===
1) Install hooks pointed at the JillyPickles governance policy.
Installed .git/hooks/pre-commit -> ContextOS commit gate
Installed .git/hooks/pre-push -> ContextOS push gate

4) Pre-commit verification sees stale/diverged context and blocks.
ContextOS verification
Action: commit
Status: BLOCKED
Mismatches:
  - protected_branch: expected 'main', found '<current-branch>' (DIVERGED)
  - context_freshness: expected '<= 900s', found '<age>s' (STALE)
Remediation:
  - Run git status
  - Verify current branch
  - Resync Cursor context
ContextOS blocked commit: contextual legitimacy check failed.
Simulated commit gate exit code: 1

5) Pre-push verification blocks the same stale context before GitOps/deploy.
Status: BLOCKED
Simulated push gate exit code: 1

6) Remediation restores the healthy config; app remains healthy.
HEALTHY: customers can order pickles.
```

The demo uses temporary state and audit files for the simulated blocked checks so
it can be re-run without leaving `JillyPickles/config.json` broken.

### Target audit event example

```json
{"action":"commit","command":"verify","detected_status":"DIVERGED","error":null,"expected":{"commit":"","protected_branch":"main","remote":"https://github.com/anthonyedgar30000/ContextOS","repo_identity":"JillyPickles"},"git":{"branch":"feature/demo","commit":"abc123","dirty":true,"remote":"https://github.com/anthonyedgar30000/ContextOS","repo_identity":"JillyPickles"},"mismatches":[{"actual":"feature/demo","expected":"main","field":"protected_branch","severity":"DIVERGED"}],"policy_path":"JillyPickles/.contextos/policy.yaml","state_path":"JillyPickles/.contextos/state_manifest.json","status":"BLOCKED","timestamp":"2026-05-19T00:00:00+00:00","tool":"contextos"}
```

## Workspace State vs Authoritative Git State

AI-generated workspace state is not authoritative by itself. Files visible in a
Cursor session, terminal buffer, or local working tree become authoritative only
when they are synchronized into canonical Git state.

ContextOS treats these as separate boundaries:

- **Cursor memory/session state** - prompts, summaries, proposed changes, and UI
  visibility. This can describe files that are not yet present in a clone of the
  repository.
- **Local filesystem state** - files written to the current workspace. These can
  still be unstaged, uncommitted, or available only inside an ephemeral agent
  environment.
- **Local Git history** - committed objects on a branch in the local repository.
  These are durable locally but are not visible to other clones until pushed.
- **Remote GitHub state** - pushed branches, commits, and pull requests. This is
  the canonical collaboration boundary for other developers, CI, GitOps, and
  deployment systems.
- **Merged default branch state** - changes merged into `main`. A fresh clone or
  `git pull` on `main` will not show feature-branch files until the PR is merged
  or the feature branch is explicitly checked out.

For example, the ContextOS/JillyPickles demo files live on the feature branch
`cursor/contextos-verify-0186` until PR merge. A local clone that only checks
`main` is correctly expected to show the initial repository contents.

To inspect the authoritative feature branch directly:

```bash
git fetch origin cursor/contextos-verify-0186
git checkout cursor/contextos-verify-0186
# or inspect without checkout:
git ls-tree -r origin/cursor/contextos-verify-0186 --name-only
```

ContextOS exists to govern this transition boundary: Cursor may generate changes
in a workspace, but ContextOS verifies contextual legitimacy before those changes
are committed, pushed, and allowed to influence authoritative operational state.

