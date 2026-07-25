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

import verify_cli


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def git_head_hash(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def configure_git_identity(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Verification Tests"],
        cwd=repo,
        check=True,
    )


def git_commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def prepare_hook_repo(repo: Path) -> None:
    git_init(repo)
    configure_git_identity(repo)
    (repo / ".githooks").mkdir()
    shutil.copy2(REPO_ROOT / "verify_cli.py", repo / "verify_cli.py")
    shutil.copy2(
        REPO_ROOT / ".githooks" / "pre-commit",
        repo / ".githooks" / "pre-commit",
    )
    os.chmod(repo / ".githooks" / "pre-commit", 0o755)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=repo,
        check=True,
    )


class PolicyParsingTests(unittest.TestCase):
    def test_parses_allowed_paths_block(self) -> None:
        policy = verify_cli.parse_policy_yaml(
            """
allowed_paths:
  - src
  - "docs/guides" # inline comment
protected_paths:
  - ".github/workflows/**"
  - deploy/**
metadata:
  owner: tests
"""
        )

        self.assertEqual(policy.allowed_paths, ("src", "docs/guides"))
        self.assertEqual(
            policy.protected_paths,
            (".github/workflows/**", "deploy/**"),
        )

    def test_rejects_empty_allowed_paths(self) -> None:
        with self.assertRaisesRegex(verify_cli.VerificationError, "cannot be empty"):
            verify_cli.parse_policy_yaml("allowed_paths: []\n")


class PlaceholderAssetTests(unittest.TestCase):
    def test_reports_zero_byte_files_under_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            assets_dir = repo / "assets" / "branding"
            assets_dir.mkdir(parents=True)
            empty_file = assets_dir / "logo.png"
            empty_file.write_bytes(b"")
            (assets_dir / "banner.png").write_bytes(b"ok")

            violations = verify_cli.empty_placeholder_asset_violations(repo)

        self.assertEqual(violations, ["empty placeholder asset: assets/branding/logo.png"])

    def test_ignores_missing_assets_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)

            violations = verify_cli.empty_placeholder_asset_violations(repo)

        self.assertEqual(violations, [])


class PathMatchingTests(unittest.TestCase):
    def test_allowed_path_matches_exact_file_or_child_path(self) -> None:
        allowed_paths = ("src", "README.md")

        self.assertTrue(verify_cli.is_allowed("src", allowed_paths))
        self.assertTrue(verify_cli.is_allowed("src/app.py", allowed_paths))
        self.assertTrue(verify_cli.is_allowed("README.md", allowed_paths))
        self.assertFalse(verify_cli.is_allowed("src-other/app.py", allowed_paths))
        self.assertFalse(verify_cli.is_allowed("README.md.bak", allowed_paths))

    def test_protected_path_patterns_match_staged_paths(self) -> None:
        violations = verify_cli.protected_path_violations(
            [".env", ".github/workflows/build.yml", "src/app.py"],
            [".github/workflows/**", "deploy/**", ".env"],
        )

        self.assertEqual(
            verify_cli.render_protected_violations(violations),
            [
                "protected path violation: .env matches .env",
                (
                    "protected path violation: .github/workflows/build.yml "
                    "matches .github/workflows/**"
                ),
            ],
        )


class AuditReportTests(unittest.TestCase):
    def test_render_audit_report_includes_required_sections(self) -> None:
        report = verify_cli.render_audit_report(
            timestamp="2026-05-20T02:48:00Z",
            repo=Path("/repo"),
            expected_branch="main",
            actual_branch="feature",
            changed_paths=["README.md", "src/app.py"],
            allowed_paths=["README.md"],
            violations=["branch mismatch: expected main, actual feature"],
            status_summary=[" M README.md"],
        )

        self.assertIn("# Verification Audit Report", report)
        self.assertIn("- Timestamp: 2026-05-20T02:48:00Z", report)
        self.assertIn("- Repo: /repo", report)
        self.assertIn("- Branch: feature", report)
        self.assertIn("- Expected Branch: main", report)
        self.assertIn("## Changed Files\n- README.md\n- src/app.py", report)
        self.assertIn("## Allowed Files\n- README.md", report)
        self.assertIn(
            "## Violations\n- branch mismatch: expected main, actual feature",
            report,
        )
        self.assertIn("## Git Status Summary\n```text\n M README.md\n```", report)


class PreCommitHookTests(unittest.TestCase):
    def test_pre_commit_hook_allows_commit_when_verification_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            prepare_hook_repo(repo)

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - .githooks/pre-commit\n"
                "  - allowed.txt\n"
                "  - policy.yaml\n"
                "  - session.json\n"
                "  - verify_cli.py\n",
                encoding="utf-8",
            )
            (repo / "allowed.txt").write_text("allowed\n", encoding="utf-8")

            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            commit = subprocess.run(
                ["git", "commit", "-m", "allowed commit"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            commit_output = commit.stdout + commit.stderr
            self.assertEqual(commit.returncode, 0, commit_output)
            self.assertIn("pre-commit verification: passed", commit_output)

    def test_pre_commit_hook_fails_commit_when_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            prepare_hook_repo(repo)

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - .githooks/pre-commit\n"
                "  - allowed.txt\n"
                "  - policy.yaml\n"
                "  - session.json\n"
                "  - verify_cli.py\n",
                encoding="utf-8",
            )
            (repo / "allowed.txt").write_text("allowed\n", encoding="utf-8")
            (repo / "blocked.txt").write_text("blocked\n", encoding="utf-8")

            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            commit = subprocess.run(
                ["git", "commit", "-m", "blocked commit"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            commit_output = commit.stdout + commit.stderr
            self.assertNotEqual(commit.returncode, 0)
            self.assertIn("verification:", commit_output)
            self.assertIn("blocked.txt", commit_output)
            self.assertIn(
                "pre-commit verification: failed; commit aborted",
                commit_output,
            )


class VerifyCliIntegrationTests(unittest.TestCase):
    def test_passes_without_session_when_session_argument_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)

            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - assets\n"
                "  - policy.yaml\n",
                encoding="utf-8",
            )
            (repo / "assets" / "branding").mkdir(parents=True)
            (repo / "assets" / "branding" / "logo.png").write_bytes(b"png")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = verify_cli.main(
                    [
                        "--policy",
                        str(repo / "policy.yaml"),
                        "--repo",
                        str(repo),
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("session: (not provided)", output)
            self.assertIn("expected: (not specified)", output)
            self.assertIn(
                f"verification: {verify_cli.GREEN}PASSED{verify_cli.RESET}",
                output,
            )

    def test_fails_when_explicit_session_path_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)

            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - policy.yaml\n",
                encoding="utf-8",
            )

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
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

            self.assertEqual(exit_code, 2)
            self.assertIn("session file not found", stderr.getvalue())

    def test_fails_when_asset_file_is_empty(self) -> None:
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
                "  - assets\n"
                "  - policy.yaml\n"
                "  - session.json\n",
                encoding="utf-8",
            )
            (repo / "assets" / "branding").mkdir(parents=True)
            (repo / "assets" / "branding" / "logo.png").write_bytes(b"")

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
            self.assertIn("empty placeholder asset: assets/branding/logo.png", output)
            self.assertIn(
                f"verification: {verify_cli.RED}FAILED{verify_cli.RESET}",
                output,
            )

    def test_passes_when_asset_files_are_non_empty(self) -> None:
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
                "  - assets\n"
                "  - policy.yaml\n"
                "  - session.json\n",
                encoding="utf-8",
            )
            (repo / "assets" / "branding").mkdir(parents=True)
            (repo / "assets" / "branding" / "logo.png").write_bytes(b"png")

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
            self.assertIn(
                f"verification: {verify_cli.GREEN}PASSED{verify_cli.RESET}",
                output,
            )

    def test_warns_for_protected_staged_paths_in_advisory_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - .env\n"
                "  - policy.yaml\n"
                "  - session.json\n"
                "protected_paths:\n"
                "  - .env\n",
                encoding="utf-8",
            )
            (repo / ".env").write_text("TOKEN=test\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            report_path = repo / "audit.md"

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
                        "--report",
                        str(report_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("protected paths:", output)
            self.assertIn(
                f"protected paths: {verify_cli.RED}WARNING{verify_cli.RESET}",
                output,
            )
            self.assertIn("protected mode: advisory", output)
            self.assertIn("protected path violation: .env matches .env", output)
            self.assertIn(
                f"verification: {verify_cli.GREEN}PASSED{verify_cli.RESET}",
                output,
            )

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("## Protected Path Violations", report)
            self.assertIn("- protected path violation: .env matches .env", report)

    def test_blocks_protected_staged_paths_in_enforce_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - deploy/app.yml\n"
                "  - policy.yaml\n"
                "  - session.json\n"
                "protected_paths:\n"
                "  - deploy/**\n",
                encoding="utf-8",
            )
            (repo / "deploy").mkdir()
            (repo / "deploy" / "app.yml").write_text("image: app\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)

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
                        "--protected-mode",
                        "enforce",
                    ]
                )

            self.assertEqual(exit_code, 1)
            output = stdout.getvalue()
            self.assertIn(
                f"protected paths: {verify_cli.RED}FAILED{verify_cli.RESET}",
                output,
            )
            self.assertIn("protected mode: enforce", output)
            self.assertIn(
                "protected path violation: deploy/app.yml matches deploy/**",
                output,
            )
            self.assertIn(
                f"verification: {verify_cli.RED}FAILED{verify_cli.RESET}",
                output,
            )

    def test_fails_when_session_context_branch_and_head_are_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)
            configure_git_identity(repo)
            (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
            git_commit_all(repo, "initial commit")
            actual_branch = git_current_branch(repo)

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - .contextos/session_context.json\n"
                "  - policy.yaml\n"
                "  - session.json\n",
                encoding="utf-8",
            )
            (repo / ".contextos").mkdir()
            (repo / ".contextos" / "session_context.json").write_text(
                json.dumps(
                    {
                        "branch": "feature/clientA",
                        "git_head_hash": "0" * 40,
                    },
                    sort_keys=True,
                )
                + "\n",
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
            self.assertIn("CONTEXT STALE", output)
            self.assertIn("- session created on feature/clientA", output)
            self.assertIn(
                f"- current branch is {actual_branch}",
                output,
            )
            self.assertIn("- HEAD changed after ingestion", output)
            self.assertIn("Suggested remediation:", output)
            self.assertIn("1. regenerate context packet", output)
            self.assertIn("2. run contextos ingest", output)
            self.assertIn("3. revalidate before commit", output)

    def test_fails_when_local_branch_is_behind_remote_tracking_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            remote = Path(temp_dir) / "remote.git"
            repo.mkdir()
            git_init(repo)
            configure_git_identity(repo)
            (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
            git_commit_all(repo, "initial commit")
            subprocess.run(
                ["git", "init", "--bare", str(remote)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "remote", "add", "origin", str(remote)],
                cwd=repo,
                check=True,
            )
            branch = git_current_branch(repo)
            subprocess.run(
                ["git", "push", "-u", "origin", branch],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            initial_head = git_head_hash(repo)

            (repo / "remote-change.txt").write_text("remote\n", encoding="utf-8")
            git_commit_all(repo, "remote change")
            subprocess.run(
                ["git", "push", "origin", branch],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "reset", "--hard", initial_head],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - .contextos/session_context.json\n"
                "  - policy.yaml\n"
                "  - session.json\n",
                encoding="utf-8",
            )
            (repo / ".contextos").mkdir()
            (repo / ".contextos" / "session_context.json").write_text(
                json.dumps(
                    {
                        "branch": branch,
                        "git_head_hash": initial_head,
                    },
                    sort_keys=True,
                )
                + "\n",
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
            self.assertIn("CONTEXT AGING", output)
            self.assertIn(
                f"- local branch is behind origin/{branch} by 1 commit",
                output,
            )

    def test_fails_when_repository_is_in_detached_head_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)
            configure_git_identity(repo)
            (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
            git_commit_all(repo, "initial commit")
            branch = git_current_branch(repo)
            head_hash = git_head_hash(repo)
            subprocess.run(
                ["git", "checkout", "--detach", head_hash],
                cwd=repo,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (repo / "session.json").write_text("{}\n", encoding="utf-8")
            (repo / "policy.yaml").write_text(
                "allowed_paths:\n"
                "  - .contextos/session_context.json\n"
                "  - policy.yaml\n"
                "  - session.json\n",
                encoding="utf-8",
            )
            (repo / ".contextos").mkdir()
            (repo / ".contextos" / "session_context.json").write_text(
                json.dumps(
                    {
                        "branch": branch,
                        "git_head_hash": head_hash,
                    },
                    sort_keys=True,
                )
                + "\n",
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
            self.assertIn("CONTEXT DIVERGED", output)
            self.assertIn(f"- session created on {branch}", output)
            self.assertIn("- current branch is (detached HEAD)", output)
            self.assertIn("- current repository is in detached HEAD state", output)

    def test_fails_when_status_contains_disallowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            git_init(repo)
            actual_branch = git_current_branch(repo)
            report_path = repo / "audit.md"

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
                        "--report",
                        str(report_path),
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
            self.assertIn(f"audit report: {report_path}", output)

            report = report_path.read_text(encoding="utf-8")
            self.assertRegex(
                report,
                r"- Timestamp: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            )
            self.assertIn(f"- Repo: {repo}", report)
            self.assertIn(f"- Branch: {actual_branch}", report)
            self.assertIn("## Changed Files", report)
            self.assertIn("- secret.txt", report)
            self.assertIn("## Allowed Files", report)
            self.assertIn("- src", report)
            self.assertIn("## Violations", report)
            self.assertIn(
                "- unauthorized file: secret.txt (not under allowed_paths)",
                report,
            )
            self.assertIn("## Git Status Summary", report)
            self.assertIn("?? secret.txt", report)

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
            self.assertIn("CONTEXT FRESH", output)
            self.assertIn("mismatch reasons:\n  (none)", output)
            self.assertIn("unauthorized files:\n  (none)", output)
            self.assertIn(
                f"verification: {verify_cli.GREEN}PASSED{verify_cli.RESET}",
                output,
            )


if __name__ == "__main__":
    unittest.main()
