#!/bin/sh
set -u
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$repo_root" ]; then
  echo "Run this demo inside the Git repository." >&2
  exit 1
fi
cd "$repo_root" || exit 1
config="demo_freelancer_context_switch/ClientB/site_config.json"
backup="$(mktemp)"
tmpdir="$(mktemp -d)"
cp "$config" "$backup"
cleanup() {
  cp "$backup" "$config"
  rm -f "$backup"
  rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM

branch="$(git branch --show-current)"
cat > "$tmpdir/session_context.json" <<JSON
{
  "active_task": "Finish ClientA landing page copy",
  "current_branch": "$branch",
  "current_repo": "ClientA",
  "expected_directories": ["demo_freelancer_context_switch/ClientA"],
  "expected_files": ["demo_freelancer_context_switch/ClientA/site_config.json"],
  "expected_technologies": ["JSON config", "static storefront"],
  "last_verification_time": "2000-01-01T00:00:00+00:00",
  "originating_branch": "$branch",
  "originating_task": "ClientA storefront maintenance",
  "repo_assumptions": ["ClientA context only", "payments disabled is acceptable for ClientA"],
  "stale_assumptions": ["Cursor may still assume ClientA is active"],
  "timestamp": "2000-01-01T00:00:00+00:00",
  "unresolved_warnings": []
}
JSON
cat > "$tmpdir/state_manifest.json" <<JSON
{
  "last_context_score": "FRESH",
  "last_status": "VALID",
  "last_verification_timestamp": "2000-01-01T00:00:00+00:00",
  "last_verified_action": "manual",
  "last_verified_branch": "$branch",
  "last_verified_commit": "stale-demo",
  "last_verified_repo": "https://example.invalid/client-a",
  "last_verified_repo_identity": "ClientA"
}
JSON

echo "=== Freelancer demo: WITH ContextOS ==="
echo "1) Freelancer starts with healthy ClientB context."
python3 demo_freelancer_context_switch/check_client_b.py || exit 1

echo ""
echo "2) Same stale ClientA assumptions edit ClientB config."
cp demo_freelancer_context_switch/stale_client_a_change_for_client_b.json "$config"
if python3 demo_freelancer_context_switch/check_client_b.py; then
  echo "Expected ClientB to break after stale ClientA config." >&2
  exit 1
fi

echo ""
echo "3) ContextOS checks AI execution context before commit."
python3 verifier.py verify \
  --action commit \
  --mode enforce \
  --policy demo_freelancer_context_switch/ClientB/.contextos/policy.yaml \
  --state "$tmpdir/state_manifest.json" \
  --session "$tmpdir/session_context.json" \
  --audit-log "$tmpdir/audit_log.jsonl"
status=$?
echo "Simulated commit gate exit code: $status"
if [ "$status" -eq 0 ]; then
  echo "Expected ContextOS to block stale ClientA context." >&2
  exit 1
fi

echo ""
echo "4) Remediation restores ClientB config; app is healthy again."
cp "$backup" "$config"
python3 demo_freelancer_context_switch/check_client_b.py || exit 1

echo ""
echo "ContextOS blocked the wrong-client mutation before Git became authoritative."
echo "Demo audit log: $tmpdir/audit_log.jsonl"
