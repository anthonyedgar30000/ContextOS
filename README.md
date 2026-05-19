# ContextOS

ContextOS is a lightweight governance layer for AI-assisted development workflows.
This prototype ships a local-first verifier that checks the current Git checkout
against a simple policy file.

## CLI

Run the verifier from the repository root:

```bash
python verifier.py verify
```

If you want the command to read like the intended CLI name, create a local alias:

```bash
alias contextos="python /path/to/ContextOS/verifier.py"
contextos verify
```

## Policy

`contextos verify` reads `policy.yaml` by default:

```yaml
expected:
  remote: "https://github.com/example/contextos"
  branch: "main"
  commit: "abc123"
require_clean_tree: true
```

Expected values that are empty or omitted are ignored. `require_clean_tree`
defaults to `true`.

## Status values

The verifier prints one status:

- `VALID` - remote, branch, commit, and cleanliness match the policy.
- `STALE` - remote and branch match, but the current commit differs.
- `DIVERGED` - the current remote or branch differs from policy.
- `BLOCKED` - verification cannot run, the policy is invalid, or the working
  tree is dirty while `require_clean_tree` is enabled.

Only `BLOCKED` returns a non-zero exit code.

## Audit log

Every verification appends a structured JSON event to `audit_log.jsonl`:

```json
{"tool":"contextos","command":"verify","status":"VALID","policy_path":"policy.yaml","git":{"remote":"...","branch":"main","commit":"abc123","dirty":false},"expected":{"remote":"...","branch":"main","commit":"abc123"},"mismatches":[],"error":null,"timestamp":"2026-05-19T00:00:00+00:00"}
```

You can override paths when needed:

```bash
python verifier.py verify --policy ./policy.yaml --audit-log ./audit_log.jsonl
```
