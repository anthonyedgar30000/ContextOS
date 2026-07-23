#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash deployment/install-contextos.sh [options]

Options:
  --replace       Replace a ContextOS-managed launcher from another checkout.
  --skip-tests    Skip the complete pre-install unit suite.
  --allow-dirty   Permit installation from a dirty source checkout.
  -h, --help      Show this help.
EOF
}

replace=false
skip_tests=false
allow_dirty=false

while (($#)); do
  case "$1" in
    --replace) replace=true ;;
    --skip-tests) skip_tests=true ;;
    --allow-dirty) allow_dirty=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

fail() {
  echo "ERROR: $*" >&2
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

for required in contextos contextos.py verify_cli.py git_command_explanations.py; do
  [[ -f "$REPO_ROOT/$required" ]] || fail "expected source file is missing: $REPO_ROOT/$required"
done

GIT_ROOT="$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)" \
  || fail "source checkout is not a Git repository"
GIT_ROOT="$(cd -- "$GIT_ROOT" && pwd -P)"
[[ "$GIT_ROOT" == "$REPO_ROOT" ]] || fail "deployment directory is not rooted at the ContextOS Git checkout"
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
DIRTY_STATUS="$(git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=normal)"
SOURCE_DIRTY=false
if [[ -n "$DIRTY_STATUS" ]]; then
  SOURCE_DIRTY=true
  $allow_dirty || fail "source checkout is dirty; review it or explicitly use --allow-dirty"
fi

if ! $skip_tests; then
  echo "Running complete ContextOS unit suite before installation..."
  (cd -- "$REPO_ROOT" && "$PYTHON_PATH" -m unittest discover -s tests -v)
fi

mkdir -p -- "$BIN_DIR" "$STATE_DIR"
chmod 700 "$STATE_DIR"

existing_source=""
if [[ -f "$STATE_FILE" ]]; then
  existing_source="$($PYTHON_PATH - "$STATE_FILE" <<'PY' 2>/dev/null || true
import json
import sys

try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))
    source = value.get("source_root")
    if isinstance(source, str):
        print(source)
except (OSError, ValueError, TypeError):
    pass
PY
)"
fi

if [[ -e "$LAUNCHER_PATH" || -L "$LAUNCHER_PATH" ]]; then
  [[ -f "$LAUNCHER_PATH" ]] || fail "launcher path exists but is not a regular file: $LAUNCHER_PATH"
  grep -Fq '# ContextOS managed launcher' "$LAUNCHER_PATH" \
    || fail "refusing to overwrite an unmanaged command at $LAUNCHER_PATH"
  if [[ "$existing_source" != "$REPO_ROOT" ]] && ! $replace; then
    fail "a managed launcher from another or unknown checkout exists; use --replace after review"
  fi
fi

launcher_tmp="$(mktemp "$BIN_DIR/.contextos-launcher.XXXXXX")"
state_tmp="$(mktemp "$STATE_DIR/.deployment.XXXXXX")"
cleanup() {
  rm -f -- "$launcher_tmp" "$state_tmp"
}
trap cleanup EXIT

{
  printf '#!/usr/bin/env bash\n'
  printf '# ContextOS managed launcher\n'
  printf 'SOURCE_ROOT=%q\n' "$REPO_ROOT"
  printf 'PYTHON_BIN=%q\n' "$PYTHON_PATH"
  printf 'exec "$PYTHON_BIN" "$SOURCE_ROOT/contextos.py" "$@"\n'
} >"$launcher_tmp"
chmod 0755 "$launcher_tmp"

export CONTEXTOS_DEPLOYMENT_SOURCE_ROOT="$REPO_ROOT"
export CONTEXTOS_DEPLOYMENT_SOURCE_COMMIT="$SOURCE_COMMIT"
export CONTEXTOS_DEPLOYMENT_SOURCE_DIRTY="$SOURCE_DIRTY"
export CONTEXTOS_DEPLOYMENT_LAUNCHER="$LAUNCHER_PATH"
export CONTEXTOS_DEPLOYMENT_PYTHON="$PYTHON_PATH"
export CONTEXTOS_DEPLOYMENT_STATE_TMP="$state_tmp"
"$PYTHON_PATH" - <<'PY'
import json
import os
from datetime import datetime, timezone

payload = {
    "schema_version": "contextos.local-deployment.v1",
    "deployment_type": "user_scoped_cli",
    "source_root": os.environ["CONTEXTOS_DEPLOYMENT_SOURCE_ROOT"],
    "source_commit": os.environ["CONTEXTOS_DEPLOYMENT_SOURCE_COMMIT"],
    "source_dirty": os.environ["CONTEXTOS_DEPLOYMENT_SOURCE_DIRTY"] == "true",
    "launcher_path": os.environ["CONTEXTOS_DEPLOYMENT_LAUNCHER"],
    "python_executable": os.environ["CONTEXTOS_DEPLOYMENT_PYTHON"],
    "installed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "helix_bridge_enabled": False,
    "system_service_installed": False,
    "credential_use": False,
}
with open(os.environ["CONTEXTOS_DEPLOYMENT_STATE_TMP"], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
chmod 0600 "$state_tmp"

mv -f -- "$launcher_tmp" "$LAUNCHER_PATH"
mv -f -- "$state_tmp" "$STATE_FILE"
trap - EXIT

"$LAUNCHER_PATH" --help >/dev/null

echo "ContextOS launcher installed: $LAUNCHER_PATH"
echo "Deployment evidence: $STATE_FILE"
echo "Source commit: $SOURCE_COMMIT"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "NOTICE: $BIN_DIR is not currently on PATH; add it to your user shell profile." >&2
fi
