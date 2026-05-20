# Sample repository setup

The demo script creates a local repository named `JillyPickles` under:

```text
/tmp/contextos-jillypickles-demo/JillyPickles
```

The repository is intentionally small but realistic enough to show how a stale
execution context can affect a normal development workflow.

## Initial branch

The repository starts on BranchB:

```text
main
```

## BranchA

The developer creates BranchA for scoped Client A copy work:

```text
feature/clientA
```

## Files created by the demo

```text
JillyPickles/
  contextos
  contextos.py
  git_command_explanations.py
  install_hooks.py
  verify_cli.py
  .gitignore
  session.json
  policy.yaml
  context_packet.yaml
  docs/
    clientA.md
  src/
    jillypickles/
      recommendations.py
  deploy/
    production.yml
```

## Policy

The policy allows Client A documentation and recommendation-code changes, but
protects deployment, infrastructure, workflow, and environment files:

```yaml
allowed_paths:
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
protected_paths:
  - ".github/workflows/**"
  - "deploy/**"
  - "infra/**"
  - ".env"
```

## Hook

The script installs a local `.git/hooks/pre-commit` hook with:

```sh
python3 install_hooks.py --repo /tmp/contextos-jillypickles-demo/JillyPickles --mode enforce
```

The hook runs `verify_cli.py` before commit and blocks the commit when ContextOS
finds stale context or protected path violations.
