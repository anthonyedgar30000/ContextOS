from __future__ import annotations

import unittest

import git_command_explanations as explanations


class GitCommandExplanationTests(unittest.TestCase):
    def test_known_read_only_command_has_terminal_explanation(self) -> None:
        explanation = explanations.explain_git_command("git status")

        self.assertEqual(explanation.risk, explanations.READ_ONLY)
        self.assertFalse(explanation.changes_state)
        rendered = explanations.render_terminal_explanation(explanation)
        self.assertIn("Recommended:\ngit status", rendered)
        self.assertIn("Risk:\nREAD_ONLY", rendered)
        self.assertIn("Changes state:\nno", rendered)

    def test_destructive_command_has_markdown_explanation(self) -> None:
        explanation = explanations.explain_git_command("git reset --hard HEAD")

        self.assertEqual(explanation.risk, explanations.DESTRUCTIVE)
        self.assertTrue(explanation.changes_state)
        rendered = explanations.render_markdown_explanation(explanation)
        self.assertIn("```sh\ngit reset --hard HEAD\n```", rendered)
        self.assertIn("**Risk:** `DESTRUCTIVE`", rendered)
        self.assertIn("permanently discards uncommitted tracked-file changes", rendered)

    def test_parameterized_command_uses_canonical_mapping(self) -> None:
        explanation = explanations.explain_git_command(
            ["git", "push", "-u", "origin", "feature/clientA"]
        )

        self.assertEqual(explanation.command, "git push -u origin <branch>")
        self.assertEqual(explanation.risk, explanations.REMOTE_CHANGING)

    def test_unknown_command_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            explanations.GitCommandExplanationError,
            "no deterministic explanation",
        ):
            explanations.explain_git_command("git reflog expire")


if __name__ == "__main__":
    unittest.main()
