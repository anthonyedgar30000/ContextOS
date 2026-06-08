# Policy Connectors and Assurance Decisions

ContextOS remains a deterministic local assurance engine. It does not implement
notifications, workflow automation, Jira integration, ServiceNow integration,
Slack integration, Teams integration, or any other external action system.

This architecture describes how ContextOS can ingest standing organizational
policy from external sources while keeping assurance decisions reproducible from
local files and observed Git state.

## Assurance hierarchy

ContextOS assurance is based on this hierarchy:

```text
Policy
+
Intent Contract
+
Observed State

Assurance Decision
```

Policy is always active. Intent Contracts are task-specific constraints layered
on top of standing policy. Intent Contracts do not replace policy.

The working model is:

```text
Intent Contract
+
Policy
+
Observed Git State

Assurance Decision
```

The ordering emphasizes the same invariant from either direction: standing
policy and task intent both constrain the observed repository state.

## Intent-to-Policy Fallback

ContextOS first evaluates changed paths against the active Intent Contract. The
Intent Contract is task-specific authorization. If a changed path is not covered
by the Intent Contract, ContextOS falls back to repository policy.

Repository policy is standing governance, not task-specific approval. Policy
fallback does not automatically approve the change. It creates a lower-confidence
classification that determines the next step. ContextOS must never fail open: if
neither intent nor policy covers a path, the result must be default human review
or default deny.

The fallback hierarchy is:

1. Intent Contract
2. Repository Policy
3. Default Human Review / Default Deny

Decision table:

| Condition | Result |
| --- | --- |
| Intent match | Compliant |
| Intent miss + policy allow | Policy-allowed, confidence reduced |
| Intent miss + policy review_required | Human review required |
| Intent miss + policy block | Blocked |
| Intent miss + no policy | Default review required / deny |

Path-level classifications include:

- `intent_allowed`: the path is covered by the active Intent Contract.
- `policy_allowed`: the path missed intent but is allowed by repository policy,
  with `confidence_reduced`.
- `review_required`: the path missed intent and requires human review under
  repository policy.
- `blocked`: the path is blocked by repository policy.
- `default_review_required`: no policy rule matched and the default action is
  human review.
- `confidence_reduced`: policy fallback was used instead of task-specific
  authorization.
- `governance_metadata`: ContextOS policy or Intent Contract metadata that can
  affect task or repository authority.

Governance metadata paths such as `.contextos/contracts/` and
`.contextos/policies/` should normally require human review unless the active
Intent Contract explicitly allows governance metadata changes.

### Current branch fallback example

Intent Contract allowed paths:

- `README.md`
- `docs/`

Observed changed files:

- `README.md`
- `docs/CAPSTONE.md`
- `docs/POLICY_CONNECTORS.md`
- `.contextos/contracts/CTX-0001-contextos-readme-update.yaml`
- `.contextos/policies/normalized-policy.example.yaml`

Assessment:

- `README.md`: allowed by Intent Contract (`intent_allowed`)
- `docs/CAPSTONE.md`: allowed by Intent Contract (`intent_allowed`)
- `docs/POLICY_CONNECTORS.md`: allowed by Intent Contract (`intent_allowed`)
- `.contextos/contracts/CTX-0001-contextos-readme-update.yaml`: not covered by
  Intent Contract; policy fallback required (`review_required`,
  `governance_metadata`)
- `.contextos/policies/normalized-policy.example.yaml`: not covered by Intent
  Contract; policy fallback required (`review_required`,
  `governance_metadata`)

Expected final decision:

```text
REVIEW REQUIRED
```

Reason: the documentation changes are mostly inside the task-specific Intent
Contract, but governance metadata changed outside the explicit Intent Contract.
Those files are policy-classified as governance metadata and require human
review.

## Intent Contracts

An Intent Contract records the approved boundary for a specific task. It can
include:

- objective
- repository and branch
- allowed paths
- protected paths
- success criteria
- assumptions
- risks
- whether architecture changes are allowed
- whether human approval is required

Intent Contracts are stored under `.contextos/contracts/`. They describe the
reviewed task boundary for one unit of work. They are not a substitute for
standing organizational policy.

## Policy Connectors

A Policy Connector translates an external policy source into a normalized
ContextOS policy model. The connector boundary is translation only: it converts
source-specific policy into local normalized policy data that ContextOS can
evaluate deterministically.

Future policy sources may include:

- GitHub `CODEOWNERS`
- GitHub branch protection settings
- repository policy files
- security policy repositories
- change management systems
- team ownership definitions

Policy Connectors should not decide organizational actions. They should not post
comments, create tickets, send notifications, approve changes, or trigger
workflow automation from ContextOS core. Those actions belong outside the
deterministic assurance engine.

## Normalized Policy Model

The normalized policy model is the local representation produced by Policy
Connectors. It should support concepts such as:

- allowed paths
- review required paths
- blocked paths
- protected paths
- ownership
- approval requirements
- freshness requirements
- default action

Example normalized policy files can live under `.contextos/policies/`. These
files are documentation and structure until runtime support is explicitly added.
A normalized policy can include `allowed`, `review_required`, `blocked`, and
`default_action` sections so fallback classification is explicit.

## Assurance Decision Flow

ContextOS compares standing policy, task-specific intent, and observed Git state
to produce findings. It does not decide what the organization must do next.

```text
normalized policy inputs
        |
        v
Policy
        |
        v
Intent Contract
        |
        v
Observed Git State
        |
        v
Assurance Decision
```

Possible findings include:

- `COMPLIANT`: observed state satisfies known policy and known task intent.
- `REDUCED_ASSURANCE`: policy or intent context is incomplete, but the engine can
  still report deterministic findings from available inputs.
- `ARCHITECTURE_DRIFT`: observed or proposed changes no longer match the
  approved Intent Contract or documented execution boundary.
- `POLICY_VIOLATION`: observed state conflicts with standing policy.

Organizations determine what actions to take from these findings. For example:

- Company A may post a GitHub comment.
- Company B may create a Jira ticket.
- Company C may require Change Advisory Board review.

Those actions are outside ContextOS core.

## Fail Safe Assurance Model

ContextOS should fail safe when policy or intent context is missing:

| Intent state | Policy state | Assurance result |
| --- | --- | --- |
| Intent Known | Policy Known | Normal Assurance |
| Intent Missing | Policy Known | Reduced Assurance |
| Intent Known | Policy Missing | Reduced Assurance |
| Intent Missing | Policy Missing | Human Review Required |
| Policy violations | Policy Known | Escalation |

This model preserves local deterministic assurance while recognizing that
missing context lowers confidence. Policy violations are findings for
organizational escalation, not automated actions by ContextOS core.
