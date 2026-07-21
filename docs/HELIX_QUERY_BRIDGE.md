# ContextOS HELIX Query Bridge

## Purpose

The HELIX Query Bridge lets an AI reasoning node consume current project and operational context without receiving unrestricted shell, cloud, or repository mutation authority.

ContextOS remains the deterministic execution-boundary layer. HELIX supplies the governed evidence and authority model. ServiceTracer contributes bounded service-path localization. The bridge packages those inputs into a short-lived, integrity-checked query package.

```text
Git / ContextOS project state
Azure or lab environment facts
ServiceTracer technician handoff
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

## What the package contains

- current local Git branch, HEAD, dirty state, and changed paths;
- declared workflow ownership and next gates from `project.active-work.v1`;
- evidence-backed environment facts from `project.environment-state.v1`;
- an allowlisted ServiceTracer technician-handoff projection;
- provenance hashes for every supplied source file;
- a query boundary, expiry time, sequence/completeness metadata, and canonical JSON integrity hash;
- an explicit list of bounded capabilities available to the reasoning node.

## What it does not do

The bridge does not:

- open SSH or provide a shell;
- call Azure, GitHub, or other remote APIs;
- execute inventory, What-If, deployment, repair, or publication actions;
- grant mutation authority;
- convert a candidate recommendation into an authorized decision;
- accept a ServiceTracer report that claims an exact root cause.

Capability entries such as `request_read_only_what_if` describe a request the AI may make to a separately governed tool. They are not executable credentials.

## Build a package

```bash
python3 helix_context.py build \
  --repo ../azure-iac-msp-lab \
  --query "Why is the collector replacement blocked, and what evidence-backed step is permitted next?" \
  --capability query_project_state \
  --capability query_environment_facts \
  --capability query_servicetracer_findings \
  --capability query_git_state \
  --capability request_read_only_what_if \
  --capability request_human_review \
  --project-state ../azure-iac-msp-lab/.project/active-work.json \
  --environment-state ../azure-iac-msp-lab/.project/environment-state.json \
  --servicetracer-report ../azure-iac-msp-lab/docs/technician-handoff-report.json \
  --ttl-minutes 60 \
  --output .contextos/audit/helix-query-package.json
```

Validate it before use:

```bash
python3 helix_context.py validate .contextos/audit/helix-query-package.json
```

## Capability catalogue

| Capability | Mode | Meaning |
| --- | --- | --- |
| `query_project_state` | read-only | Read declared branch ownership, scope, and gates. |
| `query_environment_facts` | read-only | Read evidence-backed environment facts. |
| `query_servicetracer_findings` | read-only | Read bounded ServiceTracer localization. |
| `query_git_state` | read-only | Read local branch, HEAD, and working-tree state. |
| `request_read_only_inventory` | request-only | Ask an approved observer to run a read-only inventory. |
| `request_read_only_what_if` | request-only | Ask an approved workflow to run Azure What-If. |
| `request_human_review` | request-only | Route the package to an authorized human. |

## ServiceTracer boundary

ServiceTracer is both a HELIX evidence producer and a HELIX consumer.

It contributes deterministic localization, comparison paths, containment status, and explicit uncertainty. HELIX can later provide ServiceTracer with a governed service-context package containing the approved service graph, asset priority, evidence freshness rules, and permitted containment actions.

The bridge currently accepts either the bounded technician-handoff object or the `servicetracer.public-report.v1` envelope. It fails closed unless:

- `investigation_boundary.exact_root_cause_claimed` is `false`; and
- `root_cause.status` is `not_determined_by_servicetracer`.

Unknown fields are dropped rather than forwarded.

## Relationship to HELIX Protocol Kernel

This first increment defines a ContextOS integration profile named `contextos.helix-query-package.v1`. It follows HELIX principles—provenance, bounded authority, completeness, correlation, expiry, and integrity—but it is not yet registered as a canonical artifact type in `helix-protocol-kernel`.

The next protocol increment should register the profile in the kernel, validate package manifests with the kernel implementation, and define ACK/NACK and invalidation handling for an observability or MCP transport.

## Next implementation increments

1. Register the query-package artifact in `helix-protocol-kernel`.
2. Add an observer service that produces signed or hashed environment observations.
3. Reconcile declared Git state with observed Azure state.
4. Expose only the bounded query tools through the ContextOS/HELIX gateway.
5. Add approval-gated capability execution with outcome evidence returned to HELIX memory.
