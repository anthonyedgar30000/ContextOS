# Cursor response template

## Proposed implementation plan

- Summarize the intended local implementation steps.
- Identify which ContextOS contracts are being used.
- Confirm whether the current branch matches the issue packet branch.

## Files likely touched

- List expected file paths before editing.
- Flag any file that may be outside `allowed_paths`.
- Flag any file that matches `protected_paths`.

## Risks

- Note stale context risk.
- Note protected path risk.
- Note test or verification gaps.

## Tests required

- `python3 -m unittest discover -s tests`
- Relevant CLI help or demo commands.
- `python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode enforce`

## Branch assumptions

- Expected branch:
- Current branch:
- Current HEAD:
- Context freshness:

## Unresolved questions

- List questions requiring human approval before implementation.

## Recommended Git actions

Recommended:
git status

Explanation:
Shows current repository state including modified files, staged files, untracked files, and branch status.

Risk:
READ_ONLY

Potential consequences:
No repository files, refs, or remotes are changed.

Changes state:
no

Recommended:
git diff --cached --name-only

Explanation:
Lists staged files that would be included in the next commit.

Risk:
READ_ONLY

Potential consequences:
No repository files, refs, or remotes are changed.

Changes state:
no

Recommended:
git push -u origin <branch>

Explanation:
Pushes a local branch to origin and sets it as the upstream branch.

Risk:
REMOTE_CHANGING

Potential consequences:
Remote refs can change and future pulls/pushes track origin.

Changes state:
yes
