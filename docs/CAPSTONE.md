# ContextOS capstone documentation

## Abstract

ContextOS is a lightweight deterministic execution-boundary layer for
AI-assisted development workflows. It converts reviewed task context into local
execution contracts, validates those contracts against authoritative Git state,
and blocks or reports mutations that fall outside the declared boundary. The
system is intentionally local-first: it relies on files, Git commands, terminal
output, and markdown reports rather than external services. Its purpose is to
make branch context, file scope, protected paths, and provenance explicit before
AI-assisted changes are committed or pushed.

ContextOS is not AGI governance, autonomous AI safety, or enterprise
orchestration. It is a practical execution-boundary mechanism for everyday
software development workflows that include AI-assisted edits.

## Problem statement

AI-assisted development often begins with a reviewed task: a target repository,
a branch, a file scope, and an expected implementation objective. During local
work, the repository can move away from that reviewed context. A developer can
switch branches, advance or rewind HEAD, stage unrelated files, or touch files
that were never part of the reviewed scope.

The resulting problem is not that code generation is inherently unsafe. The
problem is that an assistant can continue operating under assumptions that are
no longer true in the local repository. Without a deterministic boundary check,
stale assumptions may persist until review, CI, or production deployment catches
the mismatch.

ContextOS addresses this by making execution context explicit and validating it
at local execution time.

## Observed failure mode

The core observed failure mode is stale execution context:

1. A task is reviewed on BranchA.
2. A context packet is generated for BranchA.
3. AI-assisted work proceeds under BranchA assumptions.
4. The developer switches locally to BranchB.
5. The assistant or developer continues applying the original plan.
6. A mutation is staged outside the original branch or path scope.
7. The mismatch is not visible unless local tooling checks it.

The JillyPickles demo models this failure with a realistic deployment-file
mutation:

- BranchA: `feature/clientA`
- BranchB: `main`
- reviewed scope: Client A documentation and recommendation code
- unauthorized mutation: `deploy/production.yml`

The demo shows ContextOS detecting the stale context and blocking the commit
before any push occurs.

## Architectural gap

Common local workflows already have useful tools:

- Git tracks branch, HEAD, staged files, and working-tree changes.
- Pre-commit hooks can block local commits.
- Code review and CI can inspect committed changes.

The gap is that these tools do not automatically bind an AI-assisted task to the
reviewed execution context that produced it. A branch switch, HEAD change, or
path-scope violation can occur without a deterministic comparison against the
original task boundary.

ContextOS fills that gap by introducing explicit local contracts and checking
them against Git before commit or push.

## ContextOS design

ContextOS is built around a local CLI command surface and a small set of local
files.

### Command surfaces

- `contextos verify`
  - checks Git state, declared path scope, protected paths, and context
    freshness before allowing work to proceed
  - delegates to the deterministic verification implementation in
    `verify_cli.py`

- `contextos ingest <context_packet.yaml>`
  - reads reviewed context
  - validates required packet fields
  - compares packet repo and branch against local Git state
  - writes `.contextos/session_context.json`

- `contextos verify-freshness`
  - classifies whether an execution plan still matches current repository state

- `contextos create-issue`
  - generates local GitHub Issue markdown from `.contextos/issue_packet.yaml`
  - does not call the GitHub API

- `contextos export-last-plan`
  - exports the latest local Cursor execution result for ChatGPT review
  - does not call ChatGPT or Cursor APIs

- `contextos request-switch`
  - creates an approval-gated repository state switch request
  - does not switch branches unless explicitly approved and validation passes

- `contextos explain-git`
  - explains recommended Git commands with risk and state-change metadata

### Local files

- `context_packet.yaml`: reviewed task context
- `.contextos/session_context.json`: ingested branch, HEAD hash, timestamp, and
  source metadata
- `.contextos/contracts/`: task-specific Intent Contracts
- `.contextos/policies/`: normalized policy examples and future local policy
  inputs
- `policy.yaml`: allowed paths and protected paths
- `session.json`: verification-time session configuration
- `audit.md`: optional markdown verification report

### Architecture diagram

```text
Reviewed task context
        |
        v
context_packet.yaml
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
| - context freshness         |        | - branch             |
| - HEAD hash check           |        | - HEAD hash          |
| - path-scope enforcement    |        | - working tree diff  |
| - protected-path check      |        | - staged diff        |
| - audit report generation   |        | - upstream metadata  |
+-----------------------------+        +----------------------+
        |
        v
terminal result + optional markdown audit report + pre-commit decision
```

## Execution-boundary concept

An execution boundary is the local, deterministic contract that defines where a
task may operate. It combines:

- the branch where context was ingested
- the HEAD hash where context was ingested
- the reviewed task description
- allowed file paths
- protected file paths
- current Git branch
- current Git HEAD
- staged and unstaged changes

The boundary is not an abstract policy layer. It is a concrete comparison
between declared local files and current local Git state.

## Policy-aware assurance model

ContextOS can ingest standing organizational policy while remaining a
deterministic local assurance engine. Policy is always active. Intent Contracts
are task-specific constraints layered on top of standing policy, and they do not
replace policy.

The assurance hierarchy is:

```text
Policy
+
Intent Contract
+
Observed State

Assurance Decision
```

Equivalently, ContextOS evaluates the task-specific Intent Contract, standing
policy, and observed Git state to produce a deterministic assurance decision:

```text
Intent Contract
+
Policy
+
Observed Git State

Assurance Decision
```

### Intent-to-Policy fallback

ContextOS evaluates changed paths against the active Intent Contract first. The
Intent Contract is task-specific authorization. If a changed path is not covered
by the Intent Contract, ContextOS falls back to repository policy.

Repository policy is standing governance, not task-specific approval. Policy
fallback does not automatically approve a change. It creates a lower-confidence
classification that determines the next step. ContextOS must never fail open:
the final fallback is default human review or default deny.

The fallback hierarchy is:

1. Intent Contract
2. Repository Policy
3. Default Human Review / Default Deny

| Condition | Result |
| --- | --- |
| Intent match | Compliant |
| Intent miss + policy allow | Policy-allowed, confidence reduced |
| Intent miss + policy review_required | Human review required |
| Intent miss + policy block | Blocked |
| Intent miss + no policy | Default review required / deny |

Path-level classifications include `intent_allowed`, `policy_allowed`,
`review_required`, `blocked`, `default_review_required`,
`confidence_reduced`, and `governance_metadata`.

Governance metadata paths such as `.contextos/contracts/` and
`.contextos/policies/` should normally require human review unless the active
Intent Contract explicitly allows governance metadata changes.

Example assessment for this branch:

| Changed file | Assessment |
| --- | --- |
| `README.md` | allowed by Intent Contract (`intent_allowed`) |
| `docs/CAPSTONE.md` | allowed by Intent Contract (`intent_allowed`) |
| `docs/POLICY_CONNECTORS.md` | allowed by Intent Contract (`intent_allowed`) |
| `.contextos/contracts/CTX-0001-contextos-readme-update.yaml` | not covered by Intent Contract; policy fallback required (`review_required`, `governance_metadata`) |
| `.contextos/policies/normalized-policy.example.yaml` | not covered by Intent Contract; policy fallback required (`review_required`, `governance_metadata`) |

The expected final decision is `REVIEW REQUIRED` because governance metadata
changed outside the explicit Intent Contract.

### Intent Contracts

Intent Contracts record approved task boundaries under `.contextos/contracts/`.
They describe the objective, branch, allowed paths, protected paths, success
criteria, assumptions, risks, architecture-change allowance, and human approval
requirements for one unit of work.

### Policy Connectors

A Policy Connector translates an external policy source into a normalized
ContextOS policy model. Future sources may include GitHub `CODEOWNERS`, GitHub
branch protection settings, repository policy files, security policy
repositories, change management systems, and team ownership definitions.

Policy Connectors are translation boundaries only. They should not post
comments, create tickets, send notifications, approve changes, or trigger
workflow automation from ContextOS core.

### Normalized Policy Model

The normalized policy model is a local representation of standing policy. It
should support concepts such as:

- allowed paths
- review required paths
- blocked paths
- protected paths
- ownership
- approval requirements
- freshness requirements
- default action

Example normalized policy files can live under `.contextos/policies/` as
documentation and structure until runtime support is explicitly added. A
normalized policy can include `allowed`, `review_required`, `blocked`, and
`default_action` sections so fallback classification is explicit.

### Assurance Decision Flow

ContextOS compares policy, intent, and observed Git state to produce findings:

- `COMPLIANT`
- `REDUCED_ASSURANCE`
- `ARCHITECTURE_DRIFT`
- `POLICY_VIOLATION`

ContextOS does not decide organizational actions. One organization may post a
GitHub comment, another may create a Jira ticket, and another may require Change
Advisory Board review. Those actions are outside ContextOS core.

### Fail safe assurance model

| Intent state | Policy state | Assurance result |
| --- | --- | --- |
| Intent Known | Policy Known | Normal Assurance |
| Intent Missing | Policy Known | Reduced Assurance |
| Intent Known | Policy Missing | Reduced Assurance |
| Intent Missing | Policy Missing | Human Review Required |
| Policy violations | Policy Known | Escalation |

Policy violations produce escalation findings for organizations to handle
outside ContextOS core.

## AI-assisted mutation definition

An AI-assisted mutation is a repository change made by, suggested by, or
continued from an AI-assisted development session. ContextOS does not attempt to
infer intent or assess code quality. It evaluates whether the mutation fits the
declared execution boundary.

Examples:

- a documentation edit generated from a reviewed context packet
- a code change suggested by an assistant and staged by a developer
- a deployment configuration change attempted after branch context has changed

The mutation is acceptable only if local verification confirms that branch
freshness, HEAD freshness, allowed paths, and protected paths remain valid.

## Git authoritative state model

ContextOS treats local Git as the authoritative state source. It does not call
external APIs to decide whether the repository is in scope.

Representative Git inputs include:

- `git rev-parse --show-toplevel`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --porcelain=v1 -z`
- `git diff --name-only`
- `git diff --cached --name-only`
- upstream comparison through local remote-tracking refs

This model keeps verification deterministic and reproducible. If local remote
tracking refs are stale, ContextOS reports based on the local information it can
observe.

## Branch/context desynchronization

Branch/context desynchronization occurs when current Git state no longer
matches the state captured during context ingestion.

ContextOS classifies freshness as:

- `FRESH`: branch and HEAD match the ingested context, and the branch is not
  behind its configured upstream.
- `AGING`: branch and HEAD match the ingested context, but the local branch is
  behind its configured upstream.
- `STALE`: branch or HEAD changed after context ingestion.
- `DIVERGED`: repository is in detached HEAD state.

Example stale output:

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

## Deterministic enforcement model

ContextOS enforcement is deterministic because it is derived from local files
and Git commands.

### Path-scope enforcement

`allowed_paths` define the paths a task may change. Verification fails when
changed files fall outside those paths.

### Protected paths

`protected_paths` define sensitive paths that require additional handling.
Protected paths are evaluated against staged files from:

```sh
git diff --cached --name-only
```

Modes:

- advisory: print warnings without failing verification
- enforce: fail verification when staged protected paths are touched

### Pre-commit enforcement

`install_hooks.py` installs a local `.git/hooks/pre-commit` hook. The hook runs
`verify_cli.py` before commit. In enforce mode, verification failures block the
commit and print remediation guidance.

### Git command explanations

`contextos explain-git` provides deterministic explanations for recommended Git
commands. Each explanation includes:

- what the command does
- risk classification
- potential consequences
- whether it changes state

Supported risk classes:

- `READ_ONLY`
- `STATE_CHANGING`
- `REMOTE_CHANGING`
- `DESTRUCTIVE`

## Audit and provenance reporting

When `--report` is provided, verification writes a markdown audit report with:

- timestamp
- repository
- branch
- changed files
- allowed files
- violations
- context freshness classification and reasons
- protected path violations
- Git status summary

The report is local provenance for a verification event. It records what was
checked and why verification passed or failed.

## Demo walkthrough

The complete stale execution-context demo lives in:

```text
demos/jillypickles-stale-plan/
```

Run it from the repository root:

```sh
demos/jillypickles-stale-plan/run_demo.sh
```

The demo performs the following steps:

1. creates a local `JillyPickles` repository
2. initializes BranchB as `main`
3. creates BranchA as `feature/clientA`
4. generates a BranchA context packet
5. ingests the BranchA context
6. installs the ContextOS pre-commit hook
7. switches locally back to BranchB
8. stages an unauthorized deployment mutation
9. runs verification and writes an audit report
10. attempts a commit
11. observes the hook blocking the commit

Supporting demo artifacts include:

- sample repository setup
- BranchA and BranchB context packet examples
- expected terminal output
- expected audit report excerpt
- failure explanation
- remediation explanation
- screenshots placeholder

## Limitations

- ContextOS depends on local Git metadata. Remote freshness checks are only as
  current as local remote-tracking refs.
- YAML parsing is intentionally minimal and supports the simple packet and
  policy structures used by the tool.
- Protected-path matching is path based; it does not inspect file contents.
- ContextOS does not evaluate code correctness, test adequacy, or review quality.
- ContextOS does not decide organizational actions such as posting comments,
  creating tickets, sending notifications, or triggering workflow automation.
- Audit reports are local markdown records, not cryptographic attestations.
- The tool assumes developers run or install the verification workflow before
  commit or push.

## Future work

- share parsing utilities between `contextos.py` and `verify_cli.py`
- add machine-readable verification output
- add richer policy composition for branch-specific protected paths
- add Policy Connectors that translate external policy sources into normalized
  local policy data
- add optional audit report hashing
- add CI examples while preserving local-first usage
- expand deterministic Git command explanation coverage
- add fixture-based regression tests for demo output

## Glossary

- **AI-assisted mutation:** A repository change made by, suggested by, or
  continued from an AI-assisted development session.
- **Allowed path:** A file or directory path where task changes are permitted.
- **Architecture Drift:** A mismatch between proposed or local changes and the
  approved Intent Contract or documented execution boundary.
- **Assurance Decision:** A deterministic finding produced from policy, intent,
  and observed local Git state.
- **Audit report:** A markdown record of verification inputs, results, and
  violations.
- **Branch/context desynchronization:** A mismatch between current Git state and
  ingested session context.
- **Context packet:** Reviewed task context stored in `context_packet.yaml`.
- **Declared execution contract:** A local file that defines task boundaries,
  such as `policy.yaml` or `.contextos/session_context.json`.
- **Default review required:** The fail-safe result when no Intent Contract or
  repository policy rule covers a changed path.
- **Execution boundary:** The deterministic local boundary that defines where a
  task may operate.
- **Git authoritative state:** The local Git state used as verification input.
- **Governance metadata:** ContextOS policy or Intent Contract metadata that can
  affect task or repository authority.
- **Intent Contract:** A task-specific approved boundary stored under
  `.contextos/contracts/`.
- **Intent-to-Policy fallback:** The hierarchy that checks task-specific intent
  first, repository policy second, and default human review or deny when neither
  applies.
- **Normalized Policy Model:** The local ContextOS representation of standing
  policy produced by Policy Connectors.
- **Policy:** Standing organizational guidance that remains active for every
  task.
- **Policy Connector:** A translation boundary that converts external policy
  sources into normalized local ContextOS policy data.
- **Protected path:** A staged path that warns or blocks when touched.
- **Reduced Assurance:** A finding used when policy or intent context is missing
  or incomplete.
- **Session context:** The ingested `.contextos/session_context.json` file.
- **Stale execution context:** An execution context whose branch or HEAD no
  longer matches local Git state.

## Framing statement

ContextOS is not:

- AGI governance
- autonomous AI safety
- enterprise orchestration

ContextOS is:

> A lightweight deterministic execution-boundary layer for AI-assisted
> development workflows.
