# ContextOS local deployment readiness handoff

## Live baseline

- Repository: `anthonyedgar30000/ContextOS`
- Default branch: `main`
- Baseline at branch creation: `994b3ff8e6d4aaa47d2c9ed6c9eb09aaf27a423d`
- That commit is the merge of PR #14, `Repair merged HELIX query bridge review findings`.
- Repository code on `main` does not prove that ContextOS is installed or running on any host.
- The final PR #14 cross-repository compatibility review identified unresolved HELIX Protocol Kernel compatibility findings. Therefore the HELIX query bridge is excluded from this deployment increment and must not be treated as operationally trusted.

## Deployment meaning

ContextOS is currently a local deterministic CLI rather than a daemon or hosted service.

For the first bounded deployment model:

```text
reviewed source checkout
→ user-scoped managed launcher
→ exact source-commit deployment evidence
→ local smoke tests and full unit suite
→ verified local CLI deployment
```

This does not create an always-on process, public endpoint, cloud workload, autonomous agent, or HELIX runtime consumer.

## Sole write owner

- Branch: `deploy/contextos-local-readiness`
- Pull request: not yet assigned
- Owner: this bounded ContextOS deployment conversation
- Other conversations: review-only unless ownership is explicitly transferred

## Declared scope

Exactly eight paths:

1. `deployment/README.md`
2. `deployment/install-contextos.sh`
3. `deployment/verify-contextos.sh`
4. `deployment/uninstall-contextos.sh`
5. `.github/workflows/contextos-local-deployment-ci.yml`
6. `.contextos/contracts/CTX-0004-contextos-local-deployment-readiness.yaml`
7. `.project/active-work.json`
8. `.project/handoffs/current-state.md`

Core ContextOS code, tests, existing workflows, the HELIX bridge, runtime directories, cloud configuration, credentials, and external repositories are protected.

## Deployment model implemented

- Target: a user-owned Linux or WSL host with Git and Python 3.11 or newer.
- Install location: `$HOME/.local/bin/contextos` by default.
- Evidence location: `$HOME/.local/share/contextos/deployment.json` by default.
- Launcher type: a generated, user-owned Bash launcher bound to the absolute reviewed source checkout.
- Evidence binding: source root, full Git commit, source cleanliness, launcher path, Python executable, and UTC installation time.
- Pre-install gate: complete repository unit suite unless explicitly skipped.
- Verification: exact commit and clean-tree binding, state-shape validation, CLI help, deterministic `READ_ONLY` explanation for `git status`, and complete unit suite.
- Rollback: remove only the managed launcher and deployment evidence; preserve the source checkout and repository data.

## Authority boundary

This increment may create repository files and a draft pull request only. It does not:

- execute installation on Anthony's NUC, WSL environment, or another host;
- install a service or use `systemctl`;
- require `sudo` or modify system directories;
- enable or invoke `helix_context.py`;
- use credentials;
- call GitHub, Azure, HELIX, or another external API;
- mutate cloud resources or remote repositories;
- authorize merge.

## Verification required

1. syntax-check all three deployment scripts with `bash -n`;
2. assert prohibited privileged, network, cloud, GitHub CLI, and HELIX bridge commands are absent;
3. exercise default install, verification, and rollback under an isolated temporary `HOME`;
4. run the complete ContextOS unit suite on the exact pull-request head;
5. confirm the complete pull-request diff remains exactly the eight declared paths;
6. inspect the exact generated launcher and deployment evidence semantics;
7. retain actual host installation as a separate explicit human gate.

## Next gate

1. open a draft pull request from `deploy/contextos-local-readiness`;
2. bind the pull-request number into repository-native ownership records;
3. obtain and inspect exact-head GitHub Actions results;
4. perform a deployment-safety and rollback review against that exact head;
5. after a separate merge decision, choose the actual Linux or WSL checkout and explicitly authorize running the installer there.
