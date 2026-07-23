# ContextOS HELIX Query Bridge

## Purpose

The HELIX Query Bridge lets an AI reasoning node consume bounded project and operational context without receiving unrestricted shell, cloud, repository, or mutation authority.

ContextOS remains the deterministic containment layer. HELIX supplies governed evidence and authority semantics. ServiceTracer contributes deterministic service-path localization without claiming an exact device root cause.

```text
local Git observation
project.active-work.v1 or v2
project.environment-state.v1
bounded ServiceTracer report
              |
              v
     contextos-helix build
              |
              v
contextos.helix-query-package.v1
              |
              v
HELIX reasoning node / AI assistant
```

## Supported project-state contracts

The bridge accepts both repository-native project-state generations currently present in the governed repositories:

- `project.active-work.v1`, including HELIX-style workstreams with `objective`, `permitted_paths`, `protected_paths`, `capability_boundary`, and `verification_criteria`;
- `project.active-work.v2`, including ServiceTracer's `last_substantive_baseline`, time-bounded `repository_observation`, `authored_change`, bounded authority grants, and fail-closed defaults.

Both are normalized into `contextos.project-state-projection.v1`. The projection preserves the bounded ownership and authority information needed for reasoning while dropping unknown top-level source fields.

## Recursive evidence boundary

Allowlisting a top-level field is not enough when that field contains nested JSON. Every allowed nested object now passes through a recursive policy that:

- rejects credential-, secret-, token-, bearer-, authorization-, SAS-, password-, and private-key-like field names at any depth;
- rejects non-finite numbers and unsupported JSON types;
- bounds depth, object/list cardinality, string length, and canonical JSON size;
- applies typed checks to ServiceTracer incident counts and backend failure rates;
- keeps ServiceTracer exact-root-cause claims prohibited.

Unknown top-level input fields are dropped. Allowed nested structures are recursively constrained rather than copied blindly.

## Capability/evidence completeness

Completeness is derived from the capabilities in the package:

| Capability | Required evidence source |
| --- | --- |
| `query_project_state` | `declared_project_state` |
| `query_environment_facts` | `observed_environment_facts` |
| `query_servicetracer_findings` | `servicetracer_finding` |
| `query_git_state` | `observed_git_state` |

Request-only capabilities do not pretend that the requested operation already ran. When a requested query source is absent, the package is emitted with:

```text
package_complete_for_bounded_query = false
```

and the exact source appears in `missing_required_sources`. Validation recomputes this relationship, so a producer cannot rehash a package with a false completeness claim.

## What the package contains

- local Git branch, HEAD, dirty state, and bounded changed paths;
- normalized project ownership, scope, capability boundaries, and gates;
- recursively constrained environment facts;
- a bounded ServiceTracer technician-handoff projection;
- source-file SHA-256 provenance;
- expiry, sequence metadata, and a canonical JSON integrity hash;
- bounded read-only or request-only capabilities;
- explicit required, present, missing-required, and missing-optional source lists.

The local repository root path is not included in the package.

## What it does not do

The bridge does not:

- open SSH or provide a shell;
- call Azure, GitHub, or other remote APIs;
- execute inventory, What-If, deployment, repair, or publication actions;
- grant mutation authority;
- turn a candidate recommendation into an authorized decision;
- treat a request-only capability as an executed action;
- accept a ServiceTracer exact-root-cause claim.

## Build and validate

```bash
python3 helix_context.py build \
  --repo ../azure-iac-msp-lab \
  --query "What is verified, what is stale, and what bounded step is permitted next?" \
  --capability query_project_state \
  --capability query_environment_facts \
  --capability query_servicetracer_findings \
  --capability query_git_state \
  --capability request_human_review \
  --project-state ../azure-iac-msp-lab/.project/active-work.json \
  --environment-state ../azure-iac-msp-lab/.project/environment-state.json \
  --servicetracer-report ../azure-iac-msp-lab/docs/technician-handoff-report.json \
  --ttl-minutes 60 \
  --output .contextos/audit/helix-query-package.json

python3 helix_context.py validate .contextos/audit/helix-query-package.json
```

## CI ownership

The bridge repair uses `.github/workflows/helix-query-bridge-ci.yml`. It does not touch the parked PR #9 path `.github/workflows/contextos-ci.yml`. The dedicated workflow has `contents: read`, runs only local compilation/tests and project-record parsing, and receives no cloud or repository-write authority.

## ServiceTracer boundary

ServiceTracer contributes deterministic localization, comparison paths, containment status, and uncertainty. The bridge fails closed unless:

- `investigation_boundary.exact_root_cause_claimed` is `false`; and
- `root_cause.status` is `not_determined_by_servicetracer`.

A valid package does not prove that the source evidence is current or operationally truthful. Source freshness and authority remain separate evidence questions.

## Relationship to HELIX Protocol Kernel

`contextos.helix-query-package.v1` remains a ContextOS integration profile, not yet a canonical runtime artifact in `helix-protocol-kernel`. A later bounded kernel increment may register it, define ACK/NACK and invalidation handling, and validate manifests without giving the transport operational authority.
