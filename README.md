# ContextOS

## Verification CLI

Run the deterministic verification CLI from the repository root:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml
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
explicit mismatch reasons, and unauthorized files.
