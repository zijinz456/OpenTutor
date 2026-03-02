#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
API_BASE="${API_BASE:-http://localhost:8000/api}"
CHECK_API=1

usage() {
  cat <<'EOF'
Usage:
  scripts/check_local_mode.sh [--env-file PATH] [--api-base URL] [--skip-api]

Validates that OpenTutor is configured for the intended local-only deployment mode:
  - AUTH_ENABLED=false
  - DEPLOYMENT_MODE=single_user

When the API is already running, the script also checks /api/health to confirm the
effective runtime matches the local single-user configuration.
EOF
}

normalize_bool() {
  local value="${1:-false}"
  value="${value,,}"
  case "${value}" in
    1|true|yes|on) printf 'true\n' ;;
    *) printf 'false\n' ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --api-base)
      API_BASE="$2"
      shift 2
      ;;
    --skip-api)
      CHECK_API=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

if [[ ! -f "${ENV_FILE}" ]]; then
  fail "Environment file not found: ${ENV_FILE}"
fi

load_env_file "${ENV_FILE}"

auth_enabled="$(normalize_bool "${AUTH_ENABLED:-false}")"
deployment_mode="${DEPLOYMENT_MODE:-single_user}"

step "Checking local deployment mode"
log "  ENV_FILE=${ENV_FILE}"

if [[ "${deployment_mode}" != "single_user" ]]; then
  fail "DEPLOYMENT_MODE=${deployment_mode}. Local deployments must use DEPLOYMENT_MODE=single_user."
fi

if [[ "${auth_enabled}" != "false" ]]; then
  fail "AUTH_ENABLED=${auth_enabled}. Local deployments must keep AUTH_ENABLED=false."
fi

log "  PASS: .env is configured for single-user local deployment"

if (( CHECK_API )) && is_url_ready "${API_BASE}/health"; then
  step "Checking running API health contract"
  health_json="$(fetch_api_health_json || true)"
  [[ -n "${health_json}" ]] || fail "API health endpoint is reachable but returned no body."

  if [[ -z "${PY_BIN:-}" ]]; then
    PY_BIN="$(resolve_python_bin || true)"
  fi
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found for health JSON inspection."

  HEALTH_JSON="${health_json}" "${PY_BIN}" - <<'PY'
import json
import os
import sys

data = json.loads(os.environ["HEALTH_JSON"])
deployment_mode = data.get("deployment_mode")
auth_enabled = bool(data.get("auth_enabled"))

if deployment_mode != "single_user":
    raise SystemExit(
        f"Running API reports deployment_mode={deployment_mode!r}. Expected 'single_user'."
    )

if auth_enabled:
    raise SystemExit("Running API reports auth_enabled=true. Expected false for local deployment.")

print("  PASS: running API also reports single-user local mode")
PY
else
  log "  SKIP: API health check skipped because ${API_BASE}/health is not reachable"
fi
