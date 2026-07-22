# ContextOS HELIX Query Bridge repair handoff

## Live baseline

- Repository: `anthonyedgar30000/ContextOS`
- Default branch: `main`
- Baseline observed before branch creation: `d366bf0431716d0c87cd548a42db5810c76f0ccc`
- That commit is the merge of PR #13 at source head `98d268198465bcea6b73cdf552732acc9e5f4246`.
- PR #13 merged with a recorded five-finding blocking review and without an exact-head GitHub Actions run.

## Sole write owner

- Branch: `fix/helix-query-bridge-review-findings`
- Pull request: resolve from live GitHub after creation
- Owner: this bounded repair conversation
- Other conversations: review-only unless ownership is explicitly transferred

## Declared scope

Exactly seven paths:

1. `helix_context.py`
2. `tests/test_helix_context.py`
3. `docs/HELIX_QUERY_BRIDGE.md`
4. `.contextos/contracts/CTX-0003-helix-query-bridge-repair.yaml`
5. `.github/workflows/helix-query-bridge-ci.yml`
6. `.project/active-work.json`
7. `.project/handoffs/current-state.md`

The parked PR #9 workflow `.github/workflows/contextos-ci.yml` is protected and not modified.

## Findings being repaired

1. Accept current HELIX `project.active-work.v1` fields rather than requiring the obsolete synthetic `scope` field.
2. Accept current ServiceTracer `project.active-work.v2` baseline, observation, authored-change, and bounded-grant shape.
3. Recursively constrain allowed nested JSON and reject secret-like fields, excessive depth/cardinality/size, unsupported types, and non-finite numbers.
4. Derive package completeness from requested capabilities and supplied evidence; missing required evidence must make the package explicitly incomplete.
5. Add a dedicated read-only CI path with no overlap with parked PR #9.
6. Preserve repository-native ownership, permitted paths, protected paths, verification criteria, and capability boundaries.

## Authority boundary

This increment changes repository code, tests, documentation, CI, and coordination records only. It does not:

- deploy ContextOS or HELIX;
- call Azure, GitHub, or another external API at runtime;
- execute inventory or What-If;
- use credentials;
- mutate cloud resources;
- grant an AI shell or mutation authority;
- write to HELIX, ServiceTracer, or Protocol Kernel repositories.

## Verification sequence

1. focused local compile and unit tests;
2. publish only the seven declared files;
3. open a draft PR and bind its number into `.project`;
4. obtain fresh CI for the resulting exact head;
5. inspect every job and confirm the final diff remains exactly seven paths;
6. record a read-only containment and evidence review;
7. require a separate explicit merge decision.
