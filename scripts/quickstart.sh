#!/usr/bin/env bash
# OpenTutor — One-click local development setup & launch
# Usage: ./scripts/quickstart.sh [--exit-after-ready]
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_DIR="${ROOT_DIR}/apps/api"
WEB_DIR="${ROOT_DIR}/apps/web"
ENV_FILE="${ROOT_DIR}/.env"
VENV_DIR="${API_DIR}/.venv"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3001}"
API_BASE_URL="http://localhost:${API_PORT}"
WEB_BASE_URL="http://localhost:${WEB_PORT}"
API_PID=""
WEB_PID=""
DB_DISPLAY=""
EXIT_AFTER_READY="${QUICKSTART_EXIT_AFTER_READY:-0}"
READY_TIMEOUT_SECONDS="${QUICKSTART_READY_TIMEOUT_SECONDS:-120}"

usage() {
  cat <<'EOF'
Usage:
  scripts/quickstart.sh [--exit-after-ready]

Options:
  --exit-after-ready   Exit with code 0 after API/Web become ready.
                       Useful for CI and release rehearsal automation.
EOF
}

normalize_bool() {
  local value="${1:-false}"
  value="$(to_lower "${value}")"
  case "${value}" in
    1|true|yes|on) printf 'true\n' ;;
    *) printf 'false\n' ;;
  esac
}

wait_for_service_or_process() {
  local label="$1"
  local url="$2"
  local pid="$3"
  local timeout_seconds="$4"
  local started_at
  local status

  started_at="$(date +%s)"
  while true; do
    status="$(curl -sS -o /dev/null -w '%{http_code}' "${url}" || true)"
    if [[ "${status}" =~ ^(2|3) ]]; then
      log "READY: ${label} (${url})"
      return 0
    fi

    if ! kill -0 "${pid}" 2>/dev/null; then
      fail "${label} exited before readiness. Check the [$(to_lower "${label}")] logs above and fix the reported startup error."
    fi

    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      fail "${label} did not become ready within ${timeout_seconds}s: ${url}"
    fi

    sleep 2
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --exit-after-ready)
      EXIT_AFTER_READY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1. Run 'bash scripts/quickstart.sh --help' for valid options."
      ;;
  esac
done

EXIT_AFTER_READY="$(normalize_bool "${EXIT_AFTER_READY}")"

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
  log ""
  log "Shutting down..."
  if [[ -n "${WEB_PID}" ]]; then
    kill "${WEB_PID}" 2>/dev/null || true
    wait "${WEB_PID}" 2>/dev/null || true
  fi
  if [[ -n "${API_PID}" ]]; then
    kill "${API_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
  fi
  log "Done."
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
step "Checking prerequisites"

# Node / npm
if ! command -v node >/dev/null 2>&1; then
  fail "Node.js not found. Install it: https://nodejs.org (v20+ recommended)"
fi
log "  Node $(node -v)"

if ! command -v npm >/dev/null 2>&1; then
  fail "npm not found."
fi

# Python 3.11
PY_BIN="$(resolve_python_bin || true)"
if [[ -z "${PY_BIN}" ]]; then
  fail "Python not found. OpenTutor requires Python 3.11. Install: https://www.python.org/downloads/"
fi

require_python_311 "${PY_BIN}"
py_version="$("${PY_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
log "  Python ${py_version} at ${PY_BIN}"

# curl (for health checks)
require_cmd curl

# ---------------------------------------------------------------------------
# 2. Environment file
# ---------------------------------------------------------------------------
step "Environment configuration"

if [[ ! -f "${ENV_FILE}" ]]; then
  log "  Creating .env from .env.example ..."
  cp "${ROOT_DIR}/.env.example" "${ENV_FILE}"
  log "  .env created. Connect Ollama or add an API key for AI features."
else
  log "  .env already exists"
fi

# Source .env for this script
load_env_file "${ENV_FILE}"
if ! bash "${ROOT_DIR}/scripts/check_local_mode.sh" --env-file "${ENV_FILE}" --skip-api; then
  fail "Local mode validation failed. Run: bash scripts/check_local_mode.sh --env-file ${ENV_FILE} --skip-api, then follow the reported fix and retry quickstart."
fi

if [[ -n "${DATABASE_URL:-}" && "${DATABASE_URL}" != sqlite* ]]; then
  fail "SQLite-only local mode: DATABASE_URL must start with sqlite (current: ${DATABASE_URL})"
fi

if [[ -n "${DATABASE_URL:-}" ]]; then
  DB_DISPLAY="${DATABASE_URL}"
else
  DB_DISPLAY="sqlite+aiosqlite:///${HOME}/.opentutor/data.db"
fi

log "  Database mode: sqlite"
log "  Database URL:  ${DB_DISPLAY}"

# ---------------------------------------------------------------------------
# 3. Auto-detect Ollama
# ---------------------------------------------------------------------------
ollama_models="$(configure_local_ollama_env "${ENV_FILE}" || true)"
if [[ -n "${ollama_models}" ]]; then
  first_model="${LLM_MODEL:-$(printf '%s\n' "${ollama_models}" | head -n 1)}"
  ollama_models_inline="$(printf '%s\n' "${ollama_models}" | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  log ""
  log "  Ollama detected with models: ${ollama_models_inline}"
  log "  Auto-configuring LLM_PROVIDER=ollama, LLM_MODEL=${first_model}"
fi

# ---------------------------------------------------------------------------
# 4. Python virtual environment
# ---------------------------------------------------------------------------
step "Python environment"

VENV_PY="$(venv_python_path "${VENV_DIR}")"
VENV_PIP="$(venv_pip_path "${VENV_DIR}")"
if [[ ! -x "${VENV_PY}" ]]; then
  log "  Creating virtual environment ..."
  "${PY_BIN}" -m venv "${VENV_DIR}"
fi
PY_BIN="${VENV_PY}"
PIP_BIN="${VENV_PIP}"

log "  Installing Python dependencies ..."
"${PIP_BIN}" install -q -r "${API_DIR}/requirements-core.txt"
log "  Done"
log "  Optional integrations remain available via requirements-full.txt"

# ---------------------------------------------------------------------------
# 5. Database setup
# ---------------------------------------------------------------------------
step "Database"
sqlite_path="$(
  DATABASE_URL="${DATABASE_URL:-}" "${PY_BIN}" - <<'PY'
from pathlib import Path
import os

database_url = os.environ.get("DATABASE_URL", "").strip()
if not database_url:
    print((Path.home() / ".opentutor" / "data.db").expanduser())
elif database_url.startswith("sqlite"):
    path = database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    print((Path(path or (Path.home() / ".opentutor" / "data.db"))).expanduser())
else:
    raise SystemExit("Expected SQLite URL")
PY
)"
mkdir -p "$(dirname "${sqlite_path}")"
log "  Using SQLite at ${sqlite_path}"

# ---------------------------------------------------------------------------
# 6. Database bootstrap
# ---------------------------------------------------------------------------
step "Database bootstrap"
log "  SQLite mode uses app startup hooks to create tables and seed built-in data."

# ---------------------------------------------------------------------------
# 7. Frontend dependencies
# ---------------------------------------------------------------------------
step "Frontend dependencies"

cd "${WEB_DIR}"
if [[ ! -d "node_modules" ]] || [[ "package.json" -nt "node_modules/.package-lock.json" ]]; then
  log "  Installing npm packages ..."
  npm install --no-audit --no-fund 2>&1 | tail -1
else
  log "  node_modules up to date"
fi

# ---------------------------------------------------------------------------
# 8. Docker Compose hint
# ---------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    log ""
    log "  Tip: You can also run 'docker compose up' for a fully containerized setup."
  fi
fi

# ---------------------------------------------------------------------------
# 9. Launch services
# ---------------------------------------------------------------------------
step "Starting services"

if pgrep -f "${WEB_DIR}/node_modules/.bin/next dev" >/dev/null 2>&1; then
  fail "Detected an existing Next.js dev process for ${WEB_DIR}. Stop it before running quickstart (for example: pkill -f '${WEB_DIR}/node_modules/.bin/next dev')."
fi

next_lock_file="${WEB_DIR}/.next/dev/lock"
if [[ -f "${next_lock_file}" ]]; then
  if command -v lsof >/dev/null 2>&1 && lsof "${next_lock_file}" >/dev/null 2>&1; then
    fail "Next.js lock file is active at ${next_lock_file}. Stop the running next dev process and retry."
  fi
  rm -f "${next_lock_file}"
  log "  Removed stale Next.js lock: ${next_lock_file}"
fi

cd "${API_DIR}"
log "  Starting API server (port ${API_PORT}) ..."
"${PY_BIN}" -m uvicorn main:app --host 127.0.0.1 --port "${API_PORT}" --reload > >(sed 's/^/  [api] /') 2>&1 &
API_PID=$!

cd "${WEB_DIR}"
log "  Starting Web server (port ${WEB_PORT}) ..."
npx next dev --port "${WEB_PORT}" > >(sed 's/^/  [web] /') 2>&1 &
WEB_PID=$!

sleep 2
if ! kill -0 "${API_PID}" 2>/dev/null; then
  fail "API server exited early. Check the [api] logs above for the root cause (common fix: free port ${API_PORT} or set API_PORT to an unused port), then retry quickstart."
fi
if ! kill -0 "${WEB_PID}" 2>/dev/null; then
  fail "Web server exited early. Check the [web] logs above for the root cause (common fixes: free port ${WEB_PORT}, stop other 'next dev' instances, or remove stale .next/dev lock), then retry quickstart."
fi

# ---------------------------------------------------------------------------
# 10. Wait for readiness
# ---------------------------------------------------------------------------
step "Waiting for services to become ready"

wait_for_service_or_process "API" "${API_BASE_URL}/api/health" "${API_PID}" "${READY_TIMEOUT_SECONDS}"
wait_for_service_or_process "Web" "${WEB_BASE_URL}" "${WEB_PID}" "${READY_TIMEOUT_SECONDS}"

# Show health status
health="$(curl -sS "${API_BASE_URL}/api/health" 2>/dev/null || echo '{}')"
health_lines="$(
  HEALTH_JSON="${health}" "${PY_BIN}" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("HEALTH_JSON", "{}"))
except Exception:
    payload = {}

print(payload.get("llm_status", "unknown"))
print(payload.get("database_backend", "unknown"))
print("true" if payload.get("local_beta_ready") else "false")
print(", ".join(payload.get("local_beta_blockers") or []))
PY
)"
llm_status="$(printf '%s\n' "${health_lines}" | sed -n '1p')"
database_backend="$(printf '%s\n' "${health_lines}" | sed -n '2p')"
local_beta_ready="$(printf '%s\n' "${health_lines}" | sed -n '3p')"
local_beta_blockers="$(printf '%s\n' "${health_lines}" | sed -n '4p')"

log ""
log "============================================"
log "  OpenTutor is running!"
log "  Web:    ${WEB_BASE_URL}"
log "  API:    ${API_BASE_URL}/api"
log "  Health: ${API_BASE_URL}/api/health"
log "  DB:     ${database_backend}"
log ""
if [[ "${llm_status}" == "ready" ]]; then
  log "  LLM: ready"
elif [[ "${llm_status}" == "mock_fallback" ]]; then
  log "  LLM: not ready for beta (connect Ollama or add an API key)"
else
  log "  LLM: ${llm_status}"
fi
if [[ "${local_beta_ready}" == "true" ]]; then
  log "  Local beta readiness: ready"
else
  log "  Local beta readiness: blocked (${local_beta_blockers:-unknown})"
  log "  Tip: open Settings in the app and connect a real LLM provider."
fi
log ""
log "  Press Ctrl+C to stop all services."
log "============================================"

if [[ "${EXIT_AFTER_READY}" == "true" ]]; then
  log ""
  log "  Exit-after-ready mode enabled. Shutting down services with success."
  exit 0
fi

# Keep running until interrupted
wait
