"""Deterministic explanations for recommended Git commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Sequence


class GitCommandExplanationError(Exception):
    """Raised when a Git command cannot be explained deterministically."""


@dataclass(frozen=True)
class GitCommandExplanation:
    command: str
    explanation: str
    risk: str
    consequences: str
    changes_state: bool


READ_ONLY = "READ_ONLY"
STATE_CHANGING = "STATE_CHANGING"
REMOTE_CHANGING = "REMOTE_CHANGING"
DESTRUCTIVE = "DESTRUCTIVE"


GIT_COMMAND_EXPLANATIONS: dict[str, GitCommandExplanation] = {
    "git status": GitCommandExplanation(
        command="git status",
        explanation=(
            "Shows current repository state including modified files, staged "
            "files, untracked files, and branch status."
        ),
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git status --short --branch": GitCommandExplanation(
        command="git status --short --branch",
        explanation=(
            "Shows a compact repository status with branch information and "
            "short file-state markers."
        ),
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git diff --name-only": GitCommandExplanation(
        command="git diff --name-only",
        explanation=(
            "Lists files with unstaged changes compared with the current index."
        ),
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git diff --cached --name-only": GitCommandExplanation(
        command="git diff --cached --name-only",
        explanation=(
            "Lists staged files that would be included in the next commit."
        ),
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git branch --show-current": GitCommandExplanation(
        command="git branch --show-current",
        explanation="Prints the current branch name, or nothing in detached HEAD state.",
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git rev-parse HEAD": GitCommandExplanation(
        command="git rev-parse HEAD",
        explanation="Prints the commit hash currently checked out as HEAD.",
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git rev-parse --show-toplevel": GitCommandExplanation(
        command="git rev-parse --show-toplevel",
        explanation="Prints the absolute path to the repository root.",
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git rev-parse --abbrev-ref --symbolic-full-name @{u}": GitCommandExplanation(
        command="git rev-parse --abbrev-ref --symbolic-full-name @{u}",
        explanation="Prints the upstream branch configured for the current branch.",
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git rev-list --left-right --count HEAD...@{u}": GitCommandExplanation(
        command="git rev-list --left-right --count HEAD...@{u}",
        explanation=(
            "Counts commits that local HEAD and its upstream have independently."
        ),
        risk=READ_ONLY,
        consequences="No repository files, refs, or remotes are changed.",
        changes_state=False,
    ),
    "git add .": GitCommandExplanation(
        command="git add .",
        explanation="Stages changes under the current directory for the next commit.",
        risk=STATE_CHANGING,
        consequences=(
            "The Git index changes. No commit is created and no remote is updated."
        ),
        changes_state=True,
    ),
    "git add <path>": GitCommandExplanation(
        command="git add <path>",
        explanation="Stages the specified path for the next commit.",
        risk=STATE_CHANGING,
        consequences=(
            "The Git index changes. No commit is created and no remote is updated."
        ),
        changes_state=True,
    ),
    "git commit -m <message>": GitCommandExplanation(
        command="git commit -m <message>",
        explanation="Creates a new local commit from staged changes.",
        risk=STATE_CHANGING,
        consequences=(
            "A new local commit is created. Remote branches are unchanged until push."
        ),
        changes_state=True,
    ),
    "git checkout <branch>": GitCommandExplanation(
        command="git checkout <branch>",
        explanation="Switches the working tree to the specified branch.",
        risk=STATE_CHANGING,
        consequences=(
            "HEAD and working tree state can change. Uncommitted changes may "
            "conflict with the checkout."
        ),
        changes_state=True,
    ),
    "git checkout -b <branch>": GitCommandExplanation(
        command="git checkout -b <branch>",
        explanation="Creates a new branch and checks it out.",
        risk=STATE_CHANGING,
        consequences="A new local branch is created and HEAD moves to that branch.",
        changes_state=True,
    ),
    "git switch <branch>": GitCommandExplanation(
        command="git switch <branch>",
        explanation="Switches the working tree and HEAD to the specified branch.",
        risk=STATE_CHANGING,
        consequences=(
            "HEAD and working tree state can change. Uncommitted changes may "
            "conflict with the switch."
        ),
        changes_state=True,
    ),
    "git fetch": GitCommandExplanation(
        command="git fetch",
        explanation="Downloads remote refs and objects without changing the working tree.",
        risk=STATE_CHANGING,
        consequences=(
            "Local remote-tracking refs can change. Checked-out files and local "
            "commits are not modified."
        ),
        changes_state=True,
    ),
    "git config core.hooksPath .githooks": GitCommandExplanation(
        command="git config core.hooksPath .githooks",
        explanation=(
            "Configures this repository to load Git hooks from the tracked "
            ".githooks directory."
        ),
        risk=STATE_CHANGING,
        consequences=(
            "Local repository configuration changes. Future Git commands can "
            "run hooks from .githooks."
        ),
        changes_state=True,
    ),
    "git push -u origin <branch>": GitCommandExplanation(
        command="git push -u origin <branch>",
        explanation=(
            "Pushes a local branch to origin and sets it as the upstream branch."
        ),
        risk=REMOTE_CHANGING,
        consequences="Remote refs can change and future pulls/pushes track origin.",
        changes_state=True,
    ),
    "git push origin <branch>": GitCommandExplanation(
        command="git push origin <branch>",
        explanation="Pushes the local branch state to the origin remote.",
        risk=REMOTE_CHANGING,
        consequences="Remote refs can change for other collaborators.",
        changes_state=True,
    ),
    "git reset --hard HEAD": GitCommandExplanation(
        command="git reset --hard HEAD",
        explanation=(
            "Resets tracked files to the latest commit and permanently discards "
            "uncommitted tracked-file changes."
        ),
        risk=DESTRUCTIVE,
        consequences=(
            "Uncommitted tracked-file changes are lost. Untracked files are not removed."
        ),
        changes_state=True,
    ),
}


def normalize_git_command(command: str | Sequence[str]) -> str:
    if isinstance(command, str):
        parts = shlex.split(command)
    else:
        parts = list(command)

    if not parts:
        raise GitCommandExplanationError("Git command cannot be empty")
    if parts[0] != "git":
        parts = ["git", *parts]

    return " ".join(parts)


def canonical_git_command(command: str | Sequence[str]) -> str:
    normalized = normalize_git_command(command)
    parts = normalized.split()

    if parts[:2] == ["git", "add"] and len(parts) >= 3 and parts[2] != ".":
        return "git add <path>"
    if parts[:3] == ["git", "commit", "-m"] and len(parts) >= 4:
        return "git commit -m <message>"
    if parts[:2] == ["git", "checkout"] and len(parts) == 3:
        return "git checkout <branch>"
    if parts[:3] == ["git", "checkout", "-b"] and len(parts) == 4:
        return "git checkout -b <branch>"
    if parts[:2] == ["git", "switch"] and len(parts) == 3:
        return "git switch <branch>"
    if parts[:4] == ["git", "push", "-u", "origin"] and len(parts) == 5:
        return "git push -u origin <branch>"
    if parts[:3] == ["git", "push", "origin"] and len(parts) == 4:
        return "git push origin <branch>"
    if parts[:4] == ["git", "rev-list", "--left-right", "--count"] and len(parts) == 5:
        return "git rev-list --left-right --count HEAD...@{u}"

    return normalized


def explain_git_command(command: str | Sequence[str]) -> GitCommandExplanation:
    canonical = canonical_git_command(command)
    explanation = GIT_COMMAND_EXPLANATIONS.get(canonical)
    if explanation is None:
        raise GitCommandExplanationError(
            f"no deterministic explanation is registered for: {normalize_git_command(command)}"
        )
    return explanation


def render_terminal_explanation(explanation: GitCommandExplanation) -> str:
    changes_state = "yes" if explanation.changes_state else "no"
    return "\n".join(
        [
            "Recommended:",
            explanation.command,
            "",
            "Explanation:",
            explanation.explanation,
            "",
            "Risk:",
            explanation.risk,
            "",
            "Potential consequences:",
            explanation.consequences,
            "",
            "Changes state:",
            changes_state,
        ]
    )


def render_markdown_explanation(explanation: GitCommandExplanation) -> str:
    changes_state = "yes" if explanation.changes_state else "no"
    return "\n".join(
        [
            "### Recommended Git command",
            "",
            "```sh",
            explanation.command,
            "```",
            "",
            f"**Explanation:** {explanation.explanation}",
            "",
            f"**Risk:** `{explanation.risk}`",
            "",
            f"**Potential consequences:** {explanation.consequences}",
            "",
            f"**Changes state:** {changes_state}",
        ]
    )
