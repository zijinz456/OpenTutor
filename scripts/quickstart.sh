#!/usr/bin/env bash
# OpenTutor — One-click local development setup & launch
# Usage: ./scripts/quickstart.sh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_DIR="${ROOT_DIR}/apps/api"
WEB_DIR="${ROOT_DIR}/apps/web"
ENV_FILE="${ROOT_DIR}/.env"
VENV_DIR="${API_DIR}/.venv"
API_PID=""
WEB_PID=""

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
  log ""
  log "Shutting down..."
  [[ -n "${WEB_PID}" ]] && kill "${WEB_PID}" 2>/dev/null && wait "${WEB_PID}" 2>/dev/null
  [[ -n "${API_PID}" ]] && kill "${API_PID}" 2>/dev/null && wait "${API_PID}" 2>/dev/null
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

# PostgreSQL
if ! command -v psql >/dev/null 2>&1; then
  fail "PostgreSQL client (psql) not found. Install: $(install_hint postgresql)"
fi
log "  psql found"

# Python 3.11
PY_BIN="$(resolve_python_bin || true)"
if [[ -z "${PY_BIN}" ]]; then
  fail "Python not found. OpenTutor requires Python 3.11. Install: $(install_hint python)"
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
  log "  .env created. You can add your LLM API key later for full functionality."
  log "  (The app will use mock responses until an API key is configured.)"
else
  log "  .env already exists"
fi

# Source .env for this script
load_env_file "${ENV_FILE}"

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
"${PIP_BIN}" install -q -r "${API_DIR}/requirements.txt"
log "  Done"

# ---------------------------------------------------------------------------
# 5. Database setup
# ---------------------------------------------------------------------------
step "Database"

DB_NAME="opentutor"
DB_USER="${DATABASE_URL##*://}"
DB_USER="${DB_USER%%:*}"

# Check if PostgreSQL is running
if ! pg_isready -q 2>/dev/null; then
  log "  PostgreSQL is not running. Attempting to start ..."
  start_postgresql
  if ! pg_isready -q 2>/dev/null; then
    fail "PostgreSQL is not running. Start it manually:
  macOS:   brew services start postgresql@16
  Linux:   sudo systemctl start postgresql
  Windows: Start-Service postgresql-x64-16  (run as admin)"
  fi
fi

# Create database if it doesn't exist
if psql -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw "${DB_NAME}"; then
  log "  Database '${DB_NAME}' already exists"
else
  log "  Creating database '${DB_NAME}' ..."
  createdb "${DB_NAME}" 2>/dev/null || true
fi

# Enable pgvector extension
psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || \
  log "  Warning: Could not create pgvector extension. Install: $(install_hint pgvector)"

# ---------------------------------------------------------------------------
# 6. Database migrations
# ---------------------------------------------------------------------------
step "Running database migrations"

cd "${API_DIR}"
"${PY_BIN}" -m alembic upgrade head
log "  Migrations complete"

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

cd "${API_DIR}"
log "  Starting API server (port 8000) ..."
"${PY_BIN}" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload 2>&1 | sed 's/^/  [api] /' &
API_PID=$!

cd "${WEB_DIR}"
log "  Starting Web server (port 3000) ..."
npm run dev 2>&1 | sed 's/^/  [web] /' &
WEB_PID=$!

# ---------------------------------------------------------------------------
# 10. Wait for readiness
# ---------------------------------------------------------------------------
step "Waiting for services to become ready"

wait_for_url "API" "http://localhost:8000/api/health" 60
wait_for_url "Web" "http://localhost:3000" 60

# Show health status
health="$(curl -sS http://localhost:8000/api/health 2>/dev/null || echo '{}')"
llm_status="$(echo "${health}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("llm_status","unknown"))' 2>/dev/null || echo "unknown")"

log ""
log "============================================"
log "  OpenTutor is running!"
log "  Web:    http://localhost:3000"
log "  API:    http://localhost:8000/api"
log "  Health: http://localhost:8000/api/health"
log ""
if [[ "${llm_status}" == "ready" ]]; then
  log "  LLM: ready"
elif [[ "${llm_status}" == "mock_fallback" ]]; then
  log "  LLM: mock mode (add an API key to .env for real responses)"
else
  log "  LLM: ${llm_status}"
fi
log ""
log "  Press Ctrl+C to stop all services."
log "============================================"

# Keep running until interrupted
wait
