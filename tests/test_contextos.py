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


if __name__ == "__main__":
    unittest.main()
