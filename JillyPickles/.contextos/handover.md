# JillyPickles ContextOS Handover

JillyPickles is the governed target application for the ContextOS demo.

## Healthy application context

- App identity: `JillyPickles`
- Protected branch: `main`
- Required order route: `/pickles/order`
- Required feature flag: `pickle_ordering_enabled = true`
- Required environment: `production`

## Drift scenario

A stale assistant context remembers an old cucumber-cart experiment and changes
`config.json` to disable pickle ordering and route customers to
`/old-cucumber-cart`. Without a governance gate, that change can become
authoritative Git state and break the storefront.

## Operator checklist

1. Run `python3 verifier.py verify --action manual --policy JillyPickles/.contextos/policy.yaml --state JillyPickles/.contextos/state_manifest.json --audit-log JillyPickles/audit_log.jsonl`.
2. Run `python3 JillyPickles/app.py` to confirm the app is healthy.
3. Confirm the Git branch is the protected branch before commit or push.
4. Resync Cursor context when ContextOS reports `STALE` or `DIVERGED`.
