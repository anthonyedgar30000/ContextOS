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
- Pull request: **#15**
- Owner: this bounded ContextOS deployment conversation
- Other conversations: review-only unless ownership is explicitly transferred

## Declared scope

Exactly nine paths:

1. `deployment/README.md`
2. `deployment/install-contextos.sh`
3. `deployment/verify-contextos.sh`
4. `deployment/uninstall-contextos.sh`
5. `.github/workflows/contextos-local-deployment-ci.yml`
6. `.github/workflows/helix-query-bridge-ci.yml`
7. `.contextos/contracts/CTX-0004-contextos-local-deployment-readiness.yaml`
8. `.project/active-work.json`
9. `.project/handoffs/current-state.md`

Core ContextOS code, tests, the HELIX bridge implementation, its documentation and contract, the parked workflow, runtime directories, cloud configuration, credentials, and external repositories are protected.

## Deployment model implemented

- Target: a user-owned Linux or WSL host with Git and Python 3.11 or newer.
- Install location: `$HOME/.local/bin/contextos` by default.
- Evidence location: `$HOME/.local/share/contextos/deployment.json` by default.
- Launcher type: a generated, user-owned Bash launcher bound to the absolute reviewed source checkout.
- Evidence binding: source root, full Git commit, source cleanliness, launcher path, Python executable, and UTC installation time.
- Pre-install gate: complete repository unit suite unless explicitly skipped.
- Verification: exact commit and clean-tree binding, state-shape validation, CLI help, deterministic `READ_ONLY` explanation for `git status`, and complete unit suite.
- Rollback: remove only the managed launcher and deployment evidence; preserve the source checkout and repository data.

## Reality-synchronization findings during CI

### 1. Shared-workflow ownership assumption

The first deployment workflow passed, but the existing `HELIX Query Bridge CI` failed on the same deployment-only head.

Root cause:

- that workflow intentionally triggers when shared project ownership files change;
- its ownership assertion assumed `state['workstreams'][0]` always belonged to the HELIX bridge;
- replacing the completed HELIX workstream with the current deployment workstream caused a false ownership failure.

Bounded remediation:

- the HELIX workflow now searches for a workstream that explicitly permits `.github/workflows/helix-query-bridge-ci.yml`;
- it requires exactly one owner when claimed;
- it exits successfully with an explicit message when unrelated coordination does not claim that workflow;
- the deployment workflow selects its own workstream by `workstream_id` rather than array position.

### 2. Synthetic merge checkout was not exact-head evidence

Both workflows initially reported success against GitHub's default `pull/<number>/merge` checkout. The workflow run was associated with the PR head, but the executed files came from a synthetic merge commit.

That means:

```text
workflow associated with head SHA != workflow executed on head SHA
merge-ref success != exact-head success
```

Bounded remediation:

- both workflows now set `actions/checkout` to `${{ github.event.pull_request.head.sha }}`;
- both disable persisted checkout credentials;
- both assert `git rev-parse HEAD` equals the event's exact head SHA before testing.

These changes affect CI evidence semantics and workflow ownership isolation only. They do not enable, invoke, or alter `helix_context.py` package behavior.

## Authority boundary

This increment may create repository files and a draft pull request only. It does not:

- execute installation on Anthony's NUC, WSL environment, or another host;
- install a service or use `systemctl`;
- require `sudo` or modify system directories;
- enable or invoke `helix_context.py`;
- use credentials;
- call GitHub, Azure, HELIX, or another external API at runtime;
- mutate cloud resources or external repositories;
- authorize merge.

## Verification required

1. both workflows explicitly check out and assert the exact pull-request head SHA;
2. syntax-check all three deployment scripts with `bash -n`;
3. assert prohibited privileged, network, cloud, GitHub CLI, and HELIX bridge commands are absent;
4. exercise default install, verification, and rollback under an isolated temporary `HOME`;
5. run the complete ContextOS unit suite on the exact pull-request head;
6. prove the HELIX workflow resolves ownership by declared workflow path rather than array position;
7. obtain success from both dedicated workflows on the same exact head;
8. confirm the complete pull-request diff remains exactly the nine declared paths;
9. inspect the exact generated launcher and deployment evidence semantics;
10. retain actual host installation as a separate explicit human gate.

## Next gate

1. resolve PR #15's exact current head from live GitHub;
2. obtain and inspect exact-head results for both dedicated workflows after the checkout correction;
3. confirm the final diff remains exactly the nine declared paths;
4. perform a deployment-safety, workflow-isolation, exact-head-evidence, and rollback review against that exact head;
5. after a separate merge decision, choose the actual Linux or WSL checkout and explicitly authorize running the installer there.
