# ContextOS

## ContextOS ingest

Convert a reviewed ChatGPT context packet into deterministic local execution
context:

```sh
./contextos ingest context_packet.yaml
```

Example `context_packet.yaml`:

```yaml
project: ContextOS
repo: ContextOS
branch: main
task: Add local ingest command
allowed_paths:
  - README.md
  - src
```

The ingest command validates required packet fields, compares `repo` and
`branch` with the current local Git repository, and fails clearly on mismatch.
When valid, it writes `.contextos/session_context.json` with the packet context,
UTC timestamp, current Git HEAD hash, and `source: chatgpt_context_packet`.

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
protected_paths:
  - ".github/workflows/**"
  - "deploy/**"
  - "infra/**"
  - ".env"
```

Each allowed path matches the exact file or any child path below it. The
optional `expected_branch` value is compared with the current git branch. The
CLI runs git status and `git diff --name-only`, then prints deterministic
terminal output with colored pass/fail status, expected versus actual branch,
explicit mismatch reasons, and unauthorized files. When `--report` is provided,
the CLI writes a markdown audit report containing a UTC timestamp, repo, branch,
changed files, allowed files, violations, and git status summary.

Protected paths are evaluated against the staged diff from `git diff --cached
--name-only`. In advisory mode, staged protected path changes produce a warning
without failing verification:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode advisory
```

In enforce mode, staged protected path changes fail verification:

```sh
python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode enforce
```

Protected path violations are included in markdown audit reports.

When `.contextos/session_context.json` exists, the verification CLI also checks
that the current branch and Git HEAD still match the ingested context, and that
the local branch is not behind its configured remote-tracking branch. Stale
context fails verification with deterministic remediation steps:

```text
CONTEXT STALE
Reason:

- branch switched from feature/clientA to main
- HEAD changed since context ingestion

Suggested remediation:

1. regenerate context packet
2. run contextos ingest again
```

Enable the tracked pre-commit hook to run verification before each commit:

```sh
git config core.hooksPath .githooks
```

The hook executes `verify_cli.py` with `--protected-mode enforce` and aborts the
commit when verification fails.
