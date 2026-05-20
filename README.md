# ContextOS

## Verification CLI

Run the deterministic verification CLI from the repository root:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml
```

`session.json` must be valid JSON. `policy.yaml` supports a minimal YAML subset
with a required `allowed_paths` list:

```yaml
allowed_paths:
  - README.md
  - src
```

Each allowed path matches the exact file or any child path below it. The CLI
runs git status and `git diff --name-only`, then fails with clear terminal output
when changed files fall outside `allowed_paths`.
