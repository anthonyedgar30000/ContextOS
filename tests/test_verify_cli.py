from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

import verify_cli


def git_init(repo: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_current_branch(repo: Path) -> str:
    return subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class PolicyParsingTests(unittest.TestCase):
    def test_parses_allowed_paths_block(self) -> None:
        policy = verify_cli.parse_policy_yaml(
            """
allowed_paths:
  - src
  - "docs/guides" # inline comment
metadata:
  owner: tests
"""
        )

        self.assertEqual(policy.allowed_paths, ("src", "docs/guides"))

    def test_rejects_empty_allowed_paths(self) -> None:
        with self.assertRaisesRegex(verify_cli.VerificationError, "cannot be empty"):
            verify_cli.parse_policy_yaml("allowed_paths: []\n")


class PathMatchingTests(unittest.TestCase):
    def test_allowed_path_matches_exact_file_or_child_path(self) -> None:
        allowed_paths = ("src", "README.md")

        self.assertTrue(verify_cli.is_allowed("src", allowed_paths))
        self.assertTrue(verify_cli.is_allowed("src/app.py", allowed_paths))
        self.assertTrue(verify_cli.is_allowed("README.md", allowed_paths))
        self.assertFalse(verify_cli.is_allowed("src-other/app.py", allowed_paths))
        self.assertFalse(verify_cli.is_allowed("README.md.bak", allowed_paths))


class VerifyCliIntegrationTests(unittest.TestCase):
    def test_fails_when_status_contains_disallowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)
            actual_branch = git_current_branch(repo)

            (repo / "session.json").write_text(
                f'{{"expected_branch":"{actual_branch}"}}\n',
                encoding="utf-8",
            )
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - session.json\n"
                "  - policy.yaml\n"
                "  - src\n",
                encoding="utf-8",
            )
            (repo / "src").mkdir()
            (repo / "src" / "allowed.txt").write_text("allowed\n", encoding="utf-8")
            (repo / "secret.txt").write_text("blocked\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = verify_cli.main(
                    [
                        "--session",
                        str(repo / "session.json"),
                        "--policy",
                        str(repo / "policy.yaml"),
                        "--repo",
                        str(repo),
                    ]
                )

            self.assertEqual(exit_code, 1)
            output = stdout.getvalue()
            self.assertIn(f"expected: {actual_branch}", output)
            self.assertIn(f"actual: {actual_branch}", output)
            self.assertIn("mismatch reasons:", output)
            self.assertIn(
                "unauthorized file: secret.txt (not under allowed_paths)",
                output,
            )
            self.assertIn("unauthorized files:", output)
            self.assertIn("secret.txt", output)
            self.assertIn(
                f"verification: {verify_cli.RED}FAILED{verify_cli.RESET}",
                output,
            )

    def test_fails_when_expected_branch_does_not_match_actual_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)
            actual_branch = git_current_branch(repo)
            expected_branch = f"{actual_branch}-expected"

            (repo / "session.json").write_text(
                f'{{"expected_branch":"{expected_branch}"}}\n',
                encoding="utf-8",
            )
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - session.json\n"
                "  - policy.yaml\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = verify_cli.main(
                    [
                        "--session",
                        str(repo / "session.json"),
                        "--policy",
                        str(repo / "policy.yaml"),
                        "--repo",
                        str(repo),
                    ]
                )

            self.assertEqual(exit_code, 1)
            output = stdout.getvalue()
            self.assertIn(f"expected: {expected_branch}", output)
            self.assertIn(f"actual: {actual_branch}", output)
            self.assertIn(
                f"branch mismatch: expected {expected_branch}, actual {actual_branch}",
                output,
            )
            self.assertIn("unauthorized files:\n  (none)", output)
            self.assertIn(
                f"verification: {verify_cli.RED}FAILED{verify_cli.RESET}",
                output,
            )

    def test_pass_output_is_colorized_and_lists_no_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)
            actual_branch = git_current_branch(repo)

            (repo / "session.json").write_text(
                f'{{"expected_branch":"{actual_branch}"}}\n',
                encoding="utf-8",
            )
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - session.json\n"
                "  - policy.yaml\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = verify_cli.main(
                    [
                        "--session",
                        str(repo / "session.json"),
                        "--policy",
                        str(repo / "policy.yaml"),
                        "--repo",
                        str(repo),
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn(f"expected: {actual_branch}", output)
            self.assertIn(f"actual: {actual_branch}", output)
            self.assertIn("mismatch reasons:\n  (none)", output)
            self.assertIn("unauthorized files:\n  (none)", output)
            self.assertIn(
                f"verification: {verify_cli.GREEN}PASSED{verify_cli.RESET}",
                output,
            )


if __name__ == "__main__":
    unittest.main()
