# Freshness failure scenario

This sample shows how `contextos verify-freshness` detects an implementation
plan that no longer matches repository execution reality.

## Execution plan

```markdown
# Update Client A copy

## Original objective
Update Client A documentation without changing deployment files.

## Plan timestamp
2026-05-20T12:00:00Z

## Expected branch
feature/clientA

## Expected HEAD
abc123

## Expected files/scope
- docs/clientA.md
- src/jillypickles/recommendations.py

## Last verified branch
feature/clientA

## Last verified HEAD
abc123

## Last verified repo state
Clean working tree at plan creation.
```

## Repository drift

The developer later switches to `main` and changes:

```text
deploy/production.yml
```

## Expected classification

```text
DIVERGED
```

## Why

- current branch no longer matches the plan branch
- current HEAD no longer matches the plan HEAD
- `deploy/production.yml` is outside expected files/scope

## Required response

Do not continue applying the original plan. Regenerate the context packet,
create a new execution plan for the current branch, and re-run verification
before committing.
