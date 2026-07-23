#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash deployment/verify-contextos.sh [options]

Options:
  --skip-tests    Skip the complete repository unit suite.
  -h, --help      Show this help.
EOF
}

skip_tests=false
while (($#)); do
  case "$1" in
    --skip-tests) skip_tests=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

fail() {
  echo "DEPLOYMENT VERIFICATION FAILED: $*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is required"
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python executable not found: $PYTHON_BIN"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11 or newer is required"
PYTHON_PATH="$(command -v "$PYTHON_BIN")"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
BIN_DIR="${CONTEXTOS_BIN_DIR:-$HOME/.local/bin}"
STATE_DIR="${CONTEXTOS_STATE_DIR:-$HOME/.local/share/contextos}"
LAUNCHER_PATH="$BIN_DIR/contextos"
STATE_FILE="$STATE_DIR/deployment.json"

[[ -f "$LAUNCHER_PATH" ]] || fail "managed launcher is missing: $LAUNCHER_PATH"
[[ -x "$LAUNCHER_PATH" ]] || fail "managed launcher is not executable: $LAUNCHER_PATH"
grep -Fq '# ContextOS managed launcher' "$LAUNCHER_PATH" \
  || fail "launcher does not contain the ContextOS managed marker"
[[ -f "$STATE_FILE" ]] || fail "deployment evidence is missing: $STATE_FILE"

mapfile -t deployment_fields < <("$PYTHON_PATH" - "$STATE_FILE" <<'PY'
import json
import os
import sys
from datetime import datetime

expected_keys = {
    "schema_version",
    "deployment_type",
    "source_root",
    "source_commit",
    "source_dirty",
    "launcher_path",
    "python_executable",
    "installed_at",
    "helix_bridge_enabled",
    "system_service_installed",
    "credential_use",
}
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        value = json.load(handle)
except (OSError, ValueError) as error:
    raise SystemExit(f"invalid deployment JSON: {error}")
if not isinstance(value, dict) or set(value) != expected_keys:
    raise SystemExit("deployment evidence has an unexpected shape")
if value["schema_version"] != "contextos.local-deployment.v1":
    raise SystemExit("deployment schema version is invalid")
if value["deployment_type"] != "user_scoped_cli":
    raise SystemExit("deployment type is invalid")
for key in ("source_root", "source_commit", "launcher_path", "python_executable", "installed_at"):
    if not isinstance(value[key], str) or not value[key]:
        raise SystemExit(f"{key} must be a non-empty string")
if len(value["source_commit"]) != 40 or any(character not in "0123456789abcdef" for character in value["source_commit"]):
    raise SystemExit("source_commit must be a lowercase full Git SHA")
for key in ("source_dirty", "helix_bridge_enabled", "system_service_installed", "credential_use"):
    if not isinstance(value[key], bool):
        raise SystemExit(f"{key} must be boolean")
if value["source_dirty"]:
    raise SystemExit("deployment was recorded from a dirty source checkout")
if value["helix_bridge_enabled"] or value["system_service_installed"] or value["credential_use"]:
    raise SystemExit("deployment evidence exceeds the bounded local CLI authority")
try:
    parsed = datetime.fromisoformat(value["installed_at"].replace("Z", "+00:00"))
except ValueError as error:
    raise SystemExit(f"installed_at is invalid: {error}")
if parsed.tzinfo is None:
    raise SystemExit("installed_at must include a timezone")
print(value["source_root"])
print(value["source_commit"])
print(value["launcher_path"])
print(value["python_executable"])
PY
) || fail "deployment evidence validation failed"

[[ ${#deployment_fields[@]} -eq 4 ]] || fail "deployment evidence did not return the expected fields"
DEPLOYED_ROOT="${deployment_fields[0]}"
DEPLOYED_COMMIT="${deployment_fields[1]}"
DEPLOYED_LAUNCHER="${deployment_fields[2]}"
DEPLOYED_PYTHON="${deployment_fields[3]}"

DEPLOYED_ROOT="$(cd -- "$DEPLOYED_ROOT" 2>/dev/null && pwd -P)" \
  || fail "recorded source checkout is unavailable"
[[ "$DEPLOYED_ROOT" == "$REPO_ROOT" ]] \
  || fail "verification checkout does not match the deployed source checkout"
[[ "$DEPLOYED_LAUNCHER" == "$LAUNCHER_PATH" ]] \
  || fail "recorded launcher path does not match the configured launcher path"
[[ -x "$DEPLOYED_PYTHON" ]] || fail "recorded Python executable is unavailable"

CURRENT_COMMIT="$(git -C "$DEPLOYED_ROOT" rev-parse HEAD)" \
  || fail "could not resolve the deployed source commit"
[[ "$CURRENT_COMMIT" == "$DEPLOYED_COMMIT" ]] \
  || fail "deployed source commit drifted: recorded=$DEPLOYED_COMMIT current=$CURRENT_COMMIT"
[[ -z "$(git -C "$DEPLOYED_ROOT" status --porcelain=v1 --untracked-files=normal)" ]] \
  || fail "deployed source checkout is now dirty"

"$LAUNCHER_PATH" --help >/dev/null 
EXPLANATION_OUTPUT="$(cd -- "$DEPLOYED_ROOT" && "$LAUNCHER_PATH" explain-git git status)" \
  || fail "deterministic explain-git smoke test failed"
grep -Fq 'READ_ONLY' <<<"$EXPLANATION_OUTPUT" \
  || fail "explain-git smoke test did not classify git status as READ_ONLY"

if ! $skip_tests; then
  echo "Running complete ContextOS unit suite as deployment verification..."
  (cd -- "$DEPLOYED_ROOT" && "$DEPLOYED_PYTHON" -m unittest discover -s tests -v)
fi

echo "CONTEXTOS LOCAL DEPLOYMENT VERIFIED"
echo "Launcher: $LAUNCHER_PATH"
echo "Evidence: $STATE_FILE"
echo "Source commit: $CURRENT_COMMIT"
echo "HELIX bridge enabled: false"
echo "System service installed: false"
