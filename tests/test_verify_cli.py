from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

import verify_cli


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
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE)

            (repo / "session.json").write_text('{"session":"test"}\n', encoding="utf-8")
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
            self.assertIn("verification: FAILED", output)
            self.assertIn("secret.txt", output)


if __name__ == "__main__":
    unittest.main()
