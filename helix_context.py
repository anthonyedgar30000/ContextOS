#!/usr/bin/env python3
"""Build and validate bounded ContextOS query packages for HELIX reasoning nodes.

The bridge is deliberately read-only. It packages declared project state, observed
Git state, evidence-backed environment facts, and a bounded ServiceTracer handoff.
It does not call cloud APIs, execute diagnostics, mutate Git, or grant an AI direct
shell or state-changing authority.
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
SAFE_SENSITIVE_BOOLEAN_KEYS = {"credential_use"}

SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"^Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"^sk-[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{20,}$"),
    re.compile(r"^github_pat_[A-Za-z0-9_]{20,}$"),
    re.compile(r"^AKIA[0-9A-Z]{16}$"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

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

PACKAGE_KEYS = {
    "schema_version",
    "package_id",
    "correlation_id",
    "generated_at",
    "expires_at",
    "sequence",
    "query",
    "subject",
    "authority",
    "evidence",
    "completeness",
    "provenance",
    "notices",
    "integrity",
}
AUTHORITY_KEYS = {
    "authority_state",
    "mutation_authority",
    "may_claim_authorized_decision",
    "state_change_requires_separate_human_approval",
    "capability_grants",
}
CAPABILITY_GRANT_KEYS = {
    "capability",
    "mode",
    "description",
    "human_approval_required",
}
PROJECT_PROJECTION_KEYS = {
    "projection_version",
    "schema_version",
    "project",
    "updated_on",
    "baseline",
    "workstreams",
    "known_open_pull_requests",
    "repository_observation",
    "bounded_authority_grants",
    "authority_defaults",
}
BASELINE_KEYS = {
    "branch",
    "commit",
    "resolution",
    "pull_request",
    "title",
    "qualification",
    "claim_boundary",
}
WORKSTREAM_KEYS = {
    "workstream_id",
    "branch",
    "pull_request",
    "write_owner",
    "status",
    "objective",
    "authority",
    "state_semantics",
    "permitted_paths",
    "protected_paths",
    "capability_boundary",
    "verification_criteria",
    "next_gate",
    "failure_behavior",
    "rollback",
}
OPEN_PR_KEYS = {"pull_request", "title", "status", "action"}
OBSERVATION_KEYS = {
    "observed_on",
    "source",
    "main_head",
    "head_semantics",
    "open_pull_requests",
    "claim_boundary",
}
BOUNDED_GRANT_KEYS = {
    "grant_id",
    "workflow_path",
    "operation",
    "active_workflow_authorized",
    "dispatch_authorized",
    "azure_authentication_authorized",
    "azure_mutations_authorized",
    "authorized_by",
    "authorized_on",
    "protected_environment",
    "required_commit_semantics",
    "required_confirmation",
    "permitted_azure_operations",
    "claim_boundary",
}
AUTHORITY_DEFAULT_KEYS = {
    "active_workflow_present",
    "dispatch_authorized",
    "azure_authentication_authorized",
    "azure_mutations_authorized",
}
PROVENANCE_KEYS = {"artifact_type", "source_name", "sha256"}


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


def _boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise HelixContextError(f"{field} must be boolean")
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


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HelixContextError(f"{field} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise HelixContextError(
            f"{field} shape mismatch; missing={missing}, unknown={unknown}"
        )


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return any(segment in normalized for segment in SENSITIVE_KEY_SEGMENTS)


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
                if key not in SAFE_SENSITIVE_BOOLEAN_KEYS:
                    raise HelixContextError(
                        f"{field}.{key} contains a sensitive field name"
                    )
                if not isinstance(item, bool):
                    raise HelixContextError(
                        f"{field}.{key} must be boolean governance metadata"
                    )
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
            "qualification": None,
            "claim_boundary": None,
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
            baseline.get("pull_request"), field="last_substantive_baseline.pull_request"
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
            item.get("state_semantics"), field=f"{prefix}.state_semantics", maximum=300
        ),
        "permitted_paths": _string_list(
            item.get("permitted_paths"), field=f"{prefix}.permitted_paths"
        ),
        "protected_paths": _string_list(
            item.get("protected_paths"), field=f"{prefix}.protected_paths"
        ),
        "capability_boundary": bounded_json(
            item.get("capability_boundary") or {},
            field=f"{prefix}.capability_boundary",
            maximum_depth=3,
            maximum_items=50,
            maximum_bytes=8192,
        ),
        "verification_criteria": _string_list(
            verification, field=f"{prefix}.verification_criteria"
        ),
        "next_gate": optional_text(
            item.get("next_gate"), field=f"{prefix}.next_gate", maximum=4000
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


def _sanitize_open_pr(item: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    prefix = f"known_open_pull_requests[{index}]"
    return {
        "pull_request": _optional_positive_int(
            item.get("pull_request"), field=f"{prefix}.pull_request"
        ),
        "title": optional_text(item.get("title"), field=f"{prefix}.title"),
        "status": optional_text(item.get("status"), field=f"{prefix}.status"),
        "action": optional_text(
            item.get("action"), field=f"{prefix}.action", maximum=4000
        ),
    }


def _sanitize_observation(value: Mapping[str, Any], *, schema: str) -> dict[str, Any]:
    if schema == "project.active-work.v1":
        return {
            "observed_on": None,
            "source": None,
            "main_head": None,
            "head_semantics": None,
            "open_pull_requests": [],
            "claim_boundary": None,
        }
    observation = _mapping(
        value.get("repository_observation"), field="repository_observation"
    )
    return {
        "observed_on": optional_text(
            observation.get("observed_on"), field="repository_observation.observed_on"
        ),
        "source": optional_text(
            observation.get("source"), field="repository_observation.source"
        ),
        "main_head": optional_text(
            observation.get("main_head"),
            field="repository_observation.main_head",
            maximum=100,
        ),
        "head_semantics": optional_text(
            observation.get("head_semantics"),
            field="repository_observation.head_semantics",
        ),
        "open_pull_requests": bounded_json(
            observation.get("open_pull_requests") or [],
            field="repository_observation.open_pull_requests",
            maximum_depth=3,
            maximum_items=100,
            maximum_bytes=8192,
        ),
        "claim_boundary": optional_text(
            observation.get("claim_boundary"),
            field="repository_observation.claim_boundary",
            maximum=4000,
        ),
    }


def _sanitize_grant(item: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    prefix = f"bounded_authority_grants[{index}]"
    return {
        "grant_id": bounded_text(item.get("grant_id"), field=f"{prefix}.grant_id"),
        "workflow_path": optional_text(
            item.get("workflow_path"), field=f"{prefix}.workflow_path"
        ),
        "operation": bounded_text(item.get("operation"), field=f"{prefix}.operation"),
        "active_workflow_authorized": _boolean(
            item.get("active_workflow_authorized"),
            field=f"{prefix}.active_workflow_authorized",
        ),
        "dispatch_authorized": _boolean(
            item.get("dispatch_authorized"), field=f"{prefix}.dispatch_authorized"
        ),
        "azure_authentication_authorized": _boolean(
            item.get("azure_authentication_authorized"),
            field=f"{prefix}.azure_authentication_authorized",
        ),
        "azure_mutations_authorized": _boolean(
            item.get("azure_mutations_authorized"),
            field=f"{prefix}.azure_mutations_authorized",
        ),
        "authorized_by": optional_text(
            item.get("authorized_by"), field=f"{prefix}.authorized_by"
        ),
        "authorized_on": optional_text(
            item.get("authorized_on"), field=f"{prefix}.authorized_on"
        ),
        "protected_environment": optional_text(
            item.get("protected_environment"),
            field=f"{prefix}.protected_environment",
        ),
        "required_commit_semantics": optional_text(
            item.get("required_commit_semantics"),
            field=f"{prefix}.required_commit_semantics",
        ),
        "required_confirmation": optional_text(
            item.get("required_confirmation"),
            field=f"{prefix}.required_confirmation",
        ),
        "permitted_azure_operations": _string_list(
            item.get("permitted_azure_operations"),
            field=f"{prefix}.permitted_azure_operations",
        ),
        "claim_boundary": optional_text(
            item.get("claim_boundary"),
            field=f"{prefix}.claim_boundary",
            maximum=4000,
        ),
    }


def _sanitize_authority_defaults(value: Any) -> dict[str, bool]:
    if value is None:
        source: Mapping[str, Any] = {}
    else:
        source = _mapping(value, field="authority_defaults")
    return {
        key: _boolean(source.get(key, False), field=f"authority_defaults.{key}")
        for key in sorted(AUTHORITY_DEFAULT_KEYS)
    }


def sanitize_project_state(value: Mapping[str, Any]) -> dict[str, Any]:
    schema = value.get("schema_version")
    if schema not in PROJECT_STATE_SCHEMAS:
        raise HelixContextError(
            f"project state must use one of {sorted(PROJECT_STATE_SCHEMAS)}"
        )

    if schema == "project.active-work.v1":
        workstream_values = value.get("workstreams")
        open_pr_values = value.get("known_open_pull_requests", [])
        grant_values: Any = []
        defaults: Any = None
    else:
        authored = value.get("authored_change")
        workstream_values = [] if authored is None else [authored]
        open_pr_values = []
        grant_values = value.get("bounded_authority_grants", [])
        defaults = value.get("authority_defaults")

    if not isinstance(workstream_values, list) or len(workstream_values) > MAX_WORKSTREAMS:
        raise HelixContextError(
            f"project workstreams must be a list of at most {MAX_WORKSTREAMS} objects"
        )
    workstreams: list[dict[str, Any]] = []
    seen_branches: set[str] = set()
    for index, item in enumerate(workstream_values):
        workstream = _sanitize_workstream(_mapping(item, field=f"workstreams[{index}]"), index=index)
        if workstream["branch"] in seen_branches:
            raise HelixContextError(
                f"duplicate workstream branch ownership: {workstream['branch']}"
            )
        seen_branches.add(workstream["branch"])
        workstreams.append(workstream)

    if not isinstance(open_pr_values, list) or len(open_pr_values) > 100:
        raise HelixContextError("known_open_pull_requests must be a bounded list")
    known_open_pull_requests = [
        _sanitize_open_pr(_mapping(item, field=f"known_open_pull_requests[{index}]"), index=index)
        for index, item in enumerate(open_pr_values)
    ]

    if not isinstance(grant_values, list) or len(grant_values) > 50:
        raise HelixContextError("bounded_authority_grants must be a bounded list")
    grants = [
        _sanitize_grant(_mapping(item, field=f"bounded_authority_grants[{index}]"), index=index)
        for index, item in enumerate(grant_values)
    ]

    projection = {
        "projection_version": PROJECT_PROJECTION_VERSION,
        "schema_version": schema,
        "project": bounded_text(value.get("project"), field="project_state.project"),
        "updated_on": bounded_text(
            value.get("updated_on"), field="project_state.updated_on", maximum=50
        ),
        "baseline": _sanitize_baseline(value, schema=schema),
        "workstreams": workstreams,
        "known_open_pull_requests": known_open_pull_requests,
        "repository_observation": _sanitize_observation(value, schema=schema),
        "bounded_authority_grants": grants,
        "authority_defaults": _sanitize_authority_defaults(defaults),
    }
    validate_project_projection(projection)
    return projection


def validate_project_projection(value: Mapping[str, Any]) -> None:
    _exact_keys(value, PROJECT_PROJECTION_KEYS, field="project projection")
    if value.get("projection_version") != PROJECT_PROJECTION_VERSION:
        raise HelixContextError("project projection version is invalid")
    if value.get("schema_version") not in PROJECT_STATE_SCHEMAS:
        raise HelixContextError("project projection source schema is invalid")
    bounded_text(value.get("project"), field="project projection.project")
    bounded_text(value.get("updated_on"), field="project projection.updated_on", maximum=50)

    baseline = _mapping(value.get("baseline"), field="project projection.baseline")
    _exact_keys(baseline, BASELINE_KEYS, field="project projection.baseline")
    bounded_text(baseline.get("branch"), field="project projection.baseline.branch", maximum=300)
    optional_text(baseline.get("commit"), field="project projection.baseline.commit", maximum=100)
    optional_text(baseline.get("resolution"), field="project projection.baseline.resolution", maximum=300)
    _optional_positive_int(baseline.get("pull_request"), field="project projection.baseline.pull_request")
    optional_text(baseline.get("title"), field="project projection.baseline.title")
    optional_text(baseline.get("qualification"), field="project projection.baseline.qualification")
    optional_text(baseline.get("claim_boundary"), field="project projection.baseline.claim_boundary", maximum=4000)

    workstreams = value.get("workstreams")
    if not isinstance(workstreams, list) or len(workstreams) > MAX_WORKSTREAMS:
        raise HelixContextError("project projection.workstreams must be bounded list")
    seen_branches: set[str] = set()
    for index, item in enumerate(workstreams):
        workstream = _mapping(item, field=f"project projection.workstreams[{index}]")
        _exact_keys(workstream, WORKSTREAM_KEYS, field=f"project projection.workstreams[{index}]")
        branch = bounded_text(workstream.get("branch"), field=f"project projection.workstreams[{index}].branch", maximum=300)
        if branch in seen_branches:
            raise HelixContextError(f"duplicate workstream branch ownership: {branch}")
        seen_branches.add(branch)
        bounded_text(workstream.get("workstream_id"), field=f"project projection.workstreams[{index}].workstream_id", maximum=200)
        _optional_positive_int(workstream.get("pull_request"), field=f"project projection.workstreams[{index}].pull_request")
        optional_text(workstream.get("write_owner"), field=f"project projection.workstreams[{index}].write_owner", maximum=300)
        bounded_text(workstream.get("status"), field=f"project projection.workstreams[{index}].status", maximum=150)
        bounded_text(workstream.get("objective"), field=f"project projection.workstreams[{index}].objective", maximum=4000)
        optional_text(workstream.get("authority"), field=f"project projection.workstreams[{index}].authority", maximum=300)
        optional_text(workstream.get("state_semantics"), field=f"project projection.workstreams[{index}].state_semantics", maximum=300)
        _string_list(workstream.get("permitted_paths"), field=f"project projection.workstreams[{index}].permitted_paths")
        _string_list(workstream.get("protected_paths"), field=f"project projection.workstreams[{index}].protected_paths")
        bounded_json(workstream.get("capability_boundary"), field=f"project projection.workstreams[{index}].capability_boundary", maximum_depth=3, maximum_items=50, maximum_bytes=8192)
        _string_list(workstream.get("verification_criteria"), field=f"project projection.workstreams[{index}].verification_criteria")
        optional_text(workstream.get("next_gate"), field=f"project projection.workstreams[{index}].next_gate", maximum=4000)
        optional_text(workstream.get("failure_behavior"), field=f"project projection.workstreams[{index}].failure_behavior", maximum=4000)
        optional_text(workstream.get("rollback"), field=f"project projection.workstreams[{index}].rollback", maximum=4000)

    open_prs = value.get("known_open_pull_requests")
    if not isinstance(open_prs, list) or len(open_prs) > 100:
        raise HelixContextError("project projection.known_open_pull_requests must be bounded list")
    for index, item in enumerate(open_prs):
        pr = _mapping(item, field=f"project projection.known_open_pull_requests[{index}]")
        _exact_keys(pr, OPEN_PR_KEYS, field=f"project projection.known_open_pull_requests[{index}]")
        _optional_positive_int(pr.get("pull_request"), field=f"project projection.known_open_pull_requests[{index}].pull_request")
        optional_text(pr.get("title"), field=f"project projection.known_open_pull_requests[{index}].title")
        optional_text(pr.get("status"), field=f"project projection.known_open_pull_requests[{index}].status")
        optional_text(pr.get("action"), field=f"project projection.known_open_pull_requests[{index}].action", maximum=4000)

    observation = _mapping(value.get("repository_observation"), field="project projection.repository_observation")
    _exact_keys(observation, OBSERVATION_KEYS, field="project projection.repository_observation")
    optional_text(observation.get("observed_on"), field="project projection.repository_observation.observed_on")
    optional_text(observation.get("source"), field="project projection.repository_observation.source")
    optional_text(observation.get("main_head"), field="project projection.repository_observation.main_head", maximum=100)
    optional_text(observation.get("head_semantics"), field="project projection.repository_observation.head_semantics")
    bounded_json(observation.get("open_pull_requests"), field="project projection.repository_observation.open_pull_requests", maximum_depth=3, maximum_items=100, maximum_bytes=8192)
    optional_text(observation.get("claim_boundary"), field="project projection.repository_observation.claim_boundary", maximum=4000)

    grants = value.get("bounded_authority_grants")
    if not isinstance(grants, list) or len(grants) > 50:
        raise HelixContextError("project projection.bounded_authority_grants must be bounded list")
    for index, item in enumerate(grants):
        grant = _mapping(item, field=f"project projection.bounded_authority_grants[{index}]")
        _exact_keys(grant, BOUNDED_GRANT_KEYS, field=f"project projection.bounded_authority_grants[{index}]")
        bounded_text(grant.get("grant_id"), field=f"project projection.bounded_authority_grants[{index}].grant_id")
        optional_text(grant.get("workflow_path"), field=f"project projection.bounded_authority_grants[{index}].workflow_path")
        bounded_text(grant.get("operation"), field=f"project projection.bounded_authority_grants[{index}].operation")
        for key in (
            "active_workflow_authorized",
            "dispatch_authorized",
            "azure_authentication_authorized",
            "azure_mutations_authorized",
        ):
            _boolean(grant.get(key), field=f"project projection.bounded_authority_grants[{index}].{key}")
        optional_text(grant.get("authorized_by"), field=f"project projection.bounded_authority_grants[{index}].authorized_by")
        optional_text(grant.get("authorized_on"), field=f"project projection.bounded_authority_grants[{index}].authorized_on")
        optional_text(grant.get("protected_environment"), field=f"project projection.bounded_authority_grants[{index}].protected_environment")
        optional_text(grant.get("required_commit_semantics"), field=f"project projection.bounded_authority_grants[{index}].required_commit_semantics")
        optional_text(grant.get("required_confirmation"), field=f"project projection.bounded_authority_grants[{index}].required_confirmation")
        _string_list(grant.get("permitted_azure_operations"), field=f"project projection.bounded_authority_grants[{index}].permitted_azure_operations")
        optional_text(grant.get("claim_boundary"), field=f"project projection.bounded_authority_grants[{index}].claim_boundary", maximum=4000)

    defaults = _mapping(value.get("authority_defaults"), field="project projection.authority_defaults")
    _exact_keys(defaults, AUTHORITY_DEFAULT_KEYS, field="project projection.authority_defaults")
    for key in AUTHORITY_DEFAULT_KEYS:
        _boolean(defaults.get(key), field=f"project projection.authority_defaults.{key}")


def sanitize_environment_state(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != ENVIRONMENT_STATE_SCHEMA:
        raise HelixContextError(f"environment state must use {ENVIRONMENT_STATE_SCHEMA}")
    facts = value.get("facts")
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise HelixContextError(f"environment_state.facts must contain at most {MAX_FACTS} objects")
    sanitized_facts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(facts):
        fact = _mapping(item, field=f"environment_state.facts[{index}]")
        fact_id = bounded_text(fact.get("fact_id"), field=f"facts[{index}].fact_id", maximum=200)
        if fact_id in seen_ids:
            raise HelixContextError(f"duplicate environment fact id: {fact_id}")
        seen_ids.add(fact_id)
        sanitized_facts.append(
            {
                "fact_id": fact_id,
                "value": bounded_json(fact.get("value"), field=f"facts[{index}].value"),
                "status": bounded_text(fact.get("status"), field=f"facts[{index}].status", maximum=200),
                "last_observed_on": bounded_text(fact.get("last_observed_on"), field=f"facts[{index}].last_observed_on", maximum=100),
                "source": bounded_text(fact.get("source"), field=f"facts[{index}].source"),
                "notes": optional_text(fact.get("notes"), field=f"facts[{index}].notes", maximum=4000),
            }
        )
    return {
        "schema_version": ENVIRONMENT_STATE_SCHEMA,
        "project": bounded_text(value.get("project"), field="environment_state.project"),
        "updated_on": bounded_text(value.get("updated_on"), field="environment_state.updated_on", maximum=50),
        "facts": sanitized_facts,
    }


def _failure_rates(value: Any) -> dict[str, float]:
    source = _mapping(value, field="localization.backend_failure_rates")
    if len(source) > MAX_JSON_ITEMS:
        raise HelixContextError("backend_failure_rates is too large")
    result: dict[str, float] = {}
    for key, item in source.items():
        name = bounded_text(key, field="backend_failure_rates key", maximum=200)
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise HelixContextError(f"backend_failure_rates.{name} must be finite number")
        rate = float(item)
        if rate < 0 or rate > 1:
            raise HelixContextError(f"backend_failure_rates.{name} must be between 0 and 1")
        result[name] = rate
    return result


def sanitize_servicetracer_report(value: Mapping[str, Any]) -> dict[str, Any]:
    report = value
    if value.get("schema_version") == SERVICETRACER_PUBLIC_SCHEMA:
        report = _mapping(value.get("report"), field="servicetracer public envelope.report")

    boundary = _mapping(report.get("investigation_boundary"), field="investigation_boundary")
    if boundary.get("exact_root_cause_claimed") is not False:
        raise HelixContextError("ServiceTracer report must explicitly state exact_root_cause_claimed=false")
    root_cause = _mapping(report.get("root_cause"), field="root_cause")
    if root_cause.get("status") != "not_determined_by_servicetracer":
        raise HelixContextError("ServiceTracer report exceeds the bounded root-cause contract")

    incident = _mapping(report.get("incident"), field="incident")
    attempts = _non_negative_int(incident.get("attempts"), field="incident.attempts")
    successful = _non_negative_int(incident.get("successful_attempts"), field="incident.successful_attempts")
    failed = _non_negative_int(incident.get("failed_attempts"), field="incident.failed_attempts")
    if successful + failed != attempts:
        raise HelixContextError("incident success and failure counts must equal attempts")

    load_balancer = _mapping(report.get("load_balancer"), field="load_balancer")
    localization = _mapping(report.get("localization"), field="localization")
    workflow = report.get("technician_workflow", [])
    if not isinstance(workflow, list) or len(workflow) > 100:
        raise HelixContextError("technician_workflow must be a bounded list")
    sanitized_workflow = []
    for index, step in enumerate(workflow):
        step_map = _mapping(step, field=f"technician_workflow[{index}]")
        sanitized_workflow.append(
            {
                "step_id": bounded_text(step_map.get("step_id"), field=f"technician_workflow[{index}].step_id"),
                "owner": bounded_text(step_map.get("owner"), field=f"technician_workflow[{index}].owner"),
                "status": bounded_text(step_map.get("status"), field=f"technician_workflow[{index}].status"),
                "action": bounded_text(step_map.get("action"), field=f"technician_workflow[{index}].action", maximum=4000),
                "purpose": bounded_text(step_map.get("purpose"), field=f"technician_workflow[{index}].purpose", maximum=4000),
                "success_criteria": bounded_text(step_map.get("success_criteria"), field=f"technician_workflow[{index}].success_criteria", maximum=4000),
            }
        )

    return {
        "scenario": bounded_text(report.get("scenario"), field="servicetracer.scenario"),
        "status": bounded_text(report.get("status"), field="servicetracer.status"),
        "incident": {
            "classification": bounded_text(incident.get("classification"), field="incident.classification"),
            "attempts": attempts,
            "successful_attempts": successful,
            "failed_attempts": failed,
        },
        "load_balancer": {
            "status": bounded_text(load_balancer.get("status"), field="load_balancer.status"),
            "probe_name": bounded_text(load_balancer.get("probe_name"), field="load_balancer.probe_name"),
            "probe_scope": bounded_text(load_balancer.get("probe_scope"), field="load_balancer.probe_scope"),
            "backend_states": bounded_json(load_balancer.get("backend_states"), field="load_balancer.backend_states", maximum_depth=4, maximum_items=100, maximum_bytes=16384),
            "probe_gap_detected": _boolean(load_balancer.get("probe_gap_detected"), field="load_balancer.probe_gap_detected"),
        },
        "localization": {
            "suspect_backend": bounded_text(localization.get("suspect_backend"), field="localization.suspect_backend"),
            "healthy_comparison_backend": bounded_text(localization.get("healthy_comparison_backend"), field="localization.healthy_comparison_backend"),
            "suspect_probe_status": bounded_text(localization.get("suspect_probe_status"), field="localization.suspect_probe_status"),
            "backend_failure_rates": _failure_rates(localization.get("backend_failure_rates")),
        },
        "service_tracer_finding": bounded_text(report.get("service_tracer_finding"), field="servicetracer.service_tracer_finding", maximum=4000),
        "investigation_boundary": {
            "service_tracer_stops_at": bounded_text(boundary.get("service_tracer_stops_at"), field="investigation_boundary.service_tracer_stops_at"),
            "exact_root_cause_claimed": False,
            "statement": bounded_text(boundary.get("statement"), field="investigation_boundary.statement", maximum=4000),
        },
        "root_cause": {
            "status": "not_determined_by_servicetracer",
            "owner": bounded_text(root_cause.get("owner"), field="root_cause.owner"),
        },
        "temporary_service_status": bounded_text(report.get("temporary_service_status"), field="temporary_service_status"),
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
            f"git {' '.join(args)} failed: {completed.stderr.strip() or 'no error output'}"
        )
    return completed.stdout.strip()


def observe_git_state(repo: Path) -> dict[str, Any]:
    root = Path(run_git(repo, ["rev-parse", "--show-toplevel"]))
    status = run_git(root, ["status", "--porcelain=v1"])
    branch = run_git(root, ["branch", "--show-current"]) or "(detached HEAD)"
    changed_paths = [
        line[3:] if len(line) >= 4 else line
        for line in status.splitlines()
        if line
    ]
    if len(changed_paths) > MAX_CHANGED_PATHS:
        raise HelixContextError("working tree contains too many changed paths")
    return {
        "repository_name": bounded_text(root.name, field="git.repository_name", maximum=300),
        "branch": bounded_text(branch, field="git.branch", maximum=300),
        "head": bounded_text(run_git(root, ["rev-parse", "HEAD"]), field="git.head", maximum=100),
        "dirty_working_tree": bool(status),
        "changed_paths": [
            bounded_text(path, field=f"git.changed_paths[{index}]", maximum=1000)
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
        "artifact_type": bounded_text(artifact_type, field="provenance.artifact_type", maximum=100),
        "source_name": bounded_text(path.name, field="provenance.source_name", maximum=255),
        "sha256": file_sha256(path),
    }


def _completeness(capabilities: Sequence[str], evidence: Mapping[str, Any]) -> dict[str, Any]:
    required = []
    for capability in dict.fromkeys(capabilities):
        source = CAPABILITY_SOURCE_REQUIREMENTS.get(capability)
        if source is not None and source not in required:
            required.append(source)
    present = [source for source in required if evidence.get(source) is not None]
    missing_required = [source for source in required if evidence.get(source) is None]
    missing_optional = [
        source
        for source in EVIDENCE_KEYS
        if source not in required and evidence.get(source) is None
    ]
    return {
        "required_sources_present": present,
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
        provenance.append(provenance_record(project_state_path, "declared_project_state"))
    if environment_state_path is not None:
        evidence["observed_environment_facts"] = sanitize_environment_state(
            load_json_object(environment_state_path, label="environment state")
        )
        provenance.append(provenance_record(environment_state_path, "observed_environment_facts"))
    if servicetracer_report_path is not None:
        evidence["servicetracer_finding"] = sanitize_servicetracer_report(
            load_json_object(servicetracer_report_path, label="ServiceTracer report")
        )
        provenance.append(provenance_record(servicetracer_report_path, "servicetracer_finding"))

    grants = capability_grants(capabilities)
    package: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package_id": f"ctxhelix-{uuid.uuid4()}",
        "correlation_id": correlation_id or f"corr-{uuid.uuid4()}",
        "generated_at": iso_z(observed_at),
        "expires_at": iso_z(observed_at + timedelta(minutes=ttl_minutes)),
        "sequence": {"number": 1, "total": 1, "complete": True},
        "query": {
            "text": query_text,
            "answer_boundary": "Evidence-bound summary; disclose missing, stale, or conflicting evidence.",
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
        "completeness": _completeness(capabilities, evidence),
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
    validate_query_package(package, now=observed_at)
    return package


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise HelixContextError(f"{field} must be ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HelixContextError(f"{field} is not a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise HelixContextError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def validate_query_package(package: Mapping[str, Any], *, now: datetime | None = None) -> None:
    _exact_keys(package, PACKAGE_KEYS, field="package")
    if package.get("schema_version") != SCHEMA_VERSION:
        raise HelixContextError(f"package must use {SCHEMA_VERSION}")
    bounded_text(package.get("package_id"), field="package_id", maximum=200)
    bounded_text(package.get("correlation_id"), field="correlation_id", maximum=200)

    sequence = _mapping(package.get("sequence"), field="sequence")
    _exact_keys(sequence, {"number", "total", "complete"}, field="sequence")
    if sequence != {"number": 1, "total": 1, "complete": True}:
        raise HelixContextError("sequence must describe one complete package")

    query = _mapping(package.get("query"), field="query")
    _exact_keys(query, {"text", "answer_boundary"}, field="query")
    bounded_text(query.get("text"), field="query.text", maximum=1000)
    bounded_text(query.get("answer_boundary"), field="query.answer_boundary", maximum=1000)

    subject = _mapping(package.get("subject"), field="subject")
    _exact_keys(subject, {"project", "repository", "branch", "head"}, field="subject")
    bounded_text(subject.get("project"), field="subject.project")
    bounded_text(subject.get("repository"), field="subject.repository", maximum=300)
    bounded_text(subject.get("branch"), field="subject.branch", maximum=300)
    bounded_text(subject.get("head"), field="subject.head", maximum=100)

    authority = _mapping(package.get("authority"), field="authority")
    _exact_keys(authority, AUTHORITY_KEYS, field="authority")
    if authority.get("authority_state") != "candidate_context_only":
        raise HelixContextError("authority_state must be candidate_context_only")
    if authority.get("mutation_authority") is not False:
        raise HelixContextError("HELIX query package must not grant mutation authority")
    if authority.get("may_claim_authorized_decision") is not False:
        raise HelixContextError("HELIX query package must not claim an authorized decision")
    if authority.get("state_change_requires_separate_human_approval") is not True:
        raise HelixContextError("state changes must require separate human approval")
    grants = authority.get("capability_grants")
    if not isinstance(grants, list) or not grants:
        raise HelixContextError("authority.capability_grants must be non-empty list")
    capability_names: list[str] = []
    for index, item in enumerate(grants):
        grant = _mapping(item, field=f"authority.capability_grants[{index}]")
        _exact_keys(grant, CAPABILITY_GRANT_KEYS, field=f"authority.capability_grants[{index}]")
        name = bounded_text(grant.get("capability"), field=f"authority.capability_grants[{index}].capability", maximum=100)
        if name not in CAPABILITY_CATALOG:
            raise HelixContextError(f"unsupported packaged capability: {name}")
        expected = {"capability": name, **CAPABILITY_CATALOG[name]}
        if dict(grant) != expected:
            raise HelixContextError(f"capability grant semantics drifted for {name}")
        if name in capability_names:
            raise HelixContextError(f"duplicate packaged capability: {name}")
        capability_names.append(name)

    evidence = _mapping(package.get("evidence"), field="evidence")
    _exact_keys(evidence, set(EVIDENCE_KEYS), field="evidence")
    project_state = evidence.get("declared_project_state")
    if project_state is not None:
        validate_project_projection(_mapping(project_state, field="evidence.declared_project_state"))
    environment = evidence.get("observed_environment_facts")
    if environment is not None:
        if sanitize_environment_state(_mapping(environment, field="evidence.observed_environment_facts")) != environment:
            raise HelixContextError("environment evidence is not canonical sanitized projection")
    servicetracer = evidence.get("servicetracer_finding")
    if servicetracer is not None:
        if sanitize_servicetracer_report(_mapping(servicetracer, field="evidence.servicetracer_finding")) != servicetracer:
            raise HelixContextError("ServiceTracer evidence is not canonical sanitized projection")
    git_state = _mapping(evidence.get("observed_git_state"), field="evidence.observed_git_state")
    _exact_keys(git_state, {"repository_name", "branch", "head", "dirty_working_tree", "changed_paths"}, field="evidence.observed_git_state")
    bounded_text(git_state.get("repository_name"), field="evidence.observed_git_state.repository_name", maximum=300)
    bounded_text(git_state.get("branch"), field="evidence.observed_git_state.branch", maximum=300)
    bounded_text(git_state.get("head"), field="evidence.observed_git_state.head", maximum=100)
    _boolean(git_state.get("dirty_working_tree"), field="evidence.observed_git_state.dirty_working_tree")
    _string_list(git_state.get("changed_paths"), field="evidence.observed_git_state.changed_paths", maximum_items=MAX_CHANGED_PATHS)

    completeness = _mapping(package.get("completeness"), field="completeness")
    _exact_keys(completeness, {"required_sources_present", "missing_required_sources", "missing_optional_sources", "package_complete_for_bounded_query"}, field="completeness")
    expected_completeness = _completeness(capability_names, evidence)
    if dict(completeness) != expected_completeness:
        raise HelixContextError("completeness does not match capabilities and supplied evidence")

    provenance = package.get("provenance")
    if not isinstance(provenance, list) or len(provenance) > 20:
        raise HelixContextError("provenance must be bounded list")
    for index, item in enumerate(provenance):
        record = _mapping(item, field=f"provenance[{index}]")
        _exact_keys(record, PROVENANCE_KEYS, field=f"provenance[{index}]")
        bounded_text(record.get("artifact_type"), field=f"provenance[{index}].artifact_type", maximum=100)
        source_name = bounded_text(record.get("source_name"), field=f"provenance[{index}].source_name", maximum=255)
        if Path(source_name).name != source_name or Path(source_name).is_absolute():
            raise HelixContextError("provenance source_name must be a logical basename")
        digest = record.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise HelixContextError(f"provenance[{index}].sha256 is malformed")

    notices = package.get("notices")
    if not isinstance(notices, list) or not notices or len(notices) > 20:
        raise HelixContextError("notices must be bounded non-empty list")
    for index, notice in enumerate(notices):
        bounded_text(notice, field=f"notices[{index}]", maximum=1000)

    generated = _parse_timestamp(package.get("generated_at"), field="generated_at")
    expires = _parse_timestamp(package.get("expires_at"), field="expires_at")
    if expires <= generated or expires - generated > timedelta(minutes=1440):
        raise HelixContextError("package expiry interval is invalid")
    current = now or utc_now()
    if current.astimezone(timezone.utc) > expires:
        raise HelixContextError("package has expired")

    integrity = _mapping(package.get("integrity"), field="integrity")
    _exact_keys(integrity, {"algorithm", "canonical_json_sha256"}, field="integrity")
    if integrity.get("algorithm") != "sha256":
        raise HelixContextError("integrity algorithm must be sha256")
    expected_hash = integrity.get("canonical_json_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise HelixContextError("integrity hash is missing or malformed")
    unhashed = dict(package)
    unhashed.pop("integrity", None)
    if canonical_sha256(unhashed) != expected_hash:
        raise HelixContextError("package integrity hash mismatch")


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextos-helix",
        description="Build and validate bounded ContextOS query packages for HELIX.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build a bounded HELIX query package")
    build.add_argument("--repo", type=Path, default=Path.cwd())
    build.add_argument("--query", required=True)
    build.add_argument("--capability", action="append", dest="capabilities", required=True)
    build.add_argument("--project-state", type=Path)
    build.add_argument("--environment-state", type=Path)
    build.add_argument("--servicetracer-report", type=Path)
    build.add_argument("--ttl-minutes", type=int, default=60)
    build.add_argument("--correlation-id")
    build.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate", help="validate a HELIX query package")
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
