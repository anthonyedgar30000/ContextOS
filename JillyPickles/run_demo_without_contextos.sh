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
cp "$config" "$backup"
cleanup() {
  cp "$backup" "$config"
  rm -f "$backup"
}
trap cleanup EXIT INT TERM

echo "=== Flow A: governance disabled ==="
echo "1) Start from a healthy JillyPickles app."
python3 JillyPickles/app.py || exit 1

echo ""
echo "2) Stale context applies an obsolete cucumber-cart config."
cp JillyPickles/demo_context_drift/bad_config.json "$config"

echo ""
echo "3) The app is now visibly broken."
if python3 JillyPickles/app.py; then
  echo "Expected the bad config to break the app." >&2
  exit 1
fi

echo ""
echo "4) With governance disabled, no verifier runs before Git."
echo "   Simulated git commit: succeeds"
echo "   Simulated git push:   succeeds"
echo "   Result: broken JillyPickles config can become authoritative state."
