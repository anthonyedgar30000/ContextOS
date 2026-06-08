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

- low risk paths
- review required paths
- protected paths
- ownership
- approval requirements
- freshness requirements

Example normalized policy files can live under `.contextos/policies/`. These
files are documentation and structure until runtime support is explicitly added.

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
