# JillyPickles ContextOS Handover

JillyPickles is the governed target application for the ContextOS demo.

## Healthy application context

- App identity: `JillyPickles`
- Protected branch: `main`
- Required order route: `/pickles/order`
- Required feature flag: `pickle_ordering_enabled = true`
- Required environment: `production`

## AI handoff awareness

- Originating task: JillyPickles governed target app demo
- Originating branch: `main`
- Repo assumptions:
  - JillyPickles is the target app, not another client project
  - pickle ordering remains enabled
  - order route remains `/pickles/order`
  - config changes should stay inside `JillyPickles/config.json` unless scope is updated
- Expected scope:
  - `JillyPickles/config.json`
  - `JillyPickles/ui/*`
- Unresolved warnings: none at handoff
- Stale assumptions to re-check:
  - whether Cursor retained another client/project context
  - whether branch is still `main`
  - whether config edits touched deployment, billing, auth, or CI files

## Drift scenario

A stale assistant context remembers an old cucumber-cart experiment and changes
`config.json` to disable pickle ordering and route customers to
`/old-cucumber-cart`. Without a governance gate, that change can become
authoritative Git state and break the storefront.

## Operator checklist

1. Run `python3 verifier.py verify --action manual --mode advisory --policy JillyPickles/.contextos/policy.yaml --state JillyPickles/.contextos/state_manifest.json --session JillyPickles/.contextos/session_context.json --audit-log JillyPickles/audit_log.jsonl`.
2. Run `python3 JillyPickles/app.py` to confirm the app is healthy.
3. Confirm the Git branch is the protected branch before commit or push.
4. Resync Cursor context when ContextOS reports `STALE` or `DIVERGED`.
