from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import install_hooks


REPO_ROOT = Path(__file__).resolve().parents[1]


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
        ["git", "config", "user.name", "Hook Installer Tests"],
        cwd=repo,
        check=True,
    )


def prepare_contextos_repo(repo: Path, protected_mode: str = "enforce") -> None:
    git_init(repo)
    configure_git_identity(repo)
    shutil.copy2(REPO_ROOT / "verify_cli.py", repo / "verify_cli.py")
    (repo / "session.json").write_text("{}\n", encoding="utf-8")
    (repo / "policy.yaml").write_text(
        "allowed_paths:\n"
        "  - deploy/production.yml\n"
        "  - policy.yaml\n"
        "  - session.json\n"
        "  - verify_cli.py\n"
        "protected_paths:\n"
        "  - deploy/**\n",
        encoding="utf-8",
    )
    install_hooks.install_hook(repo, protected_mode)


class InstallHooksTests(unittest.TestCase):
    def test_install_hook_writes_executable_pre_commit_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)

            hook_path = install_hooks.install_hook(repo, "advisory")

            self.assertEqual(hook_path, repo / ".git" / "hooks" / "pre-commit")
            self.assertTrue(os.access(hook_path, os.X_OK))
            hook = hook_path.read_text(encoding="utf-8")
            self.assertIn("python3 \"$verify_cli\"", hook)
            self.assertIn("--protected-mode advisory", hook)
            self.assertIn("Suggested remediation:", hook)

    def test_installed_enforce_hook_blocks_commit_on_verification_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            prepare_contextos_repo(repo, "enforce")
            (repo / "deploy").mkdir()
            (repo / "deploy" / "production.yml").write_text(
                "replicas: 4\n",
                encoding="utf-8",
            )

            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            commit = subprocess.run(
                ["git", "commit", "-m", "deploy change"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            output = commit.stdout + commit.stderr
            self.assertNotEqual(commit.returncode, 0)
            self.assertIn(
                "ContextOS pre-commit: verification failed; commit blocked",
                output,
            )
            self.assertIn("Suggested remediation:", output)
            self.assertIn("run: ./contextos ingest context_packet.yaml", output)
            self.assertIn(
                "protected path violation: deploy/production.yml matches deploy/**",
                output,
            )

    def test_installed_advisory_hook_allows_protected_path_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            prepare_contextos_repo(repo, "advisory")
            (repo / "deploy").mkdir()
            (repo / "deploy" / "production.yml").write_text(
                "replicas: 4\n",
                encoding="utf-8",
            )

            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            commit = subprocess.run(
                ["git", "commit", "-m", "deploy change"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            output = commit.stdout + commit.stderr
            self.assertEqual(commit.returncode, 0, output)
            self.assertIn("protected mode: advisory", output)
            self.assertIn("ContextOS pre-commit: verification passed", output)


if __name__ == "__main__":
    unittest.main()
