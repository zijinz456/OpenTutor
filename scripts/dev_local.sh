#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_HOST="${API_HOST:-http://localhost:8000}"
API_BASE="${API_BASE:-${API_HOST}/api}"
WEB_BASE_URL="${WEB_BASE_URL:-http://localhost:3000}"
UPLOAD_FILE="${UPLOAD_FILE:-${ROOT_DIR}/tests/e2e/fixtures/sample-course.md}"
SCRAPE_URL="${SCRAPE_URL:-https://opentutor-e2e.local/binary-search}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-240}"
PLAYWRIGHT_PROJECT="${PLAYWRIGHT_PROJECT:-chromium}"
PY_BIN="$(resolve_python_bin || true)"
REPORT_DIR="${REPORT_DIR:-${ROOT_DIR}/tmp}"
REPORT_FILE="${REPORT_FILE:-${REPORT_DIR}/verification-summary.md}"
REPORT_JSON_FILE="${REPORT_JSON_FILE:-${REPORT_DIR}/verification-summary.json}"
REPORT_TMP_FILE=""

usage() {
  cat <<'EOF'
Usage:
  scripts/dev_local.sh up [--build]
  scripts/dev_local.sh migrate-host
  scripts/dev_local.sh preflight
  scripts/dev_local.sh verify-host
  scripts/dev_local.sh verify [--all-e2e] [--with-real-llm]
  scripts/dev_local.sh status
  scripts/dev_local.sh logs [service]
  scripts/dev_local.sh down
  scripts/dev_local.sh reset

Commands:
  up              Start db, redis, api, and web with Docker Compose and wait for readiness.
  migrate-host    Run Alembic migrations with the resolved host Python interpreter.
  preflight       Check local prerequisites and stack readiness before running full verification.
  verify-host     Run all checks that can execute on the current host, and mark stack-gated checks as skipped.
  verify          Run smoke, regression, DB-backed integration tests, and Playwright E2E against the local stack.
  status          Show compose service status.
  logs            Stream compose logs for all services or a single service.
  down            Stop the local stack.
  reset           Stop the local stack and remove named volumes.

Flags for verify:
  --all-e2e       Run the full Playwright suite instead of the representative course-flow spec.
  --with-real-llm Also run the real-provider API and browser validation checks.

Important environment variables:
  API_HOST=http://localhost:8000
  WEB_BASE_URL=http://localhost:3000
  UPLOAD_FILE=tests/e2e/fixtures/sample-course.md
  SCRAPE_URL=https://opentutor-e2e.local/binary-search
  PLAYWRIGHT_PROJECT=chromium
EOF
}

record_ok() {
  printf 'OK: %s\n' "$*"
  record_result "PASS" "$*"
}

record_skip() {
  printf 'SKIP: %s\n' "$*"
  record_result "SKIP" "$*"
}

record_warn() {
  printf 'WARN: %s\n' "$*"
  record_result "WARN" "$*"
}

init_report() {
  mkdir -p "${REPORT_DIR}"
  rm -f "${REPORT_DIR}/verification-summary.XXXXXX.tsv"
  REPORT_TMP_FILE="$(mktemp -p "${REPORT_DIR}" verification-summary.XXXXXX.tsv)"
  trap finalize_report EXIT
  cat > "${REPORT_FILE}" <<EOF
# Verification Summary

- Generated at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
- Host: $(hostname)
- Working directory: ${ROOT_DIR}

| Status | Check | Details |
|---|---|---|
EOF
  : > "${REPORT_TMP_FILE}"
}

record_result() {
  local status="$1"
  local details="$2"
  printf '| %s | %s | %s |\n' "${status}" "${CURRENT_CHECK:-n/a}" "${details}" >> "${REPORT_FILE}"
  printf '%s\t%s\t%s\n' "${status}" "${CURRENT_CHECK:-n/a}" "${details}" >> "${REPORT_TMP_FILE}"
}

finalize_report() {
  [[ -n "${REPORT_TMP_FILE}" ]] || return 0
  [[ -f "${REPORT_TMP_FILE}" ]] || return 0

  if [[ -n "${PY_BIN}" ]]; then
    "${PY_BIN}" - <<'PY' "${REPORT_TMP_FILE}" "${REPORT_JSON_FILE}" "${ROOT_DIR}"
import json
import socket
import sys
from collections import Counter
from datetime import datetime, timezone

rows_path, json_path, root_dir = sys.argv[1:4]
entries = []
counts = Counter()

with open(rows_path, encoding="utf-8") as fh:
    for raw_line in fh:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        status, check, details = line.split("\t", 2)
        entries.append({"status": status, "check": check, "details": details})
        counts[status] += 1

payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "host": socket.gethostname(),
    "working_directory": root_dir,
    "entries": entries,
    "counts": dict(sorted(counts.items())),
}

with open(json_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY
  fi

  rm -f "${REPORT_TMP_FILE}"
  REPORT_TMP_FILE=""
}

run_reported() {
  local label="$1"
  shift
  CURRENT_CHECK="${label}"
  step "${label}"
  if "$@"; then
    record_ok "${label}"
  else
    local exit_code=$?
    record_result "FAIL" "Command failed with exit code ${exit_code}"
    return "${exit_code}"
  fi
}

is_url_ready() {
  local url="$1"
  local status
  status="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"
  [[ "$status" =~ ^(2|3) ]]
}

fetch_api_health_json() {
  curl -fsS "${API_BASE}/health" 2>/dev/null
}

set_mock_llm_runtime() {
  local payload='{"provider":"mock","model":"mock-fallback","llm_required":false}'
  curl -fsS \
    -X PUT "${API_BASE}/preferences/runtime/llm" \
    -H "Content-Type: application/json" \
    --data "${payload}" >/dev/null
}

CAPTURED_LLM_PROVIDER=""
CAPTURED_LLM_MODEL=""
CAPTURED_LLM_REQUIRED=""

capture_llm_runtime() {
  local runtime_json
  local runtime_values

  [[ -n "${PY_BIN}" ]] || return 1
  runtime_json="$(curl -fsS "${API_BASE}/preferences/runtime/llm")"
  runtime_values="$(
    CURRENT_RUNTIME_JSON="${runtime_json}" "${PY_BIN}" - <<'PY'
import json
import os

payload = json.loads(os.environ["CURRENT_RUNTIME_JSON"])
print(payload.get("provider", ""))
print(payload.get("model", ""))
print("true" if payload.get("llm_required") else "false")
PY
  )"

  CAPTURED_LLM_PROVIDER="$(printf '%s\n' "${runtime_values}" | sed -n '1p')"
  CAPTURED_LLM_MODEL="$(printf '%s\n' "${runtime_values}" | sed -n '2p')"
  CAPTURED_LLM_REQUIRED="$(printf '%s\n' "${runtime_values}" | sed -n '3p')"
}

restore_captured_llm_runtime() {
  local payload

  [[ -n "${CAPTURED_LLM_PROVIDER}" ]] || return 0
  [[ -n "${PY_BIN}" ]] || return 1
  payload="$(
    RESTORE_PROVIDER="${CAPTURED_LLM_PROVIDER}" \
    RESTORE_MODEL="${CAPTURED_LLM_MODEL}" \
    RESTORE_REQUIRED="${CAPTURED_LLM_REQUIRED:-false}" \
    "${PY_BIN}" - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "provider": os.environ["RESTORE_PROVIDER"],
            "model": os.environ["RESTORE_MODEL"],
            "llm_required": os.environ["RESTORE_REQUIRED"].lower() == "true",
        }
    )
)
PY
  )"

  curl -fsS \
    -X PUT "${API_BASE}/preferences/runtime/llm" \
    -H "Content-Type: application/json" \
    --data "${payload}" >/dev/null
}

prepare_real_llm_env() {
  local provider
  local model

  for key in OPENAI_API_KEY ANTHROPIC_API_KEY DEEPSEEK_API_KEY OPENROUTER_API_KEY GEMINI_API_KEY GROQ_API_KEY; do
    if [[ -n "${!key:-}" ]]; then
      return 0
    fi
  done

  provider="${PLAYWRIGHT_REAL_LLM_PROVIDER:-${REAL_LLM_PROVIDER:-${LLM_PROVIDER:-}}}"
  provider="${provider,,}"
  if [[ -z "${provider}" ]]; then
    provider="$(detect_local_llm_provider || true)"
  fi
  [[ -n "${provider}" ]] || return 1

  export REAL_LLM_PROVIDER="${provider}"
  export PLAYWRIGHT_REAL_LLM_PROVIDER="${provider}"

  case "${provider}" in
    ollama)
      model="${REAL_LLM_MODEL:-${OLLAMA_MODEL:-$(detect_ollama_model || true)}}"
      model="${model:-llama3.2:1b}"
      export OLLAMA_MODEL="${model}"
      ;;
    lmstudio)
      model="${REAL_LLM_MODEL:-${LMSTUDIO_MODEL:-default}}"
      export LMSTUDIO_MODEL="${model}"
      ;;
    textgenwebui)
      model="${REAL_LLM_MODEL:-${TEXTGENWEBUI_MODEL:-default}}"
      export TEXTGENWEBUI_MODEL="${model}"
      ;;
    *)
      model="${REAL_LLM_MODEL:-${LLM_MODEL:-}}"
      ;;
  esac

  [[ -n "${model:-}" ]] && export REAL_LLM_MODEL="${model}"
  [[ -n "${model:-}" ]] && export LLM_MODEL="${model}"
  return 0
}

inspect_api_health() {
  local health_json="$1"

  [[ -n "${PY_BIN}" ]] || {
    printf 'ok\tunable to inspect health JSON because no Python interpreter was resolved\n'
    return 0
  }

  HEALTH_JSON="${health_json}" "${PY_BIN}" - <<'PY'
import json
import os

raw = os.environ.get("HEALTH_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("invalid\tHealth endpoint did not return valid JSON.")
    raise SystemExit(0)

status = "ok"
notes: list[str] = []
expected_keys = {"deployment_mode", "llm_status", "code_sandbox_runtime_available"}

if not expected_keys.issubset(data):
    status = "legacy_contract"
    notes.append("Health payload does not match the current OpenTutor API contract.")

if data.get("migration_required") or data.get("schema") == "missing":
    status = "migration_required"
    migration_status = data.get("migration_status")
    if migration_status == "version_table_missing":
        notes.append(
            "Database tables exist but Alembic tracking is missing; verify the schema and run "
            "'cd apps/api && python -m alembic stamp head'."
        )
    elif migration_status == "out_of_date":
        notes.append(
            "Database migrations are behind the app; run 'cd apps/api && python -m alembic upgrade head'."
        )
    elif migration_status == "inspection_error":
        notes.append(
            "Migration inspection failed; verify Alembic files and database connectivity before retrying."
        )
    else:
        notes.append(
            "Database schema is missing; run 'cd apps/api && python -m alembic upgrade head' or restart the Docker API service."
        )

if data.get("code_sandbox_runtime_available") is False:
    if status == "ok":
        status = "ok_with_warnings"
    runtime = data.get("code_sandbox_runtime") or "container runtime"
    notes.append(f"Code sandbox runtime '{runtime}' is unavailable on this host.")

if data.get("status") == "degraded" and status == "ok":
    status = "ok_with_warnings"
    notes.append("API reports degraded health.")

if not notes:
    notes.append("schema ready")

print(f"{status}\t{'; '.join(notes)}")
PY
}

guard_stack_health() {
  local health_json
  local diagnosis
  local health_state
  local health_note

  health_json="$(fetch_api_health_json || true)"
  [[ -n "${health_json}" ]] || return 0

  diagnosis="$(inspect_api_health "${health_json}")"
  IFS=$'\t' read -r health_state health_note <<< "${diagnosis}"

  case "${health_state}" in
    ok)
      [[ "${health_note}" == "schema ready" ]] || record_ok "${health_note}"
      ;;
    ok_with_warnings)
      record_warn "${health_note}"
      ;;
    migration_required)
      record_result "FAIL" "${health_note}"
      fail "${health_note}"
      ;;
    legacy_contract)
      record_result "FAIL" "${health_note} This usually means ${API_HOST} is serving an older or different API process."
      fail "${health_note} This usually means ${API_HOST} is serving an older or different API process."
      ;;
    invalid)
      record_result "FAIL" "${health_note}"
      fail "${health_note}"
      ;;
  esac
}

check_db_integration_once() {
  local tmp_output
  tmp_output="$(mktemp)"
  if "${PY_BIN}" -m pytest tests/test_api_integration.py -k weekly_prep_creates_agent_task -q >"${tmp_output}" 2>&1; then
    cat "${tmp_output}"
    rm -f "${tmp_output}"
    return 0
  fi

  cat "${tmp_output}"
  if grep -Eq "PermissionError: \[Errno 1\] Operation not permitted|5432|pgvector extension unavailable" "${tmp_output}"; then
    rm -f "${tmp_output}"
    return 2
  fi

  rm -f "${tmp_output}"
  return 1
}

run_host_migrate() {
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found. Expected apps/api/.venv/bin/python or python3.11."
  require_python_311 "${PY_BIN}"

  step "Running Alembic migrations with ${PY_BIN}"
  (
    cd "${ROOT_DIR}/apps/api"
    "${PY_BIN}" -m alembic upgrade head
  )

  if is_url_ready "${API_BASE}/health"; then
    CURRENT_CHECK="Stack readiness"
    guard_stack_health
  fi
}

run_preflight() {
  local missing=0
  local docker_missing=0
  local compose_missing=0
  local api_ready=0
  local web_ready=0
  init_report

  CURRENT_CHECK="Host prerequisites"
  step "Host prerequisites"
  if command -v docker >/dev/null 2>&1; then
    record_ok "docker installed"
    if has_compose; then
      record_ok "$(compose_name) available"
    else
      record_warn "docker compose unavailable"
      compose_missing=1
    fi
  else
    record_warn "docker not installed"
    docker_missing=1
  fi

  for cmd in curl npm npx; do
    if command -v "${cmd}" >/dev/null 2>&1; then
      record_ok "${cmd} installed"
    else
      record_warn "${cmd} missing"
      missing=1
    fi
  done

  if [[ -n "${PY_BIN}" ]]; then
    require_python_311 "${PY_BIN}"
    record_ok "python available at ${PY_BIN}"
  else
    record_warn "python interpreter not found"
    missing=1
  fi

  if [[ -f "${UPLOAD_FILE}" ]]; then
    record_ok "upload fixture present: ${UPLOAD_FILE}"
  else
    record_warn "upload fixture missing: ${UPLOAD_FILE}"
    missing=1
  fi

  CURRENT_CHECK="Stack readiness"
  step "Stack readiness"
  if is_url_ready "${API_BASE}/health"; then
    api_ready=1
    record_ok "api reachable: ${API_BASE}/health"
    guard_stack_health
  else
    record_warn "api not reachable: ${API_BASE}/health"
  fi

  if is_url_ready "${WEB_BASE_URL}"; then
    web_ready=1
    record_ok "web reachable: ${WEB_BASE_URL}"
  else
    record_warn "web not reachable: ${WEB_BASE_URL}"
  fi

  if has_real_llm_env; then
    record_ok "real LLM credentials detected"
  else
    record_warn "no real LLM credentials detected"
  fi

  if (( docker_missing || compose_missing )); then
    if (( api_ready && web_ready )); then
      record_warn "docker unavailable, but an existing local stack is already reachable; verify can continue"
    else
      missing=1
    fi
  fi

  if (( missing )); then
    record_result "FAIL" "Preflight found missing host prerequisites."
    fail "Preflight found missing host prerequisites."
  fi
}

run_host_verify() {
  require_cmd curl npx npm
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found. Expected apps/api/.venv/bin/python or python3.11."
  require_python_311 "${PY_BIN}"
  [[ -f "${UPLOAD_FILE}" ]] || fail "Upload fixture not found: ${UPLOAD_FILE}"
  init_report

  run_reported "Service-layer tests" "${PY_BIN}" -m pytest tests/test_services.py -q
  run_reported "Agent regression tests" "${PY_BIN}" -m pytest tests/test_eval_regressions.py tests/test_agent_runtime_regressions.py -q
  run_reported "Frontend lint" bash -lc "cd '${ROOT_DIR}/apps/web' && npm run lint"
  run_reported "Playwright spec discovery" npx playwright test tests/e2e/activity-tasks.spec.ts --list

  CURRENT_CHECK="DB-backed integration spot check"
  step "DB-backed integration spot check"
  if check_db_integration_once; then
    record_ok "DB-backed integration available"
  else
    status=$?
    if [[ "${status}" == "2" ]]; then
      record_skip "DB-backed integration unavailable on this host (PostgreSQL or localhost:5432 access blocked)"
    else
      fail "DB-backed integration spot check failed for a code reason"
    fi
  fi

  if is_url_ready "${API_BASE}/health" && is_url_ready "${WEB_BASE_URL}"; then
    CURRENT_CHECK="Stack smoke/regression"
    guard_stack_health
    run_reported "Smoke test against running stack" bash -lc "API_BASE='${API_HOST}' UPLOAD_FILE='${UPLOAD_FILE}' SCRAPE_URL='${SCRAPE_URL}' STRICT_LLM='${STRICT_LLM:-0}' bash '${ROOT_DIR}/scripts/smoke_test.sh'"
    run_reported "Regression benchmark against running stack" bash -lc "API_BASE='${API_BASE}' UPLOAD_FILE='${UPLOAD_FILE}' PYTHON_BIN='${PY_BIN}' bash '${ROOT_DIR}/scripts/run_regression_benchmark.sh'"
  else
    CURRENT_CHECK="Stack smoke/regression"
    record_skip "Stack smoke/regression skipped because API or web is not running"
  fi

  log ""
  log "Report written to ${REPORT_FILE}"
  log "JSON report written to ${REPORT_JSON_FILE}"
}

run_verify() {
  local run_all_e2e=0
  local run_real_llm=0
  local arg
  local e2e_targets=()

  for arg in "$@"; do
    case "$arg" in
      --all-e2e)
        run_all_e2e=1
        ;;
      --with-real-llm)
        run_real_llm=1
        ;;
      *)
        fail "Unknown verify flag: ${arg}"
        ;;
    esac
  done

  run_preflight
  require_cmd curl npx npm
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found. Expected apps/api/.venv/bin/python or python3.11."
  require_python_311 "${PY_BIN}"
  [[ -f "${UPLOAD_FILE}" ]] || fail "Upload fixture not found: ${UPLOAD_FILE}"

  CURRENT_CHECK="Stack readiness wait"
  step "Waiting for local stack"
  wait_for_url "API health" "${API_BASE}/health" "${WAIT_TIMEOUT_SECONDS}"
  wait_for_url "Web app" "${WEB_BASE_URL}" "${WAIT_TIMEOUT_SECONDS}"
  record_ok "API and web became ready"
  CURRENT_CHECK="Stack readiness wait"
  guard_stack_health

  capture_llm_runtime || fail "Unable to capture current LLM runtime configuration"
  run_reported "Switch runtime to mock for baseline verification" set_mock_llm_runtime

  run_reported "Smoke test" bash -lc "API_BASE='${API_HOST}' UPLOAD_FILE='${UPLOAD_FILE}' SCRAPE_URL='${SCRAPE_URL}' STRICT_LLM='${STRICT_LLM:-0}' bash '${ROOT_DIR}/scripts/smoke_test.sh'"
  run_reported "Regression benchmark" bash -lc "API_BASE='${API_BASE}' UPLOAD_FILE='${UPLOAD_FILE}' PYTHON_BIN='${PY_BIN}' bash '${ROOT_DIR}/scripts/run_regression_benchmark.sh'"
  run_reported "DB-backed integration tests" "${PY_BIN}" -m pytest tests/test_api_integration.py -q

  if (( run_all_e2e )); then
    run_reported "Playwright E2E suite" bash -lc "PLAYWRIGHT_USE_EXISTING_SERVER=1 PLAYWRIGHT_BASE_URL='${WEB_BASE_URL}' PLAYWRIGHT_API_URL='${API_BASE}' npx playwright test --project='${PLAYWRIGHT_PROJECT}'"
  else
    e2e_targets=(tests/e2e/course-flow.spec.ts)
    run_reported "Playwright E2E course flow" bash -lc "PLAYWRIGHT_USE_EXISTING_SERVER=1 PLAYWRIGHT_BASE_URL='${WEB_BASE_URL}' PLAYWRIGHT_API_URL='${API_BASE}' npx playwright test ${e2e_targets[*]} --project='${PLAYWRIGHT_PROJECT}'"
  fi

  if (( run_real_llm )); then
    prepare_real_llm_env || fail "--with-real-llm requires a real LLM provider (cloud API key or reachable local runtime)"

    run_reported "Real LLM API validation" bash -lc "API_BASE='${API_HOST}' bash '${ROOT_DIR}/scripts/llm_integration_test.sh'"
    run_reported "Real LLM browser validation" bash -lc "PLAYWRIGHT_USE_EXISTING_SERVER=1 PLAYWRIGHT_BASE_URL='${WEB_BASE_URL}' PLAYWRIGHT_API_URL='${API_BASE}' npx playwright test tests/e2e/llm-real.spec.ts --project='${PLAYWRIGHT_PROJECT}'"
  fi

  run_reported "Restore original LLM runtime" restore_captured_llm_runtime

  log ""
  log "Report written to ${REPORT_FILE}"
  log "JSON report written to ${REPORT_JSON_FILE}"
}

command="${1:-help}"
shift || true

case "${command}" in
  up)
    require_cmd docker curl
    step "Starting local stack"
    if [[ "${1:-}" == "--build" ]]; then
      compose up -d --build db redis api web
    else
      compose up -d db redis api web
    fi
    wait_for_url "API health" "${API_BASE}/health" "${WAIT_TIMEOUT_SECONDS}"
    wait_for_url "Web app" "${WEB_BASE_URL}" "${WAIT_TIMEOUT_SECONDS}"
    compose ps
    ;;
  migrate-host)
    run_host_migrate
    ;;
  preflight)
    run_preflight
    ;;
  verify-host)
    run_host_verify
    ;;
  verify)
    run_verify "$@"
    ;;
  status)
    require_cmd docker
    compose ps
    ;;
  logs)
    require_cmd docker
    compose logs -f --tail=200 "$@"
    ;;
  down)
    require_cmd docker
    compose down
    ;;
  reset)
    require_cmd docker
    compose down -v --remove-orphans
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    fail "Unknown command: ${command}"
    ;;
esac

finalize_report
