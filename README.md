# ContextOS

ContextOS is a lightweight deterministic execution-boundary layer for
AI-assisted development workflows. It turns reviewed context into local files,
uses Git as the source of truth for current execution state, and blocks or
reports mutations that no longer match the declared boundary.

## Repository Status

This branch is the canonical ContextOS capstone implementation branch. It
supersedes the earlier verifier prototype direction in PR #2 and intentionally
does not include the media-overlay prototype direction from PR #1. The project
identity for this branch is:

> A lightweight deterministic execution-boundary layer for AI-assisted
> development workflows.

## Problem statement

AI-assisted coding sessions often begin with a reviewed task, a target branch,
and a set of files that are safe to change. The local repository can drift after
that review: a branch switch, a new commit, a stale working tree, or a staged
change outside the intended scope can make the original execution assumptions
invalid.

ContextOS addresses that gap by making the execution assumptions explicit and
checking them against local Git state before commit or push. The goal is not to
judge code quality or model behavior. The goal is to keep an AI-assisted
mutation inside a deterministic, locally verifiable boundary.

## Architecture overview

ContextOS has local command surfaces for ingestion, verification, issue
handoff, plan export, freshness checks, and approval-gated state-switch
requests:

- `contextos ingest <context_packet.yaml>` converts reviewed context into
  `.contextos/session_context.json`.
- `contextos verify` checks Git state, declared path scope, protected paths, and
  context freshness before allowing work to proceed.
- `contextos verify-freshness` classifies whether an execution plan still
  matches current repository state.
- `contextos create-issue` generates local GitHub Issue markdown from an issue
  packet.
- `contextos export-last-plan` exports the latest local Cursor execution result
  for ChatGPT review.
- `contextos request-switch` creates an approval-gated repo/branch switch
  request.
- `contextos explain-git` explains recommended Git commands.

```text
Reviewed context packet
        |
        v
+------------------+
| contextos ingest |
+------------------+
        |
        v
.contextos/session_context.json
        |
        v
+-----------------------------+        +----------------------+
| verify_cli.py               |<------>| local Git repository |
| - branch freshness          |        | - branch             |
| - HEAD hash freshness       |        | - HEAD hash          |
| - allowed path scope        |        | - working tree diff  |
| - protected staged paths    |        | - staged diff        |
+-----------------------------+        +----------------------+
        |
        v
terminal result + optional markdown audit report
```

## Core concepts

### Stale execution context

A stale execution context exists when the repository state no longer matches the
state recorded when context was ingested. Examples include:

- the local branch changed after ingestion
- the Git HEAD hash changed after ingestion
- the local branch is behind its configured remote-tracking branch

Verification classifies context freshness as:

- `FRESH`: branch and HEAD match the ingested context and the branch is not
  behind its configured upstream.
- `AGING`: branch and HEAD still match, but the local branch is behind its
  configured upstream.
- `STALE`: the branch or HEAD changed after ingestion.
- `DIVERGED`: the repository is in detached HEAD state.

When context is not fresh, verification prints the classification with explicit
reasons and deterministic remediation steps.

### AI-assisted mutation

An AI-assisted mutation is any local repository change made by, suggested by, or
continued from an AI-assisted development session. ContextOS treats it like any
other local Git mutation: it must fit the declared branch, freshness, path, and
protected-path constraints before it can proceed.

### Execution boundary

An execution boundary is the local contract that defines where a development
task may operate. In ContextOS, the boundary is made from:

- ingested session context
- current Git branch and HEAD hash
- allowed file paths
- protected file paths
- staged and unstaged Git diffs

### Git authoritative state

ContextOS treats local Git state as authoritative. It does not call external
services to decide whether a session is valid. It reads deterministic local Git
commands such as:

- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --porcelain=v1 -z`
- `git diff --name-only`
- `git diff --cached --name-only`

### Declared execution contracts

A declared execution contract is a small local file that says what the task is
allowed to do. ContextOS currently uses:

- `context_packet.yaml` for reviewed task context
- `.contextos/session_context.json` for ingested branch and HEAD provenance
- `policy.yaml` for allowed and protected paths
- `session.json` for verification-time branch expectations

### Path-scope enforcement

`allowed_paths` define the files or directories a task may change. Verification
compares changed files against this list and fails when a file is outside scope.
This keeps a task focused on its reviewed file boundary.

### Branch freshness validation

Branch freshness validation compares current Git state with
`.contextos/session_context.json`. Verification fails when the local branch or
HEAD no longer matches the ingested context, or when the branch is behind its
configured upstream.

### Protected paths

`protected_paths` define files or directories that require extra scrutiny. They
are checked against staged changes from `git diff --cached --name-only`.

Protected paths support two modes:

- advisory: print a warning without failing verification
- enforce: fail verification when staged protected paths are touched

### Audit and provenance reporting

When `--report` is provided, verification writes a markdown audit report with:

- timestamp
- repo and branch
- changed files
- allowed files
- violations
- context freshness results
- protected path violations
- Git status summary

The report is local-first provenance for what was checked and why verification
passed or failed.

## Design principles

- **Deterministic by default:** output is based on local files and Git commands.
- **Local-first:** no external APIs or services are required.
- **Git-centered:** the current branch, HEAD, working tree, and staged diff are
  the authoritative execution state.
- **Small contracts:** context and policy are stored in simple JSON/YAML files.
- **Fail clearly:** mismatches should produce direct terminal output with
  concrete remediation.
- **Composable:** verification can run manually, in demos, or from a pre-commit
  hook.
- **Narrow scope:** ContextOS bounds execution; it does not replace tests,
  reviews, or code ownership.

## Glossary

- **Allowed path:** A file or directory pattern where task changes are permitted.
- **Audit report:** A markdown file containing verification inputs, results, and
  violations.
- **Context packet:** Reviewed task context provided as `context_packet.yaml`.
- **Execution boundary:** The local set of branch, HEAD, path, and protection
  constraints for a task.
- **Freshness:** Whether current Git state still matches ingested context.
- **Git authoritative state:** The local Git branch, HEAD, status, and diffs used
  as verification inputs.
- **Protected path:** A staged file path that should warn or block when touched.
- **Session context:** The ingested `.contextos/session_context.json` file.
- **Stale execution context:** A session context that no longer matches local Git
  state.

## Limitations

- The YAML support is intentionally minimal and only covers the simple packet and
  policy shapes used by ContextOS.
- Branch freshness is based on local Git metadata. Remote freshness depends on
  the local repository having current remote-tracking refs.
- Protected path matching is path-pattern based; it does not inspect file
  contents.
- Verification does not decide whether a code change is correct. It only checks
  execution boundary constraints.
- The audit report records local verification results, not a signed attestation.

## Future work

- Share YAML parsing helpers between `contextos.py` and `verify_cli.py`.
- Add optional machine-readable verification output.
- Add richer policy modes for branch-specific or task-specific protected paths.
- Add examples for CI usage while keeping local verification as the primary
  workflow.
- Add report hashing or signing for teams that need stronger provenance.

## Demos

- `demos/jillypickles-stale-plan/` contains a reproducible stale
  execution-context demo using a local JillyPickles repository, including sample
  repo setup, context packets, failure/remediation notes, expected output, and a
  screenshots placeholder.

## Capstone documentation

- `docs/CAPSTONE.md` provides the final capstone-oriented architecture write-up,
  including the abstract, problem statement, design model, deterministic
  enforcement model, demo walkthrough, limitations, future work, and glossary.

## GitHub Issue bridge workflow

ContextOS supports structured, auditable coordination between reasoning systems
and authoritative Git workflows. The bridge is intentionally local-first:
ContextOS generates GitHub Issue markdown on disk and does not call the GitHub
API. It does not execute implementation work, create GitHub Issues, or post
comments automatically.

```text
ChatGPT
  |
  v
GitHub Issue markdown generated from .contextos/issue_packet.yaml
  |
  v
Cursor repo-local analysis and implementation
  |
  v
GitHub comment/report using .contextos/cursor_response_template.md
  |
  v
ChatGPT review and human approval
```

Create local issue markdown:

```sh
./contextos create-issue
```

Inputs:

- `.contextos/issue_packet.yaml`
- local Git branch and HEAD state
- local remote-tracking metadata when available

Outputs:

- `.contextos/audit/generated_issue.md`
- timestamped issue packet snapshots under `.contextos/audit/issue_packets/`
- timestamped generated issue markdown under `.contextos/audit/generated_issues/`
- reserved Cursor response storage under `.contextos/audit/cursor_responses/`
- reserved verification report storage under `.contextos/audit/verification_reports/`

The issue body includes task summary, expected branch, allowed mutation scope,
protected paths, assumptions, risks, acceptance criteria, required verification
steps, and context freshness metadata:

- current branch
- current HEAD hash
- timestamp
- freshness classification: `FRESH`, `AGING`, `STALE`, or `DIVERGED`

The Cursor response template lives at:

```text
.contextos/cursor_response_template.md
```

It includes sections for proposed implementation plan, files likely touched,
risks, tests required, branch assumptions, unresolved questions, recommended Git
actions, and deterministic explanations for those Git commands.

### Reasoning vs authority separation

ChatGPT and Cursor may reason about tasks, summarize context, propose plans, and
produce implementation reports. They do not become the approval authority.
Humans remain responsible for:

- deciding whether to post the generated GitHub Issue
- approving implementation scope
- reviewing Cursor's response
- approving commits, pull requests, and merges

### Workflow limitations

- `contextos create-issue` only generates local markdown; it does not create a
  GitHub Issue.
- Freshness is based on local Git metadata.
- Generated issue markdown should be reviewed before posting.
- The bridge coordinates handoff context; it does not replace tests, review, or
  merge approval.

## Export last Cursor plan

Use `contextos export-last-plan` when ChatGPT needs a structured overview of the
most recent Cursor-executed plan without reconstructing it manually:

```sh
./contextos export-last-plan
```

The command is read-only. It does not call ChatGPT APIs, Cursor APIs, GitHub
APIs, push, commit, or mutate Git state.

It looks for the most recent local execution result in:

- `.contextos/execution_result.md`
- `.contextos/audit/execution_results/*.md`
- `.contextos/audit/verification_reports/*.md`

If no execution result exists, the command fails clearly and explains where to
write one.

Sample execution result input:

```markdown
# Implement issue bridge

## Original objective
Generate local GitHub Issue markdown from an issue packet.

## Implementation summary
- Added `contextos create-issue`.

## Files changed
- contextos.py
- tests/test_contextos.py

## Tests run
- python3 -m unittest discover -s tests

## Test results
PASS

## Policy/verification result
Verification passed locally.

## Unresolved issues
- None.

## Recommended next action
Review generated issue markdown before posting.

## Recommended Git commands
- git status

## Human approval required
Yes. Human review is required before posting or merging.
```

Sample export excerpt:

````markdown
# Last executed Cursor plan overview

## Plan/task name
Implement issue bridge

## Git status summary
```text
## cursor/minimal-verification-cli-78c4...origin/cursor/minimal-verification-cli-78c4
```

## Recommended Git command explanations
### `git status`

- Explanation: Shows current repository state including modified files, staged files, untracked files, and branch status.
- Risk: `READ_ONLY`
- Potential consequences: No repository files, refs, or remotes are changed.
- Changes state: no

## Human approval required
Yes. Human review is required before posting or merging.
````

## Repo-state switch requests

Use `contextos request-switch` when a ChatGPT-generated plan needs to request a
repository or branch state change. The command inspects local Git state,
explains proposed Git commands, writes a report, and refuses to execute any
state-changing switch unless `--approve` is explicitly provided.

Dry-run request:

```sh
./contextos request-switch \
  --target-repo . \
  --target-branch feature/clientA \
  --reason "Continue reviewed Client A work" \
  --requested-by "ChatGPT" \
  --source-context "issue-123" \
  --expected-current-branch main \
  --expected-current-head <current-head-hash>
```

Approved execution, only after human review:

```sh
./contextos request-switch \
  --target-repo . \
  --target-branch feature/clientA \
  --reason "Continue reviewed Client A work" \
  --requested-by "ChatGPT" \
  --source-context "issue-123" \
  --expected-current-branch main \
  --expected-current-head <current-head-hash> \
  --approve
```

Behavior:

- inspects repo root, current branch, current HEAD, staged changes, unstaged
  changes, and untracked files
- blocks automatic switching when the working tree is dirty
- recommends read-only commands first, such as `git status` and
  `git diff --cached --name-only`
- proposes `git switch <branch>` when the branch exists locally
- proposes `git fetch` plus `git switch <branch>` when the branch is not known
  locally
- explains every recommended Git command with risk and state-change metadata
- writes `.contextos/state_switch_report.md`
- stores audit copies under `.contextos/audit/state_switches/`

Sample report excerpt:

```markdown
# ContextOS repo-state switch request

## Current Git state before request

- Current branch: main
- Current HEAD: <current-head-hash>
- Dirty working tree: no

## Proposed Git commands

- git switch feature/clientA

## Git command explanations

### `git switch <branch>`

- Explanation: Switches the working tree and HEAD to the specified branch.
- Risk: `STATE_CHANGING`
- Potential consequences: HEAD and working tree state can change. Uncommitted changes may conflict with the switch.
- Changes state: yes

## Human approval requirement

State-changing Git commands require explicit human approval via `--approve`.
```

## Execution-context freshness verification

Use `contextos verify-freshness` to classify whether a previously generated
implementation plan still matches current repository reality:

```sh
./contextos verify-freshness --plan .contextos/execution_plan.md
```

The command compares:

- current branch
- current HEAD
- current working tree status
- execution plan timestamp
- expected files/scope
- last verified repo state

Classifications:

- `FRESH`: branch and HEAD match, there are no unauthorized mutations, and no
  major drift is detected.
- `AGING`: branch and HEAD match, but local changes exist inside expected scope.
- `STALE`: plan timestamp exceeds the freshness threshold or assumptions may be
  degraded by time.
- `DIVERGED`: branch mismatch, HEAD mismatch, unauthorized file modification,
  or policy/scope violation.

Outputs:

- `.contextos/freshness_report.md`
- audit copies under `.contextos/audit/freshness_reports/`

Sample failure scenario:

```markdown
# Freshness checked plan

## Plan timestamp
2026-05-20T12:00:00Z

## Expected branch
feature/clientA

## Expected HEAD
abc123

## Expected files/scope
- docs/clientA.md

## Last verified branch
feature/clientA

## Last verified HEAD
abc123
```

If the current branch is `main` or a file outside `docs/clientA.md` changed,
ContextOS classifies the plan as `DIVERGED`, recommends re-planning, and marks
execution as blocked. This enforces the architectural rule that reasoning
generated against one repo state should not automatically retain mutation
authority after repo-state divergence.

## ContextOS ingest

Convert a reviewed ChatGPT context packet into deterministic local execution
context:

```sh
./contextos ingest context_packet.yaml
```

Example `context_packet.yaml`:

```yaml
project: ContextOS
repo: ContextOS
branch: main
task: Add local ingest command
allowed_paths:
  - README.md
  - src
```

The ingest command validates required packet fields, compares `repo` and
`branch` with the current local Git repository, and fails clearly on mismatch.
When valid, it writes `.contextos/session_context.json` with the packet context,
UTC timestamp, current Git HEAD hash, and `source: chatgpt_context_packet`.

## Git command explanations

Use `contextos explain-git` when documenting or recommending Git commands. The
output is deterministic and includes what the command does, risk classification,
potential consequences, and whether it changes state.

Terminal output:

```sh
./contextos explain-git git status
```

```text
Recommended:
git status

Explanation:
Shows current repository state including modified files, staged files, untracked files, and branch status.

Risk:
READ_ONLY

Potential consequences:
No repository files, refs, or remotes are changed.

Changes state:
no
```

Markdown output:

```sh
./contextos explain-git --format markdown git reset --hard HEAD
```

````markdown
### Recommended Git command

```sh
git reset --hard HEAD
```

**Explanation:** Resets tracked files to the latest commit and permanently discards uncommitted tracked-file changes.

**Risk:** `DESTRUCTIVE`

**Potential consequences:** Uncommitted tracked-file changes are lost. Untracked files are not removed.

**Changes state:** yes
````

Supported risk classifications:

- `READ_ONLY`
- `STATE_CHANGING`
- `REMOTE_CHANGING`
- `DESTRUCTIVE`

## Verification CLI

Run the deterministic verification CLI from the repository root:

```sh
./contextos verify --session session.json --policy policy.yaml --report audit.md
```

`verify_cli.py` remains the underlying deterministic verifier used by
`contextos verify`.

`session.json` must be valid JSON. `policy.yaml` supports a minimal YAML subset
with a required `allowed_paths` list:

```json
{
  "expected_branch": "main"
}
```

```yaml
allowed_paths:
  - README.md
  - src
protected_paths:
  - ".github/workflows/**"
  - "deploy/**"
  - "infra/**"
  - ".env"
```

Each allowed path matches the exact file or any child path below it. The
optional `expected_branch` value is compared with the current git branch. The
CLI runs git status and `git diff --name-only`, then prints deterministic
terminal output with colored pass/fail status, expected versus actual branch,
explicit mismatch reasons, and unauthorized files. When `--report` is provided,
the CLI writes a markdown audit report containing a UTC timestamp, repo, branch,
changed files, allowed files, violations, and git status summary.

Protected paths are evaluated against the staged diff from `git diff --cached
--name-only`. In advisory mode, staged protected path changes produce a warning
without failing verification:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode advisory
```

In enforce mode, staged protected path changes fail verification:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode enforce
```

Protected path violations are included in markdown audit reports.

When `.contextos/session_context.json` exists, the verification CLI also checks
that the current branch and Git HEAD still match the ingested context, detects
detached HEAD state, and checks whether the local branch is behind its
configured remote-tracking branch. Context freshness is classified as `FRESH`,
`AGING`, `STALE`, or `DIVERGED`. Non-fresh context fails verification with
deterministic remediation steps:

```text
CONTEXT STALE
Reason:

- session created on feature/clientA
- current branch is main
- HEAD changed after ingestion

Suggested remediation:

1. regenerate context packet
2. run contextos ingest
3. revalidate before commit
```

Install the standard local Git pre-commit hook to run verification before each
commit:

```sh
python3 install_hooks.py --mode enforce
```

This writes `.git/hooks/pre-commit` in the current repository. The installed
hook executes `verify_cli.py` and aborts the commit when verification fails.

Use advisory mode when protected path touches should warn without blocking:

```sh
python3 install_hooks.py --mode advisory
```

Sample installation output:

```text
ContextOS hook installer
repo: /path/to/repo
hook: /path/to/repo/.git/hooks/pre-commit
mode: enforce
status: installed
```

Sample blocked commit output:

```text
ContextOS pre-commit: running verify_cli.py
protected paths: FAILED
protected mode: enforce
protected path violations:
  protected path violation: deploy/production.yml matches deploy/**
verification: FAILED
ContextOS pre-commit: verification failed; commit blocked
Suggested remediation:
1. review the verification output above
2. regenerate the context packet if context is stale
3. run: ./contextos ingest context_packet.yaml
4. adjust staged changes or policy before retrying
```

The repository also includes `.githooks/pre-commit` for workflows that prefer
`git config core.hooksPath .githooks`.

Recommended:

```sh
git config core.hooksPath .githooks
```

Explanation:

Configures this repository to load Git hooks from the tracked `.githooks`
directory.

Risk:

`STATE_CHANGING`

Potential consequences:

Local repository configuration changes. Future Git commands can run hooks from
`.githooks`.

Changes state:

yes
