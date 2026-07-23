#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash deployment/uninstall-contextos.sh [options]

Options:
  --force       Remove the configured launcher even when its managed marker or
                deployment evidence cannot be verified.
  -h, --help    Show this help.
EOF
}

force=false
while (($#)); do
  case "$1" in
    --force) force=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

fail() {
  echo "ROLLBACK FAILED: $*" >&2
  exit 1
}

PYTHON_BIN="${PYTHON_BIN:-python3}"
BIN_DIR="${CONTEXTOS_BIN_DIR:-$HOME/.local/bin}"
STATE_DIR="${CONTEXTOS_STATE_DIR:-$HOME/.local/share/contextos}"
LAUNCHER_PATH="$BIN_DIR/contextos"
STATE_FILE="$STATE_DIR/deployment.json"

if [[ ! -e "$LAUNCHER_PATH" && ! -L "$LAUNCHER_PATH" && ! -e "$STATE_FILE" ]]; then
  echo "ContextOS is not installed at the configured user-local paths."
  exit 0
fi

recorded_launcher=""
if [[ -f "$STATE_FILE" ]] && command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  recorded_launcher="$($PYTHON_BIN - "$STATE_FILE" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        value = json.load(handle)
    launcher = value.get("launcher_path")
    if isinstance(launcher, str):
        print(launcher)
except (OSError, ValueError, TypeError):
    pass
PY
)"
fi

if [[ -n "$recorded_launcher" && "$recorded_launcher" != "$LAUNCHER_PATH" ]] && ! $force; then
  fail "deployment evidence points to a different launcher: $recorded_launcher"
fi

if [[ -e "$LAUNCHER_PATH" || -L "$LAUNCHER_PATH" ]]; then
  if [[ -f "$LAUNCHER_PATH" ]] && grep -Fq '# ContextOS managed launcher' "$LAUNCHER_PATH"; then
    rm -f -- "$LAUNCHER_PATH"
  elif $force; then
    rm -f -- "$LAUNCHER_PATH"
  else
    fail "refusing to remove a launcher without the ContextOS managed marker; use --force only after review"
  fi
fi

if [[ -e "$STATE_FILE" ]]; then
  if [[ -f "$STATE_FILE" ]] || $force; then
    rm -f -- "$STATE_FILE"
  else
    fail "deployment evidence path is not a regular file"
  fi
fi

rmdir -- "$STATE_DIR" 2>/dev/null || true

echo "CONTEXTOS LOCAL DEPLOYMENT REMOVED"
echo "Removed launcher: $LAUNCHER_PATH"
echo "Removed evidence: $STATE_FILE"
echo "Source checkout and repository data were not modified."
