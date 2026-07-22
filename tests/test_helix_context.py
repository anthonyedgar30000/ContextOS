from __future__ import annotations

import copy
import json
import math
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import helix_context


NOW = datetime(2026, 7, 22, 20, 0, tzinfo=timezone.utc)


class HelixContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=self.root,
            check=True,
        )
        (self.root / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

        self.project_state_v1 = {
            "schema_version": "project.active-work.v1",
            "project": "HELIX — Coordination and Reality Control",
            "updated_on": "2026-07-22",
            "resolution_rules": {"current_default_branch_head": "live GitHub"},
            "trusted_baseline": {
                "branch": "main",
                "resolution": "live_github_default_branch_head",
                "last_observed_commit": "be6ec9bf6d84a5fa4b0a5ef4b22edd5cbc37eb26",
                "last_completed_increment": {
                    "pull_request": 4,
                    "title": "Register persistence charter",
                },
            },
            "workstreams": [
                {
                    "workstream_id": "persistence-reconciliation",
                    "branch": "chore/reconcile-persistence",
                    "pull_request": 6,
                    "write_owner": "HELIX coordination conversation",
                    "status": "temporary_claim_active_while_pull_request_is_open",
                    "objective": "Reconcile the persistence charter merge state.",
                    "permitted_paths": [".project/active-work.json"],
                    "protected_paths": ["runtime/**", "**/*secret*"],
                    "capability_boundary": {
                        "pull_request_merge": False,
                        "cloud_mutation": False,
                    },
                    "verification_criteria": ["one-file diff", "exact-head CI"],
                    "next_gate": "Explicit merge decision",
                    "nested_unknown": {"safe": "dropped at top-level projection"},
                }
            ],
            "known_open_pull_requests": [],
            "top_level_secret": "must-not-leak",
        }
        self.project_state_v2 = {
            "schema_version": "project.active-work.v2",
            "project": "ServiceTracer — Governed Azure Operations Lab",
            "updated_on": "2026-07-22",
            "last_substantive_baseline": {
                "branch": "main",
                "commit": "e379064b7ee8b6a1a8b7731d31dedef1bca19e6f",
                "pull_request": 38,
                "title": "Promote read-only planner",
                "qualification": "ci_verified_not_deployed",
                "claim_boundary": "Repository workflow exists; deployment is unproven.",
            },
            "repository_observation": {
                "observed_on": "2026-07-22",
                "source": "live_github",
                "main_head": "e379064b7ee8b6a1a8b7731d31dedef1bca19e6f",
                "head_semantics": "time-bounded observation",
                "open_pull_requests": [],
                "claim_boundary": "Resolve live state at read time.",
            },
            "authored_change": {
                "change_id": "repair-planner",
                "branch": "fix/planner",
                "pull_request": 39,
                "write_owner": "bounded repair conversation",
                "scope": "Repair read-only planner evidence handling.",
                "authority": "repository_only",
                "state_semantics": "declaration_not_live_status",
                "permitted_paths": ["infra/scripts/planner.sh"],
                "verification_criteria": ["exact-head CI"],
                "failure_behavior": "Keep draft and fail closed.",
                "rollback": "Close or revert repository commits.",
            },
            "bounded_authority_grants": [
                {
                    "grant_id": "read-only-plan",
                    "workflow_path": ".github/workflows/plan.yml",
                    "operation": "read_only_azure_planning",
                    "active_workflow_authorized": True,
                    "dispatch_authorized": True,
                    "azure_authentication_authorized": True,
                    "azure_mutations_authorized": False,
                    "authorized_by": "Anthony Edgar",
                    "authorized_on": "2026-07-22",
                    "protected_environment": "azure-lab",
                    "required_commit_semantics": "exact commit",
                    "required_confirmation": "PLAN:<target>",
                    "permitted_azure_operations": ["az account show"],
                    "claim_boundary": "Read-only only.",
                }
            ],
            "authority_defaults": {
                "active_workflow_present": False,
                "dispatch_authorized": False,
                "azure_authentication_authorized": False,
                "azure_mutations_authorized": False,
            },
        }
        self.environment_state = {
            "schema_version": "project.environment-state.v1",
            "project": "ServiceTracer Azure MSP Lab",
            "updated_on": "2026-07-21",
            "facts": [
                {
                    "fact_id": "collector-vm-size",
                    "value": {
                        "sku": "Standard_B2ats_v2",
                        "metadata": {"source_kind": "control_plane"},
                    },
                    "status": "azure_control_plane_observed",
                    "last_observed_on": "2026-07-21",
                    "source": "Azure planning artifact",
                    "notes": "Guest health not reverified.",
                    "credential": "must-not-leak",
                }
            ],
        }
        self.servicetracer = {
            "scenario": "intermittent_remote_access",
            "status": "technician_investigation_required",
            "incident": {
                "classification": "intermittent_failure",
                "attempts": 2,
                "successful_attempts": 1,
                "failed_attempts": 1,
            },
            "load_balancer": {
                "status": "healthy_under_configured_probe",
                "probe_name": "tcp-443-shallow",
                "probe_scope": "listener-only",
                "backend_states": {
                    "VPN-01": {"probe_status": "healthy", "observations": ["ok"]}
                },
                "probe_gap_detected": True,
            },
            "localization": {
                "suspect_backend": "VPN-02",
                "healthy_comparison_backend": "VPN-01",
                "suspect_probe_status": "healthy",
                "backend_failure_rates": {"VPN-01": 0.0, "VPN-02": 1.0},
            },
            "service_tracer_finding": "Continue investigation at VPN-02.",
            "investigation_boundary": {
                "service_tracer_stops_at": "VPN-02",
                "exact_root_cause_claimed": False,
                "statement": "Technician owns device diagnosis.",
            },
            "root_cause": {
                "status": "not_determined_by_servicetracer",
                "owner": "technician",
            },
            "temporary_service_status": "stabilized_under_containment",
            "technician_workflow": [
                {
                    "step_id": "review",
                    "owner": "technician",
                    "status": "pending",
                    "action": "Review VPN-02.",
                    "purpose": "Identify the device-specific defect.",
                    "success_criteria": "Repair is verified.",
                }
            ],
            "raw_radius_secret": "must-not-leak",
        }
        self.project_path = self.write_json("project.json", self.project_state_v1)
        self.environment_path = self.write_json(
            "environment.json", self.environment_state
        )
        self.report_path = self.write_json("report.json", self.servicetracer)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_json(self, name: str, value: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def build(self, **overrides: object) -> dict:
        arguments = {
            "repo": self.root,
            "query": "Why is the collector migration blocked?",
            "capabilities": [
                "query_project_state",
                "query_environment_facts",
                "query_servicetracer_findings",
                "query_git_state",
                "request_human_review",
            ],
            "project_state_path": self.project_path,
            "environment_state_path": self.environment_path,
            "servicetracer_report_path": self.report_path,
            "ttl_minutes": 60,
            "correlation_id": "corr-test",
            "now": NOW,
        }
        arguments.update(overrides)
        return helix_context.build_query_package(**arguments)

    def test_builds_valid_bounded_package(self) -> None:
        package = self.build()
        self.assertEqual(package["schema_version"], helix_context.SCHEMA_VERSION)
        self.assertFalse(package["authority"]["mutation_authority"])
        self.assertTrue(package["completeness"]["package_complete_for_bounded_query"])
        self.assertEqual(
            package["evidence"]["servicetracer_finding"]["localization"][
                "suspect_backend"
            ],
            "VPN-02",
        )
        self.assertNotIn("must-not-leak", json.dumps(package))
        self.assertNotIn("repository_root", package["evidence"]["observed_git_state"])
        helix_context.validate_query_package(package, now=NOW)

    def test_accepts_live_helix_v1_shape_without_scope_field(self) -> None:
        sanitized = helix_context.sanitize_project_state(self.project_state_v1)
        workstream = sanitized["workstreams"][0]
        self.assertEqual(
            workstream["objective"], "Reconcile the persistence charter merge state."
        )
        self.assertEqual(workstream["permitted_paths"], [".project/active-work.json"])
        self.assertNotIn("nested_unknown", workstream)

    def test_accepts_servicetracer_v2_shape(self) -> None:
        sanitized = helix_context.sanitize_project_state(self.project_state_v2)
        self.assertEqual(sanitized["schema_version"], "project.active-work.v2")
        self.assertEqual(sanitized["workstreams"][0]["branch"], "fix/planner")
        self.assertFalse(
            sanitized["bounded_authority_grants"][0]["azure_mutations_authorized"]
        )

    def test_v2_authored_change_without_status_uses_state_semantics(self) -> None:
        sanitized = helix_context.sanitize_project_state(self.project_state_v2)
        self.assertEqual(
            sanitized["workstreams"][0]["status"],
            "declaration_not_live_status",
        )

    def test_nested_api_key_field_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.environment_state)
        unsafe["facts"][0]["value"]["metadata"]["api_key"] = "not-safe"
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "sensitive field name"
        ):
            helix_context.sanitize_environment_state(unsafe)

    def test_credential_prefix_value_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.environment_state)
        unsafe["facts"][0]["value"]["metadata"]["opaque"] = (
            "sk-1234567890abcdefghijklmnop"
        )
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "credential-like value"
        ):
            helix_context.sanitize_environment_state(unsafe)

    def test_recursive_environment_secret_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.environment_state)
        unsafe["facts"][0]["value"]["metadata"]["client_secret"] = "leak"
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "sensitive field name"
        ):
            helix_context.sanitize_environment_state(unsafe)

    def test_recursive_servicetracer_secret_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.servicetracer)
        unsafe["load_balancer"]["backend_states"]["VPN-01"]["bearer_token"] = "leak"
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "sensitive field name"
        ):
            helix_context.sanitize_servicetracer_report(unsafe)

    def test_excessive_nested_depth_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.environment_state)
        unsafe["facts"][0]["value"] = {"a": {"b": {"c": {"d": {"e": "too deep"}}}}}
        with self.assertRaisesRegex(helix_context.HelixContextError, "depth"):
            helix_context.sanitize_environment_state(unsafe)

    def test_non_finite_number_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.environment_state)
        unsafe["facts"][0]["value"] = math.nan
        with self.assertRaisesRegex(helix_context.HelixContextError, "non-finite"):
            helix_context.sanitize_environment_state(unsafe)

    def test_missing_requested_evidence_is_reported_incomplete(self) -> None:
        package = self.build(environment_state_path=None)
        self.assertFalse(package["completeness"]["package_complete_for_bounded_query"])
        self.assertEqual(
            package["completeness"]["missing_required_sources"],
            ["observed_environment_facts"],
        )
        helix_context.validate_query_package(package, now=NOW)

    def test_request_only_capability_needs_no_external_evidence(self) -> None:
        package = self.build(
            capabilities=["query_git_state", "request_read_only_what_if"],
            project_state_path=None,
            environment_state_path=None,
            servicetracer_report_path=None,
        )
        self.assertTrue(package["completeness"]["package_complete_for_bounded_query"])
        self.assertEqual(package["completeness"]["missing_required_sources"], [])
        helix_context.validate_query_package(package, now=NOW)

    def test_semantically_false_completeness_is_rejected_even_if_rehashed(self) -> None:
        package = self.build(environment_state_path=None)
        package["completeness"]["package_complete_for_bounded_query"] = True
        package.pop("integrity")
        package["integrity"] = {
            "algorithm": "sha256",
            "canonical_json_sha256": helix_context.canonical_sha256(package),
        }
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "completeness does not match"
        ):
            helix_context.validate_query_package(package, now=NOW)

    def test_rejects_service_tracer_exact_root_cause_claim(self) -> None:
        unsafe = copy.deepcopy(self.servicetracer)
        unsafe["investigation_boundary"]["exact_root_cause_claimed"] = True
        unsafe_path = self.write_json("unsafe.json", unsafe)
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "exact_root_cause_claimed=false"
        ):
            self.build(
                capabilities=["query_servicetracer_findings"],
                project_state_path=None,
                environment_state_path=None,
                servicetracer_report_path=unsafe_path,
            )

    def test_rejects_unknown_capability(self) -> None:
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "unsupported capability"
        ):
            self.build(capabilities=["ssh_root_shell"])

    def test_integrity_validation_detects_tampering(self) -> None:
        package = self.build()
        package["query"]["text"] = "tampered"
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "integrity hash mismatch"
        ):
            helix_context.validate_query_package(package, now=NOW)

    def test_duplicate_branch_ownership_is_rejected(self) -> None:
        duplicate = copy.deepcopy(self.project_state_v1)
        duplicate["workstreams"].append(copy.deepcopy(duplicate["workstreams"][0]))
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "duplicate workstream branch"
        ):
            helix_context.sanitize_project_state(duplicate)

    def test_accepts_public_servicetracer_envelope(self) -> None:
        envelope = {
            "schema_version": "servicetracer.public-report.v1",
            "source": {"id": "collector"},
            "report": self.servicetracer,
        }
        sanitized = helix_context.sanitize_servicetracer_report(envelope)
        self.assertEqual(
            sanitized["root_cause"]["status"],
            "not_determined_by_servicetracer",
        )


if __name__ == "__main__":
    unittest.main()
