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
cp "$config" "$backup"
cleanup() {
  cp "$backup" "$config"
  rm -f "$backup"
}
trap cleanup EXIT INT TERM

echo "=== Freelancer demo: WITHOUT ContextOS ==="
echo "1) Freelancer starts with healthy ClientB context."
python3 demo_freelancer_context_switch/check_client_b.py || exit 1

echo ""
echo "2) Cursor retains stale ClientA assumptions and edits ClientB config."
cp demo_freelancer_context_switch/stale_client_a_change_for_client_b.json "$config"

echo ""
echo "3) ClientB is now visibly broken."
if python3 demo_freelancer_context_switch/check_client_b.py; then
  echo "Expected ClientB to break after stale ClientA config." >&2
  exit 1
fi

echo ""
echo "4) With no ContextOS gate, the bad workspace mutation can be committed."
echo "   Simulated git commit: succeeds"
echo "   Simulated git push:   succeeds"
echo "   Result: ClientA assumptions become authoritative for ClientB."
