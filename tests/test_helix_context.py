from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import helix_context


NOW = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)


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

        self.project_state = {
            "schema_version": "project.active-work.v1",
            "project": "ServiceTracer Azure MSP Lab",
            "updated_on": "2026-07-21",
            "trusted_baseline": {
                "branch": "main",
                "commit": "abc123",
                "last_completed_increment": {
                    "pull_request": 18,
                    "title": "Planner repair",
                },
            },
            "workstreams": [
                {
                    "workstream_id": "observer",
                    "branch": "feature/observer",
                    "pull_request": 21,
                    "write_owner": "observer-workstream",
                    "status": "planned",
                    "scope": "Build read-only evidence collection.",
                    "review_mode_for_other_conversations": "review_only",
                    "next_gate": "Human review",
                    "secret": "must-not-leak",
                }
            ],
            "known_open_pull_requests": [],
            "top_level_secret": "must-not-leak",
        }
        self.environment_state = {
            "schema_version": "project.environment-state.v1",
            "project": "ServiceTracer Azure MSP Lab",
            "updated_on": "2026-07-21",
            "facts": [
                {
                    "fact_id": "collector-vm-size",
                    "value": "Standard_B1ms",
                    "status": "operationally_verified",
                    "last_observed_on": "2026-07-20",
                    "source": "Azure verification",
                    "notes": "Known working size.",
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
                "backend_states": {"VPN-01": {"probe_status": "healthy"}},
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
        self.project_path = self.write_json("project.json", self.project_state)
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

    def build(self) -> dict:
        return helix_context.build_query_package(
            repo=self.root,
            query="Why is the collector migration blocked?",
            capabilities=[
                "query_project_state",
                "query_environment_facts",
                "query_servicetracer_findings",
                "query_git_state",
                "request_human_review",
            ],
            project_state_path=self.project_path,
            environment_state_path=self.environment_path,
            servicetracer_report_path=self.report_path,
            ttl_minutes=60,
            correlation_id="corr-test",
            now=NOW,
        )

    def test_builds_valid_bounded_package(self) -> None:
        package = self.build()
        self.assertEqual(package["schema_version"], helix_context.SCHEMA_VERSION)
        self.assertFalse(package["authority"]["mutation_authority"])
        self.assertEqual(
            package["evidence"]["servicetracer_finding"]["localization"][
                "suspect_backend"
            ],
            "VPN-02",
        )
        self.assertEqual(
            package["evidence"]["observed_environment_facts"]["facts"][0][
                "value"
            ],
            "Standard_B1ms",
        )
        self.assertNotIn("must-not-leak", json.dumps(package))
        helix_context.validate_query_package(package, now=NOW)

    def test_rejects_service_tracer_exact_root_cause_claim(self) -> None:
        unsafe = copy.deepcopy(self.servicetracer)
        unsafe["investigation_boundary"]["exact_root_cause_claimed"] = True
        unsafe_path = self.write_json("unsafe.json", unsafe)
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "exact_root_cause_claimed=false"
        ):
            helix_context.build_query_package(
                repo=self.root,
                query="What failed?",
                capabilities=["query_servicetracer_findings"],
                servicetracer_report_path=unsafe_path,
                now=NOW,
            )

    def test_rejects_unknown_capability(self) -> None:
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "unsupported capability"
        ):
            helix_context.build_query_package(
                repo=self.root,
                query="Do something",
                capabilities=["ssh_root_shell"],
                now=NOW,
            )

    def test_integrity_validation_detects_tampering(self) -> None:
        package = self.build()
        package["query"]["text"] = "tampered"
        with self.assertRaisesRegex(
            helix_context.HelixContextError, "integrity hash mismatch"
        ):
            helix_context.validate_query_package(package, now=NOW)

    def test_duplicate_branch_ownership_is_rejected(self) -> None:
        duplicate = copy.deepcopy(self.project_state)
        duplicate["workstreams"].append(
            copy.deepcopy(duplicate["workstreams"][0])
        )
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
