#!/usr/bin/env python3
"""Build and validate bounded ContextOS query packages for HELIX reasoning nodes.

The bridge is deliberately read-only. It packages declared project state, observed
Git state, evidence-backed environment facts, and a bounded ServiceTracer handoff.
It does not call cloud APIs, execute diagnostics, mutate Git, or grant an AI direct
shell access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "contextos.helix-query-package.v1"
PROJECT_STATE_SCHEMA = "project.active-work.v1"
ENVIRONMENT_STATE_SCHEMA = "project.environment-state.v1"
SERVICETRACER_PUBLIC_SCHEMA = "servicetracer.public-report.v1"

CAPABILITY_CATALOG: dict[str, dict[str, Any]] = {
    "query_project_state": {
        "mode": "read_only",
        "description": "Read declared workflow ownership, scope, and next gates.",
        "human_approval_required": False,
    },
    "query_environment_facts": {
        "mode": "read_only",
        "description": "Read evidence-backed environment facts and freshness metadata.",
        "human_approval_required": False,
    },
    "query_servicetracer_findings": {
        "mode": "read_only",
        "description": "Read bounded ServiceTracer localization and handoff findings.",
        "human_approval_required": False,
    },
    "query_git_state": {
        "mode": "read_only",
        "description": "Read local branch, HEAD, and working-tree state.",
        "human_approval_required": False,
    },
    "request_read_only_inventory": {
        "mode": "request_only",
        "description": "Request a separately governed, read-only infrastructure inventory.",
        "human_approval_required": True,
    },
    "request_read_only_what_if": {
        "mode": "request_only",
        "description": "Request a separately governed, read-only deployment What-If.",
        "human_approval_required": True,
    },
    "request_human_review": {
        "mode": "request_only",
        "description": "Route the evidence package to an authorized human reviewer.",
        "human_approval_required": False,
    },
}


class HelixContextError(Exception):
    """Raised when a bounded context package cannot be built or validated."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bounded_text(value: Any, *, field: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HelixContextError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise HelixContextError(f"{field} exceeds {maximum} characters")
    return normalized


def optional_text(value: Any, *, field: str, maximum: int = 2000) -> str | None:
    if value is None:
        return None
    return bounded_text(value, field=field, maximum=maximum)


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise HelixContextError(f"could not read {label} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise HelixContextError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise HelixContextError(f"{label} must contain a JSON object")
    return value


def _copy_optional_string(
    source: Mapping[str, Any], key: str, *, prefix: str
) -> str | None:
    return optional_text(source.get(key), field=f"{prefix}.{key}")


def sanitize_project_state(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != PROJECT_STATE_SCHEMA:
        raise HelixContextError(f"project state must use {PROJECT_STATE_SCHEMA}")

    trusted = value.get("trusted_baseline")
    if not isinstance(trusted, Mapping):
        raise HelixContextError("project_state.trusted_baseline must be an object")
    increment = trusted.get("last_completed_increment")
    sanitized_increment: dict[str, Any] | None = None
    if increment is not None:
        if not isinstance(increment, Mapping):
            raise HelixContextError("last_completed_increment must be an object")
        sanitized_increment = {
            "pull_request": increment.get("pull_request"),
            "title": _copy_optional_string(
                increment, "title", prefix="last_completed_increment"
            ),
        }

    workstreams = value.get("workstreams")
    if not isinstance(workstreams, list):
        raise HelixContextError("project_state.workstreams must be a list")
    sanitized_workstreams: list[dict[str, Any]] = []
    seen_branches: set[str] = set()
    for index, item in enumerate(workstreams):
        if not isinstance(item, Mapping):
            raise HelixContextError(
                f"project_state.workstreams[{index}] must be an object"
            )
        branch = bounded_text(
            item.get("branch"), field=f"workstreams[{index}].branch", maximum=300
        )
        if branch in seen_branches:
            raise HelixContextError(f"duplicate workstream branch ownership: {branch}")
        seen_branches.add(branch)
        sanitized_workstreams.append(
            {
                "workstream_id": bounded_text(
                    item.get("workstream_id"),
                    field=f"workstreams[{index}].workstream_id",
                    maximum=200,
                ),
                "branch": branch,
                "pull_request": item.get("pull_request"),
                "write_owner": bounded_text(
                    item.get("write_owner"),
                    field=f"workstreams[{index}].write_owner",
                    maximum=200,
                ),
                "status": bounded_text(
                    item.get("status"),
                    field=f"workstreams[{index}].status",
                    maximum=100,
                ),
                "scope": bounded_text(
                    item.get("scope"), field=f"workstreams[{index}].scope"
                ),
                "review_mode_for_other_conversations": _copy_optional_string(
                    item,
                    "review_mode_for_other_conversations",
                    prefix=f"workstreams[{index}]",
                ),
                "next_gate": _copy_optional_string(
                    item, "next_gate", prefix=f"workstreams[{index}]"
                ),
            }
        )

    open_prs = value.get("known_open_pull_requests", [])
    if not isinstance(open_prs, list):
        raise HelixContextError(
            "project_state.known_open_pull_requests must be a list"
        )
    sanitized_open_prs = []
    for index, item in enumerate(open_prs):
        if not isinstance(item, Mapping):
            raise HelixContextError(
                f"known_open_pull_requests[{index}] must be an object"
            )
        sanitized_open_prs.append(
            {
                "pull_request": item.get("pull_request"),
                "title": _copy_optional_string(
                    item, "title", prefix=f"known_open_pull_requests[{index}]"
                ),
                "status": _copy_optional_string(
                    item, "status", prefix=f"known_open_pull_requests[{index}]"
                ),
                "action": _copy_optional_string(
                    item, "action", prefix=f"known_open_pull_requests[{index}]"
                ),
            }
        )

    return {
        "schema_version": PROJECT_STATE_SCHEMA,
        "project": bounded_text(value.get("project"), field="project_state.project"),
        "updated_on": bounded_text(
            value.get("updated_on"), field="project_state.updated_on", maximum=50
        ),
        "trusted_baseline": {
            "branch": bounded_text(
                trusted.get("branch"), field="trusted_baseline.branch", maximum=300
            ),
            "commit": bounded_text(
                trusted.get("commit"), field="trusted_baseline.commit", maximum=100
            ),
            "last_completed_increment": sanitized_increment,
        },
        "workstreams": sanitized_workstreams,
        "known_open_pull_requests": sanitized_open_prs,
    }


def sanitize_environment_state(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != ENVIRONMENT_STATE_SCHEMA:
        raise HelixContextError(
            f"environment state must use {ENVIRONMENT_STATE_SCHEMA}"
        )
    facts = value.get("facts")
    if not isinstance(facts, list):
        raise HelixContextError("environment_state.facts must be a list")
    sanitized_facts = []
    seen_ids: set[str] = set()
    for index, item in enumerate(facts):
        if not isinstance(item, Mapping):
            raise HelixContextError(
                f"environment_state.facts[{index}] must be an object"
            )
        fact_id = bounded_text(
            item.get("fact_id"), field=f"facts[{index}].fact_id", maximum=200
        )
        if fact_id in seen_ids:
            raise HelixContextError(f"duplicate environment fact id: {fact_id}")
        seen_ids.add(fact_id)
        sanitized_facts.append(
            {
                "fact_id": fact_id,
                "value": item.get("value"),
                "status": bounded_text(
                    item.get("status"), field=f"facts[{index}].status", maximum=200
                ),
                "last_observed_on": bounded_text(
                    item.get("last_observed_on"),
                    field=f"facts[{index}].last_observed_on",
                    maximum=100,
                ),
                "source": bounded_text(
                    item.get("source"), field=f"facts[{index}].source"
                ),
                "notes": _copy_optional_string(
                    item, "notes", prefix=f"facts[{index}]"
                ),
            }
        )
    return {
        "schema_version": ENVIRONMENT_STATE_SCHEMA,
        "project": bounded_text(
            value.get("project"), field="environment_state.project"
        ),
        "updated_on": bounded_text(
            value.get("updated_on"),
            field="environment_state.updated_on",
            maximum=50,
        ),
        "facts": sanitized_facts,
    }


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HelixContextError(f"{field} must be an object")
    return value


def sanitize_servicetracer_report(value: Mapping[str, Any]) -> dict[str, Any]:
    report = value
    if value.get("schema_version") == SERVICETRACER_PUBLIC_SCHEMA:
        report = _mapping(
            value.get("report"), field="servicetracer public envelope.report"
        )

    boundary = _mapping(
        report.get("investigation_boundary"), field="investigation_boundary"
    )
    if boundary.get("exact_root_cause_claimed") is not False:
        raise HelixContextError(
            "ServiceTracer report must explicitly state exact_root_cause_claimed=false"
        )
    root_cause = _mapping(report.get("root_cause"), field="root_cause")
    if root_cause.get("status") != "not_determined_by_servicetracer":
        raise HelixContextError(
            "ServiceTracer report exceeds the bounded root-cause contract"
        )

    incident = _mapping(report.get("incident"), field="incident")
    load_balancer = _mapping(report.get("load_balancer"), field="load_balancer")
    localization = _mapping(report.get("localization"), field="localization")

    workflow = report.get("technician_workflow", [])
    if not isinstance(workflow, list):
        raise HelixContextError("technician_workflow must be a list")
    sanitized_workflow = []
    for index, step in enumerate(workflow):
        step_map = _mapping(step, field=f"technician_workflow[{index}]")
        sanitized_workflow.append(
            {
                "step_id": bounded_text(
                    step_map.get("step_id"),
                    field=f"technician_workflow[{index}].step_id",
                ),
                "owner": bounded_text(
                    step_map.get("owner"),
                    field=f"technician_workflow[{index}].owner",
                ),
                "status": bounded_text(
                    step_map.get("status"),
                    field=f"technician_workflow[{index}].status",
                ),
                "action": bounded_text(
                    step_map.get("action"),
                    field=f"technician_workflow[{index}].action",
                ),
                "purpose": bounded_text(
                    step_map.get("purpose"),
                    field=f"technician_workflow[{index}].purpose",
                ),
                "success_criteria": bounded_text(
                    step_map.get("success_criteria"),
                    field=f"technician_workflow[{index}].success_criteria",
                ),
            }
        )

    return {
        "scenario": bounded_text(
            report.get("scenario"), field="servicetracer.scenario"
        ),
        "status": bounded_text(report.get("status"), field="servicetracer.status"),
        "incident": {
            "classification": incident.get("classification"),
            "attempts": incident.get("attempts"),
            "successful_attempts": incident.get("successful_attempts"),
            "failed_attempts": incident.get("failed_attempts"),
        },
        "load_balancer": {
            "status": load_balancer.get("status"),
            "probe_name": load_balancer.get("probe_name"),
            "probe_scope": load_balancer.get("probe_scope"),
            "backend_states": load_balancer.get("backend_states"),
            "probe_gap_detected": load_balancer.get("probe_gap_detected"),
        },
        "localization": {
            "suspect_backend": localization.get("suspect_backend"),
            "healthy_comparison_backend": localization.get(
                "healthy_comparison_backend"
            ),
            "suspect_probe_status": localization.get("suspect_probe_status"),
            "backend_failure_rates": localization.get("backend_failure_rates"),
        },
        "service_tracer_finding": bounded_text(
            report.get("service_tracer_finding"),
            field="servicetracer.service_tracer_finding",
        ),
        "investigation_boundary": {
            "service_tracer_stops_at": boundary.get("service_tracer_stops_at"),
            "exact_root_cause_claimed": False,
            "statement": boundary.get("statement"),
        },
        "root_cause": {
            "status": "not_determined_by_servicetracer",
            "owner": root_cause.get("owner"),
        },
        "temporary_service_status": report.get("temporary_service_status"),
        "technician_workflow": sanitized_workflow,
    }


def run_git(repo: Path, args: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise HelixContextError(
            f"git {' '.join(args)} failed: "
            f"{completed.stderr.strip() or 'no error output'}"
        )
    return completed.stdout.strip()


def observe_git_state(repo: Path) -> dict[str, Any]:
    root = Path(run_git(repo, ["rev-parse", "--show-toplevel"]))
    status = run_git(root, ["status", "--porcelain=v1"])
    branch = run_git(root, ["branch", "--show-current"]) or "(detached HEAD)"
    return {
        "repository_name": root.name,
        "repository_root": str(root),
        "branch": branch,
        "head": run_git(root, ["rev-parse", "HEAD"]),
        "dirty_working_tree": bool(status),
        "changed_paths": [
            line[3:] if len(line) >= 4 else line
            for line in status.splitlines()
            if line
        ],
    }


def capability_grants(names: Sequence[str]) -> list[dict[str, Any]]:
    if not names:
        raise HelixContextError("at least one bounded capability is required")
    grants = []
    for name in dict.fromkeys(names):
        if name not in CAPABILITY_CATALOG:
            raise HelixContextError(f"unsupported capability: {name}")
        grants.append({"capability": name, **CAPABILITY_CATALOG[name]})
    return grants


def provenance_record(path: Path, artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "path": str(path),
        "sha256": file_sha256(path),
    }


def build_query_package(
    *,
    repo: Path,
    query: str,
    capabilities: Sequence[str],
    project_state_path: Path | None = None,
    environment_state_path: Path | None = None,
    servicetracer_report_path: Path | None = None,
    ttl_minutes: int = 60,
    correlation_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if ttl_minutes < 1 or ttl_minutes > 1440:
        raise HelixContextError("ttl_minutes must be between 1 and 1440")
    query_text = bounded_text(query, field="query", maximum=1000)
    observed_at = now or utc_now()
    git_state = observe_git_state(repo)
    provenance: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "declared_project_state": None,
        "observed_environment_facts": None,
        "servicetracer_finding": None,
        "observed_git_state": git_state,
    }
    missing_optional_sources: list[str] = []

    if project_state_path is not None:
        evidence["declared_project_state"] = sanitize_project_state(
            load_json_object(project_state_path, label="project state")
        )
        provenance.append(
            provenance_record(project_state_path, "declared_project_state")
        )
    else:
        missing_optional_sources.append("declared_project_state")

    if environment_state_path is not None:
        evidence["observed_environment_facts"] = sanitize_environment_state(
            load_json_object(environment_state_path, label="environment state")
        )
        provenance.append(
            provenance_record(environment_state_path, "observed_environment_facts")
        )
    else:
        missing_optional_sources.append("observed_environment_facts")

    if servicetracer_report_path is not None:
        evidence["servicetracer_finding"] = sanitize_servicetracer_report(
            load_json_object(servicetracer_report_path, label="ServiceTracer report")
        )
        provenance.append(
            provenance_record(servicetracer_report_path, "servicetracer_finding")
        )
    else:
        missing_optional_sources.append("servicetracer_finding")

    package: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package_id": f"ctxhelix-{uuid.uuid4()}",
        "correlation_id": correlation_id or f"corr-{uuid.uuid4()}",
        "generated_at": iso_z(observed_at),
        "expires_at": iso_z(observed_at + timedelta(minutes=ttl_minutes)),
        "sequence": {"number": 1, "total": 1, "complete": True},
        "query": {
            "text": query_text,
            "answer_boundary": (
                "Evidence-bound summary; disclose missing, stale, or conflicting "
                "evidence."
            ),
        },
        "subject": {
            "project": (
                evidence["declared_project_state"]["project"]
                if evidence["declared_project_state"] is not None
                else git_state["repository_name"]
            ),
            "repository": git_state["repository_name"],
            "branch": git_state["branch"],
            "head": git_state["head"],
        },
        "authority": {
            "authority_state": "candidate_context_only",
            "mutation_authority": False,
            "may_claim_authorized_decision": False,
            "state_change_requires_separate_human_approval": True,
            "capability_grants": capability_grants(capabilities),
        },
        "evidence": evidence,
        "completeness": {
            "required_sources_present": ["observed_git_state"],
            "missing_optional_sources": missing_optional_sources,
            "package_complete_for_bounded_query": True,
        },
        "provenance": provenance,
        "notices": [
            "This package is context, not an authorized decision.",
            "Capabilities describe bounded requests; they do not execute actions.",
            "Unknown input fields are dropped by allowlist sanitizers.",
        ],
    }
    package["integrity"] = {
        "algorithm": "sha256",
        "canonical_json_sha256": canonical_sha256(package),
    }
    return package


def validate_query_package(
    package: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    if package.get("schema_version") != SCHEMA_VERSION:
        raise HelixContextError(f"package must use {SCHEMA_VERSION}")
    authority = _mapping(package.get("authority"), field="authority")
    if authority.get("mutation_authority") is not False:
        raise HelixContextError("HELIX query package must not grant mutation authority")
    if authority.get("may_claim_authorized_decision") is not False:
        raise HelixContextError(
            "HELIX query package must not claim an authorized decision"
        )
    grants = authority.get("capability_grants")
    if not isinstance(grants, list) or not grants:
        raise HelixContextError(
            "authority.capability_grants must be a non-empty list"
        )
    for index, grant in enumerate(grants):
        grant_map = _mapping(grant, field=f"capability_grants[{index}]")
        if grant_map.get("capability") not in CAPABILITY_CATALOG:
            raise HelixContextError(
                f"unsupported packaged capability: {grant_map.get('capability')}"
            )

    evidence = _mapping(package.get("evidence"), field="evidence")
    servicetracer = evidence.get("servicetracer_finding")
    if servicetracer is not None:
        sanitize_servicetracer_report(
            _mapping(servicetracer, field="evidence.servicetracer_finding")
        )

    integrity = _mapping(package.get("integrity"), field="integrity")
    expected = integrity.get("canonical_json_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise HelixContextError("integrity hash is missing or malformed")
    unhashed = dict(package)
    unhashed.pop("integrity", None)
    actual = canonical_sha256(unhashed)
    if actual != expected:
        raise HelixContextError("package integrity hash mismatch")

    current = now or utc_now()
    try:
        expires = datetime.fromisoformat(
            str(package.get("expires_at")).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise HelixContextError(
            "expires_at is not a valid ISO-8601 timestamp"
        ) from error
    if current > expires.astimezone(timezone.utc):
        raise HelixContextError("package has expired")


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextos-helix",
        description=(
            "Build and validate bounded ContextOS query packages for HELIX."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="build a bounded HELIX query package"
    )
    build.add_argument("--repo", type=Path, default=Path.cwd())
    build.add_argument("--query", required=True)
    build.add_argument(
        "--capability", action="append", dest="capabilities", required=True
    )
    build.add_argument("--project-state", type=Path)
    build.add_argument("--environment-state", type=Path)
    build.add_argument("--servicetracer-report", type=Path)
    build.add_argument("--ttl-minutes", type=int, default=60)
    build.add_argument("--correlation-id")
    build.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser(
        "validate", help="validate a HELIX query package"
    )
    validate.add_argument("package", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            package = build_query_package(
                repo=args.repo,
                query=args.query,
                capabilities=args.capabilities,
                project_state_path=args.project_state,
                environment_state_path=args.environment_state,
                servicetracer_report_path=args.servicetracer_report,
                ttl_minutes=args.ttl_minutes,
                correlation_id=args.correlation_id,
            )
            atomic_write_json(args.output, package)
            print(f"HELIX query package written: {args.output}")
            print(f"Package ID: {package['package_id']}")
            print("Mutation authority: false")
            return 0
        if args.command == "validate":
            package = load_json_object(args.package, label="HELIX query package")
            validate_query_package(package)
            print("HELIX query package: VALID")
            return 0
    except HelixContextError as error:
        print(f"contextos-helix: ERROR: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
