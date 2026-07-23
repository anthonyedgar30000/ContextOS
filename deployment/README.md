# ContextOS local deployment

## What “deployed” means

ContextOS is a deterministic local CLI. It is not a daemon, hosted API, cloud service, or autonomous agent.

For this first deployment model, ContextOS is actively deployed when a reviewed source checkout is bound to a user-scoped launcher and that launcher has passed the deployment verification script on a chosen Linux or WSL host.

```text
repository code merged = software available
launcher installed on a host = locally deployed
verification passed = deployment evidenced
service continuously running = not applicable
HELIX bridge operationally trusted = not claimed
```

## Scope and authority

This directory provides an idempotent user-local installation path. It does not:

- use `sudo`;
- install a system service;
- create a privileged account;
- use credentials;
- call GitHub, Azure, HELIX, or another external API;
- mutate cloud or remote resources;
- enable autonomous repository changes;
- deploy or invoke `helix_context.py`.

The HELIX query bridge remains outside this deployment increment until its cross-repository protocol compatibility is resolved and separately reviewed.

## Supported target

The initial target is a user-owned Linux or WSL environment with:

- Bash;
- Git;
- Python 3.11 or newer;
- a reviewed ContextOS checkout;
- `$HOME/.local/bin` available for user commands, or a custom directory supplied through `CONTEXTOS_BIN_DIR`.

No container or always-on process is required because ContextOS operates against the current local Git repository when deliberately invoked.

## Install

From the reviewed ContextOS checkout:

```bash
bash deployment/install-contextos.sh
```

The installer performs these gates before writing the launcher:

1. verifies Bash, Git, and Python 3.11 or newer;
2. confirms the expected ContextOS source files exist;
3. resolves the exact source checkout and Git commit;
4. refuses a dirty source tree unless `--allow-dirty` is explicitly supplied;
5. runs the complete repository unit suite unless `--skip-tests` is explicitly supplied;
6. writes a managed launcher under `$HOME/.local/bin/contextos` by default;
7. records deployment evidence in `$HOME/.local/share/contextos/deployment.json` by default.

Options:

```text
--replace       replace an existing ContextOS-managed launcher
--skip-tests    skip the pre-install unit suite
--allow-dirty   permit installation from a dirty source checkout
```

Environment overrides:

```text
CONTEXTOS_BIN_DIR
CONTEXTOS_STATE_DIR
PYTHON_BIN
```

A normal reviewed deployment should not use `--skip-tests` or `--allow-dirty`.

## Verify

```bash
bash deployment/verify-contextos.sh
```

Verification checks:

- the managed launcher exists and is executable;
- deployment state is valid JSON;
- launcher and state agree on the source checkout;
- the currently checked-out source commit equals the recorded deployment commit;
- `contextos --help` executes successfully;
- `contextos explain-git git status` returns deterministic read-only guidance;
- the complete repository unit suite passes unless `--skip-tests` is supplied.

A passing verification is evidence that the local CLI is installed. It is not evidence that every future repository context is authorized, that the HELIX bridge is compatible, or that a production service exists.

## Roll back

```bash
bash deployment/uninstall-contextos.sh
```

The uninstaller removes only the launcher containing the ContextOS managed marker and the matching deployment-state file. It does not delete the source checkout, Git history, audit artifacts, or user repositories.

Use `--force` only when intentionally removing a launcher whose managed marker cannot be verified.

## PATH

When `$HOME/.local/bin` is not already on `PATH`, add it through the user’s shell profile and begin a new shell session. The installer reports this condition but does not edit shell startup files automatically.

## Separate host-execution gate

Merging these scripts makes ContextOS deployment-ready; it does not install them on Anthony’s NUC, WSL environment, or another host. Choosing the target checkout and running the installer on that host is a separate explicit action with its own observed evidence and rollback result.
