# Expected audit report excerpt

The demo writes a full markdown audit report to:

```text
/tmp/contextos-jillypickles-demo/JillyPickles/audit.md
```

Key deterministic sections include:

```markdown
## Changed Files
- deploy/production.yml

## Allowed Files
- .gitignore
- context_packet.yaml
- docs/clientA.md
- src/jillypickles/recommendations.py
- policy.yaml
- session.json
- .contextos/session_context.json
- contextos
- contextos.py
- git_command_explanations.py
- install_hooks.py
- verify_cli.py

## Violations
- session created on feature/clientA
- current branch is main
- HEAD changed after ingestion
- protected path violation: deploy/production.yml matches deploy/**

## Context Freshness
- classification: STALE
- session created on feature/clientA
- current branch is main
- HEAD changed after ingestion

## Protected Path Violations
- protected path violation: deploy/production.yml matches deploy/**
```
