#!/bin/sh
set -u

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$repo_root" ]; then
  echo "Run this demo inside the Git repository." >&2
  exit 1
fi
cd "$repo_root" || exit 1

config="JillyPickles/config.json"
backup="$(mktemp)"
tmpdir="$(mktemp -d)"
cp "$config" "$backup"
cleanup() {
  cp "$backup" "$config"
  rm -f "$backup"
  rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM

write_stale_state() {
  cat > "$tmpdir/state_manifest.json" <<'JSON'
{
  "last_status": "VALID",
  "last_verification_timestamp": "2000-01-01T00:00:00+00:00",
  "last_verified_action": "manual",
  "last_verified_branch": "legacy-cucumber-context",
  "last_verified_commit": "stale-demo",
  "last_verified_repo": "https://example.invalid/stale/JillyPickles",
  "last_verified_repo_identity": "JillyPickles"
}
JSON
}

echo "=== Flow B: ContextOS enabled ==="
echo "1) Install hooks pointed at the JillyPickles governance policy."
python3 install_hooks.py \
  --policy JillyPickles/.contextos/policy.yaml \
  --state JillyPickles/.contextos/state_manifest.json \
  --audit-log JillyPickles/audit_log.jsonl

echo ""
echo "2) Start from a healthy JillyPickles app."
python3 JillyPickles/app.py || exit 1

echo ""
echo "3) The same stale context applies the bad config."
cp JillyPickles/demo_context_drift/bad_config.json "$config"
if python3 JillyPickles/app.py; then
  echo "Expected the bad config to break the app." >&2
  exit 1
fi

echo ""
echo "4) Pre-commit verification sees stale/diverged context and blocks."
write_stale_state
python3 verifier.py verify \
  --action commit \
  --policy JillyPickles/.contextos/policy.yaml \
  --state "$tmpdir/state_manifest.json" \
  --audit-log "$tmpdir/audit_log.jsonl"
commit_status=$?
echo "Simulated commit gate exit code: $commit_status"

if [ "$commit_status" -eq 0 ]; then
  echo "Expected ContextOS to block the commit." >&2
  exit 1
fi

echo ""
echo "5) Pre-push verification blocks the same stale context before GitOps/deploy."
write_stale_state
python3 verifier.py verify \
  --action push \
  --policy JillyPickles/.contextos/policy.yaml \
  --state "$tmpdir/state_manifest.json" \
  --audit-log "$tmpdir/audit_log.jsonl"
push_status=$?
echo "Simulated push gate exit code: $push_status"

if [ "$push_status" -eq 0 ]; then
  echo "Expected ContextOS to block the push." >&2
  exit 1
fi

echo ""
echo "6) Remediation restores the healthy config; app remains healthy."
cp "$backup" "$config"
python3 JillyPickles/app.py || exit 1

echo ""
echo "ContextOS prevented stale AI context from becoming authoritative Git state."
echo "Demo audit log: $tmpdir/audit_log.jsonl"
