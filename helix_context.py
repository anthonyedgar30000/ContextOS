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
import math
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "contextos.helix-query-package.v1"
PROJECT_STATE_SCHEMAS = {"project.active-work.v1", "project.active-work.v2"}
PROJECT_PROJECTION_VERSION = "contextos.project-state-projection.v1"
ENVIRONMENT_STATE_SCHEMA = "project.environment-state.v1"
SERVICETRACER_PUBLIC_SCHEMA = "servicetracer.public-report.v1"

MAX_JSON_DEPTH = 5
MAX_JSON_ITEMS = 100
MAX_JSON_BYTES = 32768
MAX_FACTS = 200
MAX_WORKSTREAMS = 50
MAX_CHANGED_PATHS = 500

SENSITIVE_KEY_SEGMENTS = {
    "accesskey",
    "apikey",
    "authorization",
    "bearer",
    "clientsecret",
    "connectionstring",
    "credential",
    "credentials",
    "password",
    "privatekey",
    "sas",
    "secret",
    "token",
}

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

CAPABILITY_SOURCE_REQUIREMENTS = {
    "query_project_state": "declared_project_state",
    "query_environment_facts": "observed_environment_facts",
    "query_servicetracer_findings": "servicetracer_finding",
    "query_git_state": "observed_git_state",
}

EVIDENCE_KEYS = (
    "declared_project_state",
    "observed_environment_facts",
    "servicetracer_finding",
    "observed_git_state",
)


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
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise HelixContextError(f"value is not canonical JSON: {error}") from error


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


def _optional_positive_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HelixContextError(f"{field} must be a positive integer or null")
    return value


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HelixContextError(f"{field} must be a non-negative integer")
    return value


def _reject_json_constant(value: str) -> None:
    raise HelixContextError(f"non-finite JSON number is not allowed: {value}")


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except OSError as error:
        raise HelixContextError(f"could not read {label} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise HelixContextError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise HelixContextError(f"{label} must contain a JSON object")
    return value


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return any(segment in normalized for segment in SENSITIVE_KEY_SEGMENTS)


SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"^Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"^sk-[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{20,}$"),
    re.compile(r"^github_pat_[A-Za-z0-9_]{20,}$"),
    re.compile(r"^AKIA[0-9A-Z]{16}$"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _contains_sensitive_value(value: str) -> bool:
    if any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
        return True
    lowered = value.lower()
    return "sig=" in lowered and ("sv=" in lowered or "se=" in lowered)


def _sanitize_json_value(
    value: Any,
    *,
    field: str,
    depth: int,
    maximum_depth: int,
    maximum_items: int,
    maximum_string: int,
) -> Any:
    if depth > maximum_depth:
        raise HelixContextError(f"{field} exceeds maximum JSON depth {maximum_depth}")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HelixContextError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, str):
        if _contains_sensitive_value(value):
            raise HelixContextError(f"{field} contains a credential-like value")
        if len(value) > maximum_string:
            raise HelixContextError(
                f"{field} string exceeds {maximum_string} characters"
            )
        return value
    if isinstance(value, list):
        if len(value) > maximum_items:
            raise HelixContextError(f"{field} exceeds {maximum_items} list items")
        return [
            _sanitize_json_value(
                item,
                field=f"{field}[{index}]",
                depth=depth + 1,
                maximum_depth=maximum_depth,
                maximum_items=maximum_items,
                maximum_string=maximum_string,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        if len(value) > maximum_items:
            raise HelixContextError(f"{field} exceeds {maximum_items} object fields")
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise HelixContextError(f"{field} object keys must be non-empty strings")
            if len(key) > 200:
                raise HelixContextError(f"{field}.{key[:20]} key exceeds 200 characters")
            if _is_sensitive_key(key):
                raise HelixContextError(f"{field}.{key} contains a sensitive field name")
            sanitized[key] = _sanitize_json_value(
                item,
                field=f"{field}.{key}",
                depth=depth + 1,
                maximum_depth=maximum_depth,
                maximum_items=maximum_items,
                maximum_string=maximum_string,
            )
        return sanitized
    raise HelixContextError(f"{field} contains unsupported JSON type {type(value).__name__}")


def bounded_json(
    value: Any,
    *,
    field: str,
    maximum_depth: int = MAX_JSON_DEPTH,
    maximum_items: int = MAX_JSON_ITEMS,
    maximum_string: int = 2000,
    maximum_bytes: int = MAX_JSON_BYTES,
) -> Any:
    sanitized = _sanitize_json_value(
        value,
        field=field,
        depth=0,
        maximum_depth=maximum_depth,
        maximum_items=maximum_items,
        maximum_string=maximum_string,
    )
    if len(canonical_json(sanitized).encode("utf-8")) > maximum_bytes:
        raise HelixContextError(f"{field} exceeds {maximum_bytes} canonical JSON bytes")
    return sanitized


def _string_list(
    value: Any,
    *,
    field: str,
    maximum_items: int = 100,
    maximum_string: int = 1000,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum_items:
        raise HelixContextError(f"{field} must be a list of at most {maximum_items} strings")
    return [
        bounded_text(item, field=f"{field}[{index}]", maximum=maximum_string)
        for index, item in enumerate(value)
    ]


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HelixContextError(f"{field} must be an object")
    return value


def _sanitize_baseline(value: Mapping[str, Any], *, schema: str) -> dict[str, Any]:
    if schema == "project.active-work.v1":
        trusted = _mapping(value.get("trusted_baseline"), field="trusted_baseline")
        increment = trusted.get("last_completed_increment")
        increment_map = (
            _mapping(increment, field="trusted_baseline.last_completed_increment")
            if increment is not None
            else {}
        )
        return {
            "branch": bounded_text(
                trusted.get("branch"), field="trusted_baseline.branch", maximum=300
            ),
            "commit": optional_text(
                trusted.get("commit") or trusted.get("last_observed_commit"),
                field="trusted_baseline.commit",
                maximum=100,
            ),
            "resolution": optional_text(
                trusted.get("resolution"),
                field="trusted_baseline.resolution",
                maximum=300,
            ),
            "pull_request": _optional_positive_int(
                increment_map.get("pull_request"),
                field="trusted_baseline.last_completed_increment.pull_request",
            ),
            "title": optional_text(
                increment_map.get("title"),
                field="trusted_baseline.last_completed_increment.title",
            ),
        }

    baseline = _mapping(
        value.get("last_substantive_baseline"), field="last_substantive_baseline"
    )
    return {
        "branch": bounded_text(
            baseline.get("branch"), field="last_substantive_baseline.branch", maximum=300
        ),
        "commit": bounded_text(
            baseline.get("commit"), field="last_substantive_baseline.commit", maximum=100
        ),
        "resolution": None,
        "pull_request": _optional_positive_int(
            baseline.get("pull_request"),
            field="last_substantive_baseline.pull_request",
        ),
        "title": optional_text(
            baseline.get("title"), field="last_substantive_baseline.title"
        ),
        "qualification": optional_text(
            baseline.get("qualification"),
            field="last_substantive_baseline.qualification",
        ),
        "claim_boundary": optional_text(
            baseline.get("claim_boundary"),
            field="last_substantive_baseline.claim_boundary",
            maximum=4000,
        ),
    }


def _sanitize_workstream(item: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    prefix = f"workstreams[{index}]"
    objective = item.get("objective") if item.get("objective") is not None else item.get("scope")
    status = item.get("status") or item.get("state_semantics") or "declared_change"
    verification = item.get("verification_criteria")
    if verification is None:
        verification = item.get("acceptance_criteria")
    return {
        "workstream_id": bounded_text(
            item.get("workstream_id") or item.get("change_id"),
            field=f"{prefix}.workstream_id",
            maximum=200,
        ),
        "branch": bounded_text(item.get("branch"), field=f"{prefix}.branch", maximum=300),
        "pull_request": _optional_positive_int(
            item.get("pull_request"), field=f"{prefix}.pull_request"
        ),
        "write_owner": optional_text(
            item.get("write_owner"), field=f"{prefix}.write_owner", maximum=300
        ),
        "status": bounded_text(status, field=f"{prefix}.status", maximum=150),
        "objective": bounded_text(objective, field=f"{prefix}.objective", maximum=4000),
        "authority": optional_text(
            item.get("authority"), field=f"{prefix}.authority", maximum=300
        ),
        "state_semantics": optional_text(
            item.get("state_semantics"), field=f"{prefix}.state_semantics", maximum=200
        ),
        "permitted_paths": _string_list(
            item.get("permitted_paths"), field=f"{prefix}.permitted_paths"
        ),
        "protected_paths": _string_list(
            item.get("protected_paths"), field=f"{prefix}.protected_paths"
        ),
        "capability_boundary": (
            bounded_json(
                item.get("capability_boundary"),
                field=f"{prefix}.capability_boundary",
                maximum_depth=3,
                maximum_items=50,
                maximum_bytes=12000,
            )
            if item.get("capability_boundary") is not None
            else None
        ),
        "verification_criteria": _string_list(
            verification,
            field=f"{prefix}.verification_criteria",
            maximum_items=100,
            maximum_string=2000,
        ),
        "review_mode_for_other_conversations": optional_text(
            item.get("review_mode_for_other_conversations"),
            field=f"{prefix}.review_mode_for_other_conversations",
            maximum=300,
        ),
        "next_gate": optional_text(
            item.get("next_gate"), field=f"{prefix}.next_gate", maximum=4000
        ),
        "authority_expiry_condition": optional_text(
            item.get("authority_expiry_condition"),
            field=f"{prefix}.authority_expiry_condition",
            maximum=2000,
        ),
        "failure_behavior": optional_text(
            item.get("failure_behavior"),
            field=f"{prefix}.failure_behavior",
            maximum=4000,
        ),
        "rollback": optional_text(
            item.get("rollback"), field=f"{prefix}.rollback", maximum=4000
        ),
    }


def _sanitize_repository_observation(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    observation = _mapping(value, field="repository_observation")
    return {
        "observed_on": bounded_text(
            observation.get("observed_on"),
            field="repository_observation.observed_on",
            maximum=100,
        ),
        "source": bounded_text(
            observation.get("source"),
            field="repository_observation.source",
            maximum=300,
        ),
        "main_head": bounded_text(
            observation.get("main_head"),
            field="repository_observation.main_head",
            maximum=100,
        ),
        "head_semantics": optional_text(
            observation.get("head_semantics"),
            field="repository_observation.head_semantics",
            maximum=2000,
        ),
        "open_pull_requests": bounded_json(
            observation.get("open_pull_requests", []),
            field="repository_observation.open_pull_requests",
            maximum_depth=3,
            maximum_items=100,
            maximum_bytes=12000,
        ),
        "claim_boundary": optional_text(
            observation.get("claim_boundary"),
            field="repository_observation.claim_boundary",
            maximum=3000,
        ),
    }


def _sanitize_authority_grants(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 50:
        raise HelixContextError("bounded_authority_grants must be a list of at most 50 entries")
    grants: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        grant = _mapping(item, field=f"bounded_authority_grants[{index}]")
        prefix = f"bounded_authority_grants[{index}]"
        grants.append(
            {
                "grant_id": bounded_text(
                    grant.get("grant_id"), field=f"{prefix}.grant_id", maximum=200
                ),
                "workflow_path": optional_text(
                    grant.get("workflow_path"), field=f"{prefix}.workflow_path", maximum=500
                ),
                "operation": bounded_text(
                    grant.get("operation"), field=f"{prefix}.operation", maximum=200
                ),
                "active_workflow_authorized": grant.get("active_workflow_authorized") is True,
                "dispatch_authorized": grant.get("dispatch_authorized") is True,
                "azure_authentication_authorized": grant.get("azure_authentication_authorized") is True,
                "azure_mutations_authorized": grant.get("azure_mutations_authorized") is True,
                "authorized_by": optional_text(
                    grant.get("authorized_by"), field=f"{prefix}.authorized_by", maximum=300
                ),
                "authorized_on": optional_text(
                    grant.get("authorized_on"), field=f"{prefix}.authorized_on", maximum=100
                ),
                "protected_environment": optional_text(
                    grant.get("protected_environment"),
                    field=f"{prefix}.protected_environment",
                    maximum=300,
                ),
                "required_commit_semantics": optional_text(
                    grant.get("required_commit_semantics"),
                    field=f"{prefix}.required_commit_semantics",
                    maximum=1000,
                ),
                "required_confirmation": optional_text(
                    grant.get("required_confirmation"),
                    field=f"{prefix}.required_confirmation",
                    maximum=1000,
                ),
                "permitted_operations": _string_list(
                    grant.get("permitted_azure_operations"),
                    field=f"{prefix}.permitted_azure_operations",
                ),
                "claim_boundary": optional_text(
                    grant.get("claim_boundary"),
                    field=f"{prefix}.claim_boundary",
                    maximum=3000,
                ),
            }
        )
    return grants


def sanitize_project_state(value: Mapping[str, Any]) -> dict[str, Any]:
    schema = value.get("schema_version")
    if schema not in PROJECT_STATE_SCHEMAS:
        raise HelixContextError(
            "project state must use project.active-work.v1 or project.active-work.v2"
        )

    if schema == "project.active-work.v1":
        raw_workstreams = value.get("workstreams")
        if not isinstance(raw_workstreams, list):
            raise HelixContextError("project_state.workstreams must be a list")
        repository_observation = None
        authority_grants: list[dict[str, Any]] = []
        authority_defaults = None
    else:
        raw_workstreams = []
        authored = value.get("authored_change")
        if authored is not None:
            raw_workstreams.append(_mapping(authored, field="authored_change"))
        repository_observation = _sanitize_repository_observation(
            value.get("repository_observation")
        )
        authority_grants = _sanitize_authority_grants(
            value.get("bounded_authority_grants")
        )
        authority_defaults = (
            bounded_json(
                value.get("authority_defaults"),
                field="authority_defaults",
                maximum_depth=3,
                maximum_items=50,
                maximum_bytes=12000,
            )
            if value.get("authority_defaults") is not None
            else None
        )

    if len(raw_workstreams) > MAX_WORKSTREAMS:
        raise HelixContextError(
            f"project_state workstreams exceed {MAX_WORKSTREAMS} entries"
        )
    sanitized_workstreams: list[dict[str, Any]] = []
    seen_branches: set[str] = set()
    for index, item in enumerate(raw_workstreams):
        workstream = _sanitize_workstream(
            _mapping(item, field=f"workstreams[{index}]"), index=index
        )
        if workstream["branch"] in seen_branches:
            raise HelixContextError(
                f"duplicate workstream branch ownership: {workstream['branch']}"
            )
        seen_branches.add(workstream["branch"])
        sanitized_workstreams.append(workstream)

    projection = {
        "schema_version": schema,
        "projection_version": PROJECT_PROJECTION_VERSION,
        "project": bounded_text(value.get("project"), field="project_state.project"),
        "updated_on": bounded_text(
            value.get("updated_on"), field="project_state.updated_on", maximum=100
        ),
        "baseline": _sanitize_baseline(value, schema=schema),
        "workstreams": sanitized_workstreams,
        "repository_observation": repository_observation,
        "bounded_authority_grants": authority_grants,
        "authority_defaults": authority_defaults,
    }
    return bounded_json(
        projection,
        field="project_state_projection",
        maximum_depth=6,
        maximum_items=200,
        maximum_bytes=100000,
    )


def sanitize_environment_state(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != ENVIRONMENT_STATE_SCHEMA:
        raise HelixContextError(
            f"environment state must use {ENVIRONMENT_STATE_SCHEMA}"
        )
    facts = value.get("facts")
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise HelixContextError(
            f"environment_state.facts must be a list of at most {MAX_FACTS} items"
        )
    sanitized_facts = []
    seen_ids: set[str] = set()
    for index, item in enumerate(facts):
        fact = _mapping(item, field=f"environment_state.facts[{index}]")
        fact_id = bounded_text(
            fact.get("fact_id"), field=f"facts[{index}].fact_id", maximum=200
        )
        if fact_id in seen_ids:
            raise HelixContextError(f"duplicate environment fact id: {fact_id}")
        seen_ids.add(fact_id)
        sanitized_facts.append(
            {
                "fact_id": fact_id,
                "value": bounded_json(
                    fact.get("value"),
                    field=f"facts[{index}].value",
                    maximum_depth=4,
                    maximum_items=100,
                    maximum_bytes=16000,
                ),
                "status": bounded_text(
                    fact.get("status"), field=f"facts[{index}].status", maximum=200
                ),
                "last_observed_on": bounded_text(
                    fact.get("last_observed_on"),
                    field=f"facts[{index}].last_observed_on",
                    maximum=100,
                ),
                "source": bounded_text(
                    fact.get("source"), field=f"facts[{index}].source", maximum=3000
                ),
                "notes": optional_text(
                    fact.get("notes"), field=f"facts[{index}].notes", maximum=4000
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
            maximum=100,
        ),
        "facts": sanitized_facts,
    }


def _sanitize_backend_states(value: Any) -> dict[str, Any]:
    states = _mapping(value, field="load_balancer.backend_states")
    if len(states) > 100:
        raise HelixContextError("load_balancer.backend_states exceeds 100 backends")
    sanitized: dict[str, Any] = {}
    for backend, state in states.items():
        name = bounded_text(backend, field="load_balancer.backend_states key", maximum=300)
        if _is_sensitive_key(name):
            raise HelixContextError(
                f"load_balancer.backend_states.{name} contains a sensitive field name"
            )
        sanitized[name] = bounded_json(
            state,
            field=f"load_balancer.backend_states.{name}",
            maximum_depth=3,
            maximum_items=50,
            maximum_bytes=8000,
        )
    return sanitized


def _sanitize_failure_rates(value: Any) -> dict[str, float]:
    rates = _mapping(value, field="localization.backend_failure_rates")
    if len(rates) > 100:
        raise HelixContextError("localization.backend_failure_rates exceeds 100 backends")
    sanitized: dict[str, float] = {}
    for backend, rate in rates.items():
        name = bounded_text(backend, field="backend_failure_rates key", maximum=300)
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise HelixContextError(
                f"localization.backend_failure_rates.{name} must be numeric"
            )
        number = float(rate)
        if not math.isfinite(number) or number < 0 or number > 1:
            raise HelixContextError(
                f"localization.backend_failure_rates.{name} must be between 0 and 1"
            )
        sanitized[name] = number
    return sanitized


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
    if not isinstance(workflow, list) or len(workflow) > 100:
        raise HelixContextError("technician_workflow must be a list of at most 100 steps")
    sanitized_workflow = []
    for index, step in enumerate(workflow):
        step_map = _mapping(step, field=f"technician_workflow[{index}]")
        sanitized_workflow.append(
            {
                "step_id": bounded_text(
                    step_map.get("step_id"),
                    field=f"technician_workflow[{index}].step_id",
                    maximum=300,
                ),
                "owner": bounded_text(
                    step_map.get("owner"),
                    field=f"technician_workflow[{index}].owner",
                    maximum=300,
                ),
                "status": bounded_text(
                    step_map.get("status"),
                    field=f"technician_workflow[{index}].status",
                    maximum=300,
                ),
                "action": bounded_text(
                    step_map.get("action"),
                    field=f"technician_workflow[{index}].action",
                    maximum=4000,
                ),
                "purpose": bounded_text(
                    step_map.get("purpose"),
                    field=f"technician_workflow[{index}].purpose",
                    maximum=4000,
                ),
                "success_criteria": bounded_text(
                    step_map.get("success_criteria"),
                    field=f"technician_workflow[{index}].success_criteria",
                    maximum=4000,
                ),
            }
        )

    sanitized = {
        "scenario": bounded_text(
            report.get("scenario"), field="servicetracer.scenario", maximum=500
        ),
        "status": bounded_text(
            report.get("status"), field="servicetracer.status", maximum=500
        ),
        "incident": {
            "classification": bounded_text(
                incident.get("classification"),
                field="incident.classification",
                maximum=500,
            ),
            "attempts": _non_negative_int(incident.get("attempts"), field="incident.attempts"),
            "successful_attempts": _non_negative_int(
                incident.get("successful_attempts"), field="incident.successful_attempts"
            ),
            "failed_attempts": _non_negative_int(
                incident.get("failed_attempts"), field="incident.failed_attempts"
            ),
        },
        "load_balancer": {
            "status": bounded_text(
                load_balancer.get("status"), field="load_balancer.status", maximum=500
            ),
            "probe_name": bounded_text(
                load_balancer.get("probe_name"),
                field="load_balancer.probe_name",
                maximum=500,
            ),
            "probe_scope": bounded_text(
                load_balancer.get("probe_scope"),
                field="load_balancer.probe_scope",
                maximum=500,
            ),
            "backend_states": _sanitize_backend_states(
                load_balancer.get("backend_states")
            ),
            "probe_gap_detected": load_balancer.get("probe_gap_detected") is True,
        },
        "localization": {
            "suspect_backend": bounded_text(
                localization.get("suspect_backend"),
                field="localization.suspect_backend",
                maximum=500,
            ),
            "healthy_comparison_backend": bounded_text(
                localization.get("healthy_comparison_backend"),
                field="localization.healthy_comparison_backend",
                maximum=500,
            ),
            "suspect_probe_status": bounded_text(
                localization.get("suspect_probe_status"),
                field="localization.suspect_probe_status",
                maximum=500,
            ),
            "backend_failure_rates": _sanitize_failure_rates(
                localization.get("backend_failure_rates")
            ),
        },
        "service_tracer_finding": bounded_text(
            report.get("service_tracer_finding"),
            field="servicetracer.service_tracer_finding",
            maximum=5000,
        ),
        "investigation_boundary": {
            "service_tracer_stops_at": bounded_text(
                boundary.get("service_tracer_stops_at"),
                field="investigation_boundary.service_tracer_stops_at",
                maximum=500,
            ),
            "exact_root_cause_claimed": False,
            "statement": bounded_text(
                boundary.get("statement"),
                field="investigation_boundary.statement",
                maximum=5000,
            ),
        },
        "root_cause": {
            "status": "not_determined_by_servicetracer",
            "owner": bounded_text(
                root_cause.get("owner"), field="root_cause.owner", maximum=500
            ),
        },
        "temporary_service_status": bounded_text(
            report.get("temporary_service_status"),
            field="temporary_service_status",
            maximum=1000,
        ),
        "technician_workflow": sanitized_workflow,
    }
    return bounded_json(
        sanitized,
        field="servicetracer_projection",
        maximum_depth=6,
        maximum_items=200,
        maximum_bytes=100000,
    )


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
    changed_paths = [
        line[3:] if len(line) >= 4 else line
        for line in status.splitlines()
        if line
    ]
    if len(changed_paths) > MAX_CHANGED_PATHS:
        raise HelixContextError(
            f"observed Git state exceeds {MAX_CHANGED_PATHS} changed paths"
        )
    return {
        "repository_name": root.name,
        "branch": run_git(root, ["branch", "--show-current"]) or "(detached HEAD)",
        "head": run_git(root, ["rev-parse", "HEAD"]),
        "dirty_working_tree": bool(status),
        "changed_paths": [
            bounded_text(path, field=f"changed_paths[{index}]", maximum=1000)
            for index, path in enumerate(changed_paths)
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


def _completeness_for(
    capability_names: Sequence[str], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    required_sources = sorted(
        {
            CAPABILITY_SOURCE_REQUIREMENTS[name]
            for name in capability_names
            if name in CAPABILITY_SOURCE_REQUIREMENTS
        }
    )
    present_sources = sorted(
        key for key in EVIDENCE_KEYS if evidence.get(key) is not None
    )
    missing_required = sorted(set(required_sources) - set(present_sources))
    missing_optional = sorted(
        key
        for key in EVIDENCE_KEYS
        if key not in required_sources and evidence.get(key) is None
    )
    return {
        "required_sources": required_sources,
        "required_sources_present": sorted(set(required_sources) & set(present_sources)),
        "missing_required_sources": missing_required,
        "missing_optional_sources": missing_optional,
        "package_complete_for_bounded_query": not missing_required,
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
    grants = capability_grants(capabilities)
    capability_names = [grant["capability"] for grant in grants]
    provenance: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "declared_project_state": None,
        "observed_environment_facts": None,
        "servicetracer_finding": None,
        "observed_git_state": git_state,
    }

    if project_state_path is not None:
        evidence["declared_project_state"] = sanitize_project_state(
            load_json_object(project_state_path, label="project state")
        )
        provenance.append(
            provenance_record(project_state_path, "declared_project_state")
        )
    if environment_state_path is not None:
        evidence["observed_environment_facts"] = sanitize_environment_state(
            load_json_object(environment_state_path, label="environment state")
        )
        provenance.append(
            provenance_record(environment_state_path, "observed_environment_facts")
        )
    if servicetracer_report_path is not None:
        evidence["servicetracer_finding"] = sanitize_servicetracer_report(
            load_json_object(servicetracer_report_path, label="ServiceTracer report")
        )
        provenance.append(
            provenance_record(servicetracer_report_path, "servicetracer_finding")
        )

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
                "evidence. An incomplete package cannot support a complete answer."
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
            "capability_grants": grants,
        },
        "evidence": evidence,
        "completeness": _completeness_for(capability_names, evidence),
        "provenance": provenance,
        "notices": [
            "This package is context, not an authorized decision.",
            "Capabilities describe bounded requests; they do not execute actions.",
            "Top-level inputs are allowlisted; allowed nested JSON is recursively bounded and secret-field names are rejected.",
            "package_complete_for_bounded_query is derived from requested capabilities and supplied evidence.",
        ],
    }
    package["integrity"] = {
        "algorithm": "sha256",
        "canonical_json_sha256": canonical_sha256(package),
    }
    return package


def _validate_project_projection(value: Any) -> None:
    projection = _mapping(value, field="evidence.declared_project_state")
    if projection.get("projection_version") != PROJECT_PROJECTION_VERSION:
        raise HelixContextError("project state projection version is missing or unsupported")
    if projection.get("schema_version") not in PROJECT_STATE_SCHEMAS:
        raise HelixContextError("project state projection has unsupported source schema")
    allowed = {
        "schema_version",
        "projection_version",
        "project",
        "updated_on",
        "baseline",
        "workstreams",
        "repository_observation",
        "bounded_authority_grants",
        "authority_defaults",
    }
    if set(projection) != allowed:
        raise HelixContextError("project state projection contains missing or unknown fields")
    bounded_json(
        projection,
        field="evidence.declared_project_state",
        maximum_depth=6,
        maximum_items=200,
        maximum_bytes=100000,
    )
    workstreams = projection.get("workstreams")
    if not isinstance(workstreams, list):
        raise HelixContextError("project state projection workstreams must be a list")
    branches: set[str] = set()
    for index, item in enumerate(workstreams):
        workstream = _mapping(item, field=f"project_projection.workstreams[{index}]")
        branch = bounded_text(
            workstream.get("branch"),
            field=f"project_projection.workstreams[{index}].branch",
            maximum=300,
        )
        if branch in branches:
            raise HelixContextError(f"duplicate workstream branch ownership: {branch}")
        branches.add(branch)


def _validate_git_projection(value: Any) -> None:
    git_state = _mapping(value, field="evidence.observed_git_state")
    allowed = {
        "repository_name",
        "branch",
        "head",
        "dirty_working_tree",
        "changed_paths",
    }
    if set(git_state) != allowed:
        raise HelixContextError("observed Git state contains missing or unknown fields")
    bounded_text(git_state.get("repository_name"), field="observed_git_state.repository_name")
    bounded_text(git_state.get("branch"), field="observed_git_state.branch", maximum=300)
    bounded_text(git_state.get("head"), field="observed_git_state.head", maximum=100)
    if not isinstance(git_state.get("dirty_working_tree"), bool):
        raise HelixContextError("observed_git_state.dirty_working_tree must be boolean")
    _string_list(
        git_state.get("changed_paths"),
        field="observed_git_state.changed_paths",
        maximum_items=MAX_CHANGED_PATHS,
        maximum_string=1000,
    )


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
    capability_names: list[str] = []
    for index, grant in enumerate(grants):
        grant_map = _mapping(grant, field=f"capability_grants[{index}]")
        name = grant_map.get("capability")
        if name not in CAPABILITY_CATALOG:
            raise HelixContextError(f"unsupported packaged capability: {name}")
        capability_names.append(str(name))

    evidence = _mapping(package.get("evidence"), field="evidence")
    if set(evidence) != set(EVIDENCE_KEYS):
        raise HelixContextError("evidence contains missing or unknown source fields")
    _validate_git_projection(evidence.get("observed_git_state"))
    project_state = evidence.get("declared_project_state")
    if project_state is not None:
        _validate_project_projection(project_state)
    environment = evidence.get("observed_environment_facts")
    if environment is not None:
        sanitized_environment = sanitize_environment_state(
            _mapping(environment, field="evidence.observed_environment_facts")
        )
        if sanitized_environment != environment:
            raise HelixContextError("environment evidence is not in canonical projection form")
    servicetracer = evidence.get("servicetracer_finding")
    if servicetracer is not None:
        sanitized_servicetracer = sanitize_servicetracer_report(
            _mapping(servicetracer, field="evidence.servicetracer_finding")
        )
        if sanitized_servicetracer != servicetracer:
            raise HelixContextError("ServiceTracer evidence is not in canonical projection form")

    completeness = _mapping(package.get("completeness"), field="completeness")
    expected_completeness = _completeness_for(capability_names, evidence)
    if dict(completeness) != expected_completeness:
        raise HelixContextError(
            "completeness does not match requested capabilities and supplied evidence"
        )

    integrity = _mapping(package.get("integrity"), field="integrity")
    if integrity.get("algorithm") != "sha256":
        raise HelixContextError("integrity algorithm must be sha256")
    expected = integrity.get("canonical_json_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
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
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextos-helix",
        description="Build and validate bounded ContextOS query packages for HELIX.",
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
            print(
                "Complete for bounded query: "
                f"{str(package['completeness']['package_complete_for_bounded_query']).lower()}"
            )
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
