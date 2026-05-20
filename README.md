# ContextOS

## Verification CLI

Run the deterministic verification CLI from the repository root:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml --report audit.md
```

`session.json` must be valid JSON. `policy.yaml` supports a minimal YAML subset
with a required `allowed_paths` list:

```json
{
  "expected_branch": "main"
}
```

```yaml
allowed_paths:
  - README.md
  - src
```

Each allowed path matches the exact file or any child path below it. The
optional `expected_branch` value is compared with the current git branch. The
CLI runs git status and `git diff --name-only`, then prints deterministic
terminal output with colored pass/fail status, expected versus actual branch,
explicit mismatch reasons, and unauthorized files. When `--report` is provided,
the CLI writes a markdown audit report containing a UTC timestamp, repo, branch,
changed files, allowed files, violations, and git status summary.

Enable the tracked pre-commit hook to run verification before each commit:

```sh
git config core.hooksPath .githooks
```

The hook executes `python3 verify_cli.py --session session.json --policy
policy.yaml --repo <repo-root>` and aborts the commit when verification fails.
