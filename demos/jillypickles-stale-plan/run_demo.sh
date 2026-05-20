#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
WORK_ROOT=${CONTEXTOS_DEMO_WORKDIR:-/tmp/contextos-jillypickles-demo}
DEMO_REPO="$WORK_ROOT/JillyPickles"
BRANCH_A="feature/clientA"
BRANCH_B="main"

section() {
  printf '\n== %s ==\n' "$1"
}

run() {
  printf '+ %s\n' "$*"
  "$@"
}

section "Reset demo workspace"
rm -rf "$DEMO_REPO"
mkdir -p "$WORK_ROOT"

section "Create local JillyPickles repository"
run git init -b "$BRANCH_B" "$DEMO_REPO"
run git -C "$DEMO_REPO" config user.email "demo@jillypickles.example"
run git -C "$DEMO_REPO" config user.name "JillyPickles Demo"

mkdir -p "$DEMO_REPO/src/jillypickles" "$DEMO_REPO/docs" "$DEMO_REPO/deploy"
cp "$REPO_ROOT/contextos" "$DEMO_REPO/contextos"
cp "$REPO_ROOT/contextos.py" "$DEMO_REPO/contextos.py"
cp "$REPO_ROOT/verify_cli.py" "$DEMO_REPO/verify_cli.py"
chmod +x "$DEMO_REPO/contextos"

cat > "$DEMO_REPO/src/jillypickles/recommendations.py" <<'PY'
def client_a_recommendation():
    return "Classic dill picnic pack"
PY

cat > "$DEMO_REPO/docs/clientA.md" <<'MD'
# Client A picnic pack

- classic dill jar
- garlic spear jar
MD

cat > "$DEMO_REPO/deploy/production.yml" <<'YAML'
service: jillypickles-web
replicas: 2
YAML

cat > "$DEMO_REPO/session.json" <<'JSON'
{}
JSON

cat > "$DEMO_REPO/policy.yaml" <<'YAML'
allowed_paths:
  - context_packet.yaml
  - docs/clientA.md
  - src/jillypickles/recommendations.py
  - policy.yaml
  - session.json
  - .contextos/session_context.json
  - contextos
  - contextos.py
  - verify_cli.py
protected_paths:
  - ".github/workflows/**"
  - "deploy/**"
  - "infra/**"
  - ".env"
YAML

run git -C "$DEMO_REPO" add .
run git -C "$DEMO_REPO" commit -m "Initialize JillyPickles demo app"

section "1. Start on BranchA"
run git -C "$DEMO_REPO" checkout -b "$BRANCH_A"

cat > "$DEMO_REPO/docs/clientA.md" <<'MD'
# Client A picnic pack

- classic dill jar
- garlic spear jar
- spicy bread-and-butter chips
MD

run git -C "$DEMO_REPO" add docs/clientA.md
run git -C "$DEMO_REPO" commit -m "Update Client A pickle recommendations"

section "2. Generate/update context packet"
cat > "$DEMO_REPO/context_packet.yaml" <<YAML
project: JillyPickles
repo: JillyPickles
branch: $BRANCH_A
task: Update Client A picnic pack copy without changing deploy or infra files
allowed_paths:
  - context_packet.yaml
  - docs/clientA.md
  - src/jillypickles/recommendations.py
  - policy.yaml
  - session.json
YAML

run "$DEMO_REPO/contextos" --repo "$DEMO_REPO" ingest "$DEMO_REPO/context_packet.yaml"

section "3. Switch locally to BranchB"
run git -C "$DEMO_REPO" checkout "$BRANCH_B"

section "4-5. Simulate stale AI assumptions and attempt unauthorized mutation"
cat > "$DEMO_REPO/deploy/production.yml" <<'YAML'
service: jillypickles-web
replicas: 4
YAML
run git -C "$DEMO_REPO" add deploy/production.yml

section "6-7. ContextOS detects mismatch and verification fails before commit/push"
set +e
python3 "$DEMO_REPO/verify_cli.py" \
  --session "$DEMO_REPO/session.json" \
  --policy "$DEMO_REPO/policy.yaml" \
  --repo "$DEMO_REPO" \
  --protected-mode enforce \
  --report "$DEMO_REPO/audit.md"
VERIFY_EXIT=$?
set -e

printf '\nverification exit code: %s\n' "$VERIFY_EXIT"
if [ "$VERIFY_EXIT" -eq 0 ]; then
  printf 'demo failed: verification unexpectedly passed\n' >&2
  exit 1
fi

section "Demo result"
printf 'Commit/push should not proceed. Inspect generated repo at: %s\n' "$DEMO_REPO"
printf 'Audit report: %s\n' "$DEMO_REPO/audit.md"
