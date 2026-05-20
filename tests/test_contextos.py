from __future__ import annotations

import contextlib
import io
import json
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


if __name__ == "__main__":
    unittest.main()
