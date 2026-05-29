from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import contextos


def git_init(repo: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def configure_git_identity(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "ContextOS Tests"],
        cwd=repo,
        check=True,
    )


def git_current_branch(repo: Path) -> str:
    return subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def git_head_hash(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def prepare_repo(repo: Path) -> None:
    git_init(repo)
    configure_git_identity(repo)
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class ContextPacketParsingTests(unittest.TestCase):
    def test_load_context_packet_validates_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet_path = Path(temp_dir) / "context_packet.yaml"
            packet_path.write_text(
                "project: ContextOS\n"
                "repo: test-repo\n"
                "branch: main\n"
                "task: Add ingest\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(contextos.ContextOSError, "allowed_paths"):
                contextos.load_context_packet(packet_path)


class ContextosIngestTests(unittest.TestCase):
    def test_ingest_writes_session_context_when_packet_matches_git_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            head_hash = git_head_hash(repo)
            packet_path = repo / "context_packet.yaml"
            packet_path.write_text(
                "project: ContextOS\n"
                "repo: ContextOS\n"
                f"branch: {branch}\n"
                "task: Convert reviewed context\n"
                "allowed_paths:\n"
                "  - README.md\n"
                "  - src\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "ingest",
                        str(packet_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("contextos ingest: PASSED", output)
            self.assertIn("session context:", output)

            session_context_path = repo / ".contextos" / "session_context.json"
            session_context = json.loads(
                session_context_path.read_text(encoding="utf-8")
            )
            self.assertRegex(
                session_context["timestamp"],
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            )
            self.assertEqual(session_context["git_head_hash"], head_hash)
            self.assertEqual(session_context["source"], "chatgpt_context_packet")
            self.assertEqual(session_context["repo"], "ContextOS")
            self.assertEqual(session_context["branch"], branch)
            self.assertEqual(session_context["allowed_paths"], ["README.md", "src"])

    def test_ingest_fails_clearly_when_repo_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            packet_path = repo / "context_packet.yaml"
            packet_path.write_text(
                "project: ContextOS\n"
                "repo: OtherRepo\n"
                f"branch: {branch}\n"
                "task: Convert reviewed context\n"
                "allowed_paths:\n"
                "  - README.md\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "ingest",
                        str(packet_path),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("contextos ingest: FAILED", stdout.getvalue())
            self.assertIn(
                "repo mismatch: expected OtherRepo, actual ContextOS",
                stdout.getvalue(),
            )
            self.assertIn(
                "context packet does not match current Git context",
                stderr.getvalue(),
            )
            self.assertFalse((repo / ".contextos" / "session_context.json").exists())

    def test_ingest_fails_clearly_when_branch_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            packet_path = repo / "context_packet.yaml"
            packet_path.write_text(
                "project: ContextOS\n"
                "repo: ContextOS\n"
                f"branch: {branch}-expected\n"
                "task: Convert reviewed context\n"
                "allowed_paths:\n"
                "  - README.md\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "ingest",
                        str(packet_path),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("contextos ingest: FAILED", stdout.getvalue())
            self.assertIn(
                f"branch mismatch: expected {branch}-expected, actual {branch}",
                stdout.getvalue(),
            )
            self.assertIn(
                "context packet does not match current Git context",
                stderr.getvalue(),
            )
            self.assertFalse((repo / ".contextos" / "session_context.json").exists())


class ContextosVerifyTests(unittest.TestCase):
    def test_verify_wrapper_runs_verification_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            git_init(repo)
            branch = git_current_branch(repo)
            (repo / "session.json").write_text(
                f'{{"expected_branch":"{branch}"}}\n',
                encoding="utf-8",
            )
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - policy.yaml\n"
                "  - session.json\n"
                "  - project_plan.yaml\n",
                encoding="utf-8",
            )
            shutil.copy2(
                Path(__file__).resolve().parents[1] / "project_plan.yaml",
                repo / "project_plan.yaml",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "verify",
                        "--session",
                        str(repo / "session.json"),
                        "--policy",
                        str(repo / "policy.yaml"),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("CONTEXT FRESH", stdout.getvalue())
            self.assertIn("verification:", stdout.getvalue())


class ExplainGitTests(unittest.TestCase):
    def test_explain_git_renders_terminal_output(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = contextos.main(["explain-git", "git", "status"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Recommended:\ngit status", output)
        self.assertIn("Explanation:", output)
        self.assertIn("Risk:\nREAD_ONLY", output)
        self.assertIn("Changes state:\nno", output)

    def test_explain_git_renders_markdown_output(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = contextos.main(
                [
                    "explain-git",
                    "--format",
                    "markdown",
                    "git",
                    "reset",
                    "--hard",
                    "HEAD",
                ]
            )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("### Recommended Git command", output)
        self.assertIn("git reset --hard HEAD", output)
        self.assertIn("**Risk:** `DESTRUCTIVE`", output)
        self.assertIn("**Changes state:** yes", output)

    def test_explain_git_fails_for_unknown_command(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = contextos.main(["explain-git", "git", "unknown-command"])

        self.assertEqual(exit_code, 2)
        self.assertIn(
            "no deterministic explanation is registered",
            stderr.getvalue(),
        )


class CreateIssueTests(unittest.TestCase):
    def write_issue_packet(self, path: Path, branch: str = "main") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "project: ContextOS\n"
            "repo: ContextOS\n"
            f"branch: {branch}\n"
            "task: Add issue bridge\n"
            "objective: Coordinate ChatGPT and Cursor through GitHub Issues.\n"
            "allowed_paths:\n"
            "  - README.md\n"
            "  - contextos.py\n"
            "protected_paths:\n"
            "  - .env\n"
            "assumptions:\n"
            "  - GitHub Issue markdown is generated locally first.\n"
            "risks:\n"
            "  - Branch may become stale before implementation.\n"
            "acceptance_criteria:\n"
            "  - Generated markdown includes freshness metadata.\n",
            encoding="utf-8",
        )

    def test_load_issue_packet_validates_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet_path = Path(temp_dir) / "issue_packet.yaml"
            packet_path.write_text(
                "project: ContextOS\n"
                "repo: ContextOS\n"
                "branch: main\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(contextos.ContextOSError, "objective"):
                contextos.load_issue_packet(packet_path)

    def test_create_issue_generates_markdown_and_audit_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            packet_path = repo / ".contextos" / "issue_packet.yaml"
            self.write_issue_packet(packet_path, branch)
            output_path = repo / ".contextos" / "audit" / "generated_issue.md"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "create-issue",
                        "--packet",
                        str(packet_path),
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("# Add issue bridge", output)
            self.assertIn("## Context freshness", output)
            self.assertIn(f"- Current branch: {branch}", output)
            self.assertIn("- Freshness classification: FRESH", output)
            self.assertIn("No GitHub API call was made by ContextOS", output)
            self.assertTrue(output_path.exists())
            self.assertIn("## Required verification steps", output_path.read_text())
            self.assertTrue(
                any(
                    (repo / ".contextos" / "audit" / "issue_packets").glob(
                        "*_issue_packet.yaml"
                    )
                )
            )
            self.assertTrue(
                any(
                    (repo / ".contextos" / "audit" / "generated_issues").glob(
                        "*_issue.md"
                    )
                )
            )

    def test_create_issue_marks_stale_when_branch_mismatches_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            packet_path = repo / ".contextos" / "issue_packet.yaml"
            self.write_issue_packet(packet_path, "feature/clientA")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "create-issue",
                        "--packet",
                        str(packet_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("- Freshness classification: STALE", output)
            self.assertIn("- issue packet expects branch feature/clientA", output)
            self.assertIn("- current branch is", output)


class ExportLastPlanTests(unittest.TestCase):
    def write_execution_result(self, path: Path, task_name: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {task_name}\n\n"
            "## Original objective\n"
            "Export the latest Cursor plan for ChatGPT review.\n\n"
            "## Implementation summary\n"
            "- Added a read-only export command.\n\n"
            "## Files changed\n"
            "- contextos.py\n"
            "- tests/test_contextos.py\n\n"
            "## Tests run\n"
            "- python3 -m unittest discover -s tests\n\n"
            "## Test results\n"
            "PASS\n\n"
            "## Policy/verification result\n"
            "Verification passed locally.\n\n"
            "## Unresolved issues\n"
            "- None.\n\n"
            "## Recommended next action\n"
            "Review the generated summary before approving follow-up work.\n\n"
            "## Recommended Git commands\n"
            "- git status\n"
            "- git push -u origin feature/export\n\n"
            "## Human approval required\n"
            "Yes. Human review is required before merge.\n",
            encoding="utf-8",
        )

    def test_export_last_plan_uses_execution_result_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            self.write_execution_result(
                repo / ".contextos" / "execution_result.md",
                "Export latest plan",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "export-last-plan",
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("# Last executed Cursor plan overview", output)
            self.assertIn("## Plan/task name\nExport latest plan", output)
            self.assertIn("## Original objective", output)
            self.assertIn("## Files changed", output)
            self.assertIn("## Git status summary", output)
            self.assertIn("## Policy/verification result", output)
            self.assertIn("## Recommended Git command explanations", output)
            self.assertIn("### `git status`", output)
            self.assertIn("Risk: `READ_ONLY`", output)
            self.assertIn("### `git push -u origin <branch>`", output)
            self.assertIn("Risk: `REMOTE_CHANGING`", output)
            self.assertIn("## Human approval required\nYes.", output)
            self.assertIn("No Git state was changed.", output)

    def test_export_last_plan_fails_when_no_execution_result_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "export-last-plan",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("No execution result found", stderr.getvalue())
            self.assertIn(".contextos/execution_result.md", stderr.getvalue())

    def test_export_last_plan_chooses_most_recent_audit_execution_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            old_result = repo / ".contextos" / "execution_result.md"
            new_result = (
                repo
                / ".contextos"
                / "audit"
                / "execution_results"
                / "latest.md"
            )
            self.write_execution_result(old_result, "Old plan")
            self.write_execution_result(new_result, "New plan")
            os.utime(old_result, (1, 1))
            os.utime(new_result, (2, 2))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "export-last-plan",
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("## Plan/task name\nNew plan", output)
            self.assertNotIn("## Plan/task name\nOld plan", output)


class RequestSwitchTests(unittest.TestCase):
    def prepare_switch_repo(self, repo: Path) -> tuple[str, str]:
        prepare_repo(repo)
        branch = git_current_branch(repo)
        head = git_head_hash(repo)
        subprocess.run(
            ["git", "checkout", "-b", "feature/clientA"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "checkout", branch],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return branch, head

    def request_args(self, repo: Path, branch: str, head: str) -> list[str]:
        return [
            "request-switch",
            "--target-repo",
            str(repo),
            "--target-branch",
            "feature/clientA",
            "--reason",
            "Continue reviewed Client A work.",
            "--requested-by",
            "ChatGPT",
            "--source-context",
            "issue-123",
            "--expected-current-branch",
            branch,
            "--expected-current-head",
            head,
        ]

    def test_request_switch_dry_run_writes_report_without_switching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            branch, head = self.prepare_switch_repo(repo)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(self.request_args(repo, branch, head))

            self.assertEqual(exit_code, 0)
            self.assertEqual(git_current_branch(repo), branch)
            output = stdout.getvalue()
            self.assertIn("# ContextOS repo-state switch request", output)
            self.assertIn("- Human approval provided: no", output)
            self.assertIn("- git switch feature/clientA", output)
            self.assertIn("### `git switch <branch>`", output)
            self.assertIn("Not executed. Explicit human approval is required.", output)
            self.assertTrue((repo / ".contextos" / "state_switch_report.md").exists())
            self.assertTrue(
                any(
                    (repo / ".contextos" / "audit" / "state_switches").glob(
                        "*_state_switch_report.md"
                    )
                )
            )

    def test_request_switch_approval_is_blocked_when_working_tree_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            branch, head = self.prepare_switch_repo(repo)
            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        *self.request_args(repo, branch, head),
                        "--approve",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(git_current_branch(repo), branch)
            output = stdout.getvalue()
            self.assertIn("working tree is dirty; automatic switching is blocked", output)
            self.assertIn("Recommended safe read-only commands first", output)
            self.assertIn("git status", output)
            self.assertIn(
                "Not executed. Validation failed; state-changing commands were blocked.",
                output,
            )

    def test_request_switch_approval_executes_when_validation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            branch, head = self.prepare_switch_repo(repo)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        *self.request_args(repo, branch, head),
                        "--approve",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(git_current_branch(repo), "feature/clientA")
            output = stdout.getvalue()
            self.assertIn("- Human approval provided: yes", output)
            self.assertIn("Executed. Current branch verified after switch.", output)
            self.assertIn("## Git state after execution", output)


class VerifyFreshnessTests(unittest.TestCase):
    def write_plan(
        self,
        path: Path,
        *,
        branch: str,
        head: str,
        timestamp: str = "2999-01-01T00:00:00Z",
        scope: tuple[str, ...] = ("README.md",),
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        scope_lines = "\n".join(f"- {item}" for item in scope)
        path.write_text(
            "# Freshness checked plan\n\n"
            "## Original objective\n"
            "Validate execution context before continuing.\n\n"
            "## Plan timestamp\n"
            f"{timestamp}\n\n"
            "## Expected branch\n"
            f"{branch}\n\n"
            "## Expected HEAD\n"
            f"{head}\n\n"
            "## Expected files/scope\n"
            f"{scope_lines}\n\n"
            "## Last verified branch\n"
            f"{branch}\n\n"
            "## Last verified HEAD\n"
            f"{head}\n\n"
            "## Last verified repo state\n"
            "Clean working tree at plan creation.\n",
            encoding="utf-8",
        )

    def test_verify_freshness_reports_fresh_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            head = git_head_hash(repo)
            plan = repo / ".contextos" / "execution_plan.md"
            self.write_plan(plan, branch=branch, head=head)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    ["--repo", str(repo), "verify-freshness", "--plan", str(plan)]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("## Classification\nFRESH", output)
            self.assertIn("## Re-planning recommended\nno", output)
            self.assertIn("## Execution should be blocked\nno", output)
            self.assertTrue((repo / ".contextos" / "freshness_report.md").exists())
            self.assertTrue(
                any(
                    (repo / ".contextos" / "audit" / "freshness_reports").glob(
                        "*_freshness_report.md"
                    )
                )
            )

    def test_verify_freshness_reports_aging_for_in_scope_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            head = git_head_hash(repo)
            plan = repo / ".contextos" / "execution_plan.md"
            self.write_plan(plan, branch=branch, head=head, scope=("README.md",))
            (repo / "README.md").write_text("# Changed\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    ["--repo", str(repo), "verify-freshness", "--plan", str(plan)]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("## Classification\nAGING", output)
            self.assertIn("local working tree has staged, unstaged, or untracked changes", output)
            self.assertIn("## Execution should be blocked\nno", output)

    def test_verify_freshness_reports_stale_for_old_plan_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            head = git_head_hash(repo)
            plan = repo / ".contextos" / "execution_plan.md"
            self.write_plan(
                plan,
                branch=branch,
                head=head,
                timestamp="2000-01-01T00:00:00Z",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    [
                        "--repo",
                        str(repo),
                        "verify-freshness",
                        "--plan",
                        str(plan),
                        "--freshness-threshold-hours",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 1)
            output = stdout.getvalue()
            self.assertIn("## Classification\nSTALE", output)
            self.assertIn("execution plan timestamp exceeded freshness threshold", output)
            self.assertIn("## Re-planning recommended\nyes", output)

    def test_verify_freshness_reports_diverged_for_unauthorized_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ContextOS"
            repo.mkdir()
            prepare_repo(repo)
            branch = git_current_branch(repo)
            head = git_head_hash(repo)
            plan = repo / ".contextos" / "execution_plan.md"
            self.write_plan(plan, branch=branch, head=head, scope=("README.md",))
            (repo / "deploy.yml").write_text("replicas: 2\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = contextos.main(
                    ["--repo", str(repo), "verify-freshness", "--plan", str(plan)]
                )

            self.assertEqual(exit_code, 1)
            output = stdout.getvalue()
            self.assertIn("## Classification\nDIVERGED", output)
            self.assertIn("unauthorized file modification: deploy.yml", output)
            self.assertIn("## Execution should be blocked\nyes", output)


if __name__ == "__main__":
    unittest.main()
