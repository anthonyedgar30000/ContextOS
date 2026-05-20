# JillyPickles stale execution-plan demo

This demo shows how ContextOS prevents a stale execution plan from reaching a
commit or push. It uses a local toy repository named `JillyPickles`; no network
services or external APIs are required.

## Scenario

1. Start on BranchA: `feature/clientA`.
2. Generate a reviewed context packet for `feature/clientA`.
3. Run `contextos ingest` to create `.contextos/session_context.json`.
4. Switch locally to BranchB: `main`.
5. Simulate an assistant continuing under the stale `feature/clientA`
   assumptions.
6. Attempt an unauthorized mutation to `deploy/production.yml`.
7. Run verification in protected-path enforce mode.
8. ContextOS detects the stale branch/HEAD and protected-path violation before
   any commit or push.

## Run it

From the repository root:

```sh
demos/jillypickles-stale-plan/run_demo.sh
```

By default, the script recreates the local demo repository at:

```text
/tmp/contextos-jillypickles-demo/JillyPickles
```

To use a different parent directory:

```sh
CONTEXTOS_DEMO_WORKDIR=/tmp/my-contextos-demo demos/jillypickles-stale-plan/run_demo.sh
```

## Files

- `run_demo.sh` - reproducible local demo script.
- `context_packet.yaml` - sample reviewed ChatGPT context packet for BranchA.
- `sample_violation.md` - unauthorized mutation example.
- `expected_terminal_output.txt` - representative terminal output with stable
  paths and deterministic ContextOS messages.
- `screenshots/` - placeholder directory for captured demo screenshots.

## Why this is realistic

The stale-plan failure is a common local workflow risk:

- A reviewed context packet is generated for one branch.
- The developer or agent switches branches before applying the plan.
- The staged mutation touches a deployment file that was never in scope.
- Verification checks local Git state, staged paths, and the ingested session
  context before a commit can proceed.

The demo intentionally combines two independent safeguards:

- **Context freshness:** `.contextos/session_context.json` records the branch
  and HEAD hash from `contextos ingest`.
- **Protected paths:** `verify_cli.py --protected-mode enforce` blocks staged
  changes under `deploy/**`.

The expected result is a non-zero verification exit and a clear remediation:

```text
CONTEXT STALE
Reason:

- branch switched from feature/clientA to main
- HEAD changed since context ingestion

Suggested remediation:

1. regenerate context packet
2. run contextos ingest again
```
