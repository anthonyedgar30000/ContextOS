# Failure explanation

The demo failure is caused by two independent local checks.

## 1. Stale execution context

The context packet was ingested on BranchA:

```text
feature/clientA
```

That ingestion wrote `.contextos/session_context.json` with the BranchA name and
the BranchA HEAD hash. The developer then switched locally to BranchB:

```text
main
```

When `verify_cli.py` runs, it compares the current local Git branch and HEAD
hash with the ingested session context. The current branch and HEAD no longer
match the recorded context, so verification classifies the context as:

```text
CONTEXT STALE
```

## 2. Protected path mutation

The simulated stale plan changes:

```text
deploy/production.yml
```

That file matches the protected path pattern:

```text
deploy/**
```

Because verification runs in `--protected-mode enforce`, the staged deployment
change is a blocking violation.

## Result

The manual verification step fails, writes `audit.md`, and the installed
pre-commit hook blocks the attempted commit. No push is attempted.
