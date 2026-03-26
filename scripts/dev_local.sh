#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3001}"
API_HOST="${API_HOST:-http://localhost:${API_PORT}}"
API_BASE="${API_BASE:-${API_HOST}/api}"
WEB_BASE_URL="${WEB_BASE_URL:-http://localhost:${WEB_PORT}}"
UPLOAD_FILE="${UPLOAD_FILE:-${ROOT_DIR}/tests/e2e/fixtures/sample-course.md}"
SCRAPE_URL="${SCRAPE_URL:-https://opentutor-e2e.local/binary-search}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-240}"
PLAYWRIGHT_PROJECT="${PLAYWRIGHT_PROJECT:-chromium}"
PY_BIN="$(resolve_python_bin || true)"
REPORT_DIR="${REPORT_DIR:-${ROOT_DIR}/tmp}"
REPORT_FILE="${REPORT_FILE:-${REPORT_DIR}/verification-summary.md}"
REPORT_JSON_FILE="${REPORT_JSON_FILE:-${REPORT_DIR}/verification-summary.json}"
REPORT_TMP_FILE=""
CI_API_TEST_TARGETS=(
  tests/test_api_unit_basics.py
  tests/test_services.py
  tests/test_agent_runtime_regressions.py
  tests/test_code_execution_agent.py
  tests/test_eval_regressions.py
  tests/test_ingestion_regressions.py
  tests/test_canvas_parser.py
  tests/test_canvas_router_unit.py
  tests/test_scrape_services.py
  tests/test_scrape_router_unit.py
  tests/test_cognitive_load.py
  tests/test_progress_tracker.py
  tests/test_workspace_tool_actions.py
  tests/test_builtin_ui_behaviors.py
  tests/test_bkt.py
  tests/test_lector.py
  tests/test_loom.py
  tests/test_middleware_security.py
  tests/test_scheduler_engine.py
  tests/test_agenda_ranking.py
  tests/test_agenda_tick.py
  tests/test_agent_state_machine.py
  tests/test_ambient_monitor.py
  tests/test_analytics_events.py
  tests/test_api_integration.py
  tests/test_auth_jwt.py
  tests/test_block_decision_engine.py
  tests/test_capabilities.py
  tests/test_circuit_breaker.py
  tests/test_clarify_parser.py
  tests/test_code_sandbox_policy.py
  tests/test_cognitive_load_calibrator.py
  tests/test_compaction.py
  tests/test_complexity_router.py
  tests/test_diagnosis_classifier.py
  tests/test_difficulty_selector.py
  tests/test_encryption.py
  tests/test_exceptions.py
  tests/test_experiments.py
  tests/test_forgetting_forecast.py
  tests/test_fsrs.py
  tests/test_fsrs_bkt_properties.py
  tests/test_knowledge_graph_ops.py
  tests/test_learning_pipeline_e2e.py
  tests/test_learning_science.py
  tests/test_loom_confusion.py
  tests/test_metrics_middleware.py
  tests/test_optimization_features.py
  tests/test_rate_limiting.py
  tests/test_reflection.py
  tests/test_report_generator.py
  tests/test_security_regressions_authz.py
  tests/test_socratic_engine.py
  tests/test_stream_events.py
  tests/test_teaching_strategies.py
  tests/test_text_utils.py
  tests/test_tool_tracking.py
  tests/test_url_validation.py
  tests/test_usage_tracking.py
  tests/test_utils.py
  tests/test_wiring_snapshots.py
)

usage() {
  cat <<'EOF'
Usage:
  scripts/dev_local.sh up [--build]
  scripts/dev_local.sh check-local-mode
  scripts/dev_local.sh beta-check
  scripts/dev_local.sh migrate-host
  scripts/dev_local.sh preflight
  scripts/dev_local.sh verify-host [--ci-parity]
  scripts/dev_local.sh verify [--all-e2e] [--with-real-llm]
  scripts/dev_local.sh status
  scripts/dev_local.sh logs [service]
  scripts/dev_local.sh down
  scripts/dev_local.sh reset

Commands:
  up              Start redis, api, and web with Docker Compose and wait for readiness.
  check-local-mode Validate that .env and the running API are both using local single-user mode.
  beta-check      Fail unless the running local stack is ready for the technical-user single-user beta.
  migrate-host    Schema helper (no-op in SQLite local mode).
  preflight       Check local prerequisites and stack readiness before running full verification.
  verify-host     Run all checks that can execute on the current host, and mark stack-gated checks as skipped.
  verify          Run smoke, regression, database integration tests, and Playwright E2E against the local stack.
  status          Show compose service status.
  logs            Stream compose logs for all services or a single service.
  down            Stop the local stack.
  reset           Stop the local stack and remove named volumes.

Flags for verify:
  --all-e2e       Run the full Playwright suite instead of the representative course-flow spec.
  --with-real-llm Also run the real-provider API and browser validation checks.

Flags for verify-host:
  --ci-parity     Run CI-equivalent host checks (coverage gate, web build, compileall) without stack-dependent smoke/regression.

Important environment variables:
  API_PORT=8000
  WEB_PORT=3001
  API_HOST=http://localhost:${API_PORT}
  WEB_BASE_URL=http://localhost:${WEB_PORT}
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
  REPORT_TMP_FILE="$(mktemp "${REPORT_DIR}/verification-summary.XXXXXX.tsv")"
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

compose_service_url() {
  local service="$1"
  local container_port="$2"
  local mapping
  local host
  local port

  has_compose || return 1
  mapping="$(compose port "${service}" "${container_port}" 2>/dev/null | tail -n 1)"
  [[ -n "${mapping}" ]] || return 1

  host="${mapping%:*}"
  port="${mapping##*:}"
  host="${host#[}"
  host="${host%]}"
  if [[ "${host}" == "0.0.0.0" || "${host}" == "::" || -z "${host}" ]]; then
    host="localhost"
  fi

  printf 'http://%s:%s\n' "${host}" "${port}"
}

refresh_stack_endpoints_from_compose() {
  local compose_api_host
  local compose_web_base

  compose_api_host="$(compose_service_url api 8000 || true)"
  if [[ -n "${compose_api_host}" ]]; then
    API_HOST="${compose_api_host}"
    API_BASE="${API_HOST}/api"
  fi

  compose_web_base="$(compose_service_url web 3001 || true)"
  if [[ -n "${compose_web_base}" ]]; then
    WEB_BASE_URL="${compose_web_base}"
  fi
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
  provider="$(to_lower "${provider}")"
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
    notes.append(
        "SQLite schema is missing; restart the API with APP_AUTO_CREATE_TABLES=true "
        "or run quickstart/dev_local up again."
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

inspect_local_beta_health() {
  local health_json="$1"

  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found for health JSON inspection."

  HEALTH_JSON="${health_json}" "${PY_BIN}" - <<'PY'
import json
import os

data = json.loads(os.environ["HEALTH_JSON"])
print(
    "|".join(
        [
            "ready" if data.get("local_beta_ready") else "blocked",
            ", ".join(data.get("local_beta_blockers") or []),
            ", ".join(data.get("local_beta_warnings") or []),
            data.get("database_backend", "unknown"),
        ]
    )
)
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

run_host_migrate() {
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found. Expected apps/api/.venv/bin/python or python3.11."
  require_python_311 "${PY_BIN}"
  step "Host migration"
  log "  SQLite-only local mode: Alembic host migration is skipped."
}

run_preflight() {
  local missing=0
  local docker_missing=0
  local compose_missing=0
  local api_ready=0
  local web_ready=0
  init_report

  CURRENT_CHECK="Local deployment mode"
  step "Local deployment mode"
  if bash "${ROOT_DIR}/scripts/check_local_mode.sh" --env-file "${ROOT_DIR}/.env"; then
    record_ok "single-user local mode confirmed"
  else
    record_result "FAIL" "Local deployment mode check failed."
    fail "Local deployment mode check failed."
  fi

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
  refresh_stack_endpoints_from_compose
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

run_ci_parity_consistency_check() {
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found for CI parity consistency check."
  "${PY_BIN}" - <<'PY' "${ROOT_DIR}/pytest.ini" "${ROOT_DIR}/.github/workflows/ci.yml" "${ROOT_DIR}/scripts/dev_local.sh"
import re
import sys
from pathlib import Path

pytest_ini = Path(sys.argv[1]).read_text(encoding="utf-8")
ci_workflow = Path(sys.argv[2]).read_text(encoding="utf-8")
dev_local = Path(sys.argv[3]).read_text(encoding="utf-8")

cov_match = re.search(r"--cov-fail-under=(\d+)", pytest_ini)
if cov_match is None:
    raise SystemExit("pytest.ini does not define --cov-fail-under.")
if int(cov_match.group(1)) < 45:
    raise SystemExit("pytest coverage gate must be at least 45 for this release phase.")

api_tests_section = re.search(
    r"- name:\s*Run API unit tests(?P<body>.*?)(?:\n\s*-\s+name:|\Z)",
    ci_workflow,
    flags=re.S,
)
if api_tests_section is None:
    raise SystemExit("Unable to find 'Run API unit tests' step in CI workflow.")
if "-o addopts=" in api_tests_section.group("body"):
    raise SystemExit("Run API unit tests step must not bypass addopts coverage gate.")

parity_line = None
for line in dev_local.splitlines():
    if "CI parity API tests" in line:
        parity_line = line
        break
if parity_line is None:
    raise SystemExit("scripts/dev_local.sh is missing the CI parity API tests command.")
if "-o addopts=" in parity_line:
    raise SystemExit("CI parity API tests command must not bypass addopts coverage gate.")

print("Coverage gate and pytest addopts parity checks passed.")
PY
}

run_host_verify() {
  local ci_parity=0
  local arg

  for arg in "$@"; do
    case "${arg}" in
      --ci-parity)
        ci_parity=1
        ;;
      *)
        fail "Unknown verify-host flag: ${arg}"
        ;;
    esac
  done

  if (( ci_parity )); then
    :
  fi

  require_cmd curl npx npm
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found. Expected apps/api/.venv/bin/python or python3.11."
  require_python_311 "${PY_BIN}"
  [[ -f "${UPLOAD_FILE}" ]] || fail "Upload fixture not found: ${UPLOAD_FILE}"
  init_report
  refresh_stack_endpoints_from_compose

  if (( ci_parity )); then
    run_reported "CI parity gate consistency" run_ci_parity_consistency_check
    run_reported "CI parity API tests" "${PY_BIN}" -m pytest "${CI_API_TEST_TARGETS[@]}" -q
    run_reported "CI parity compile API sources" "${PY_BIN}" -m compileall -q -x '/\\.venv/' apps/api
    run_reported "CI parity frontend lint" bash -lc "cd '${ROOT_DIR}/apps/web' && npm run lint"
    run_reported "CI parity frontend build" bash -lc "cd '${ROOT_DIR}/apps/web' && npm run build"
  else
    run_reported "Service-layer tests" "${PY_BIN}" -m pytest tests/test_services.py -q -o addopts=
    run_reported "Agent regression tests" "${PY_BIN}" -m pytest tests/test_eval_regressions.py tests/test_agent_runtime_regressions.py -q -o addopts=
    run_reported "Frontend lint" bash -lc "cd '${ROOT_DIR}/apps/web' && npm run lint"
    run_reported "Playwright spec discovery" npx playwright test tests/e2e/activity-tasks.spec.ts --list
    run_reported "SQLite integration spot check" "${PY_BIN}" -m pytest tests/test_sqlite_mode.py -q -o addopts=
  fi

  if (( ci_parity )); then
    CURRENT_CHECK="Stack smoke/regression"
    record_skip "Stack smoke/regression skipped in --ci-parity mode. Run STRICT_BENCHMARK=1 bash scripts/run_regression_benchmark.sh against a running stack."
  elif is_url_ready "${API_BASE}/health" && is_url_ready "${WEB_BASE_URL}"; then
    CURRENT_CHECK="Stack smoke/regression"
    guard_stack_health
    run_reported "Smoke test against running stack" bash -lc "API_BASE='${API_HOST}' UPLOAD_FILE='${UPLOAD_FILE}' SCRAPE_URL='${SCRAPE_URL}' STRICT_LLM='${STRICT_LLM:-0}' bash '${ROOT_DIR}/scripts/smoke_test.sh'"
    run_reported "Regression benchmark against running stack" bash -lc "API_BASE='${API_BASE}' UPLOAD_FILE='${UPLOAD_FILE}' PYTHON_BIN='${PY_BIN}' STRICT_BENCHMARK='0' bash '${ROOT_DIR}/scripts/run_regression_benchmark.sh'"
  else
    CURRENT_CHECK="Stack smoke/regression"
    record_skip "Stack smoke/regression skipped because API or web is not running"
  fi

  log ""
  log "Report written to ${REPORT_FILE}"
  log "JSON report written to ${REPORT_JSON_FILE}"
}

run_beta_check() {
  require_cmd curl
  [[ -n "${PY_BIN}" ]] || fail "Python interpreter not found. Expected apps/api/.venv/bin/python or python3.11."
  require_python_311 "${PY_BIN}"
  [[ -f "${UPLOAD_FILE}" ]] || fail "Upload fixture not found: ${UPLOAD_FILE}"
  init_report
  refresh_stack_endpoints_from_compose

  CURRENT_CHECK="Local deployment mode"
  step "Local deployment mode"
  bash "${ROOT_DIR}/scripts/check_local_mode.sh" --env-file "${ROOT_DIR}/.env"
  record_ok "single-user local mode confirmed"

  CURRENT_CHECK="Stack readiness"
  step "Stack readiness"
  wait_for_url "API health" "${API_BASE}/health" "${WAIT_TIMEOUT_SECONDS}"
  wait_for_url "Web app" "${WEB_BASE_URL}" "${WAIT_TIMEOUT_SECONDS}"
  record_ok "API and web became ready"
  guard_stack_health

  local health_json
  local beta_state
  local beta_blockers
  local beta_warnings
  local beta_backend
  local beta_diag
  local llm_primary
  local llm_status

  health_json="$(fetch_api_health_json)"
  beta_diag="$(inspect_local_beta_health "${health_json}")"
  IFS='|' read -r beta_state beta_blockers beta_warnings beta_backend <<< "${beta_diag}"
  llm_primary="$(json_get_field "${health_json}" "llm_primary")"
  llm_status="$(json_get_field "${health_json}" "llm_status")"

  CURRENT_CHECK="Local beta readiness"
  step "Local beta readiness"
  if [[ "${beta_state}" != "ready" ]]; then
    record_result "FAIL" "Local beta blockers: ${beta_blockers:-unknown} (llm=${llm_primary:-unknown}/${llm_status:-unknown})"
    fail "Local beta blockers detected: ${beta_blockers:-unknown} (llm=${llm_primary:-unknown}/${llm_status:-unknown})"
  fi
  record_ok "Running stack is ready for the local single-user beta (${beta_backend})"
  if [[ -n "${beta_warnings}" ]]; then
    record_warn "Non-blocking warnings: ${beta_warnings}"
  fi

  run_reported "Strict smoke test" bash -lc "API_BASE='${API_HOST}' UPLOAD_FILE='${UPLOAD_FILE}' SCRAPE_URL='${SCRAPE_URL}' STRICT_LLM='1' bash '${ROOT_DIR}/scripts/smoke_test.sh'"

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
  refresh_stack_endpoints_from_compose

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
  run_reported "SQLite integration tests" "${PY_BIN}" -m pytest tests/test_sqlite_mode.py -q -o addopts=

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
    bash "${ROOT_DIR}/scripts/check_local_mode.sh" --env-file "${ROOT_DIR}/.env" --skip-api
    step "Starting local stack"
    if [[ "${1:-}" == "--build" ]]; then
      compose up -d --build redis api web
    else
      compose up -d redis api web
    fi
    refresh_stack_endpoints_from_compose
    wait_for_url "API health" "${API_BASE}/health" "${WAIT_TIMEOUT_SECONDS}"
    wait_for_url "Web app" "${WEB_BASE_URL}" "${WAIT_TIMEOUT_SECONDS}"
    log "  API_HOST=${API_HOST}"
    log "  WEB_BASE_URL=${WEB_BASE_URL}"
    compose ps
    ;;
  migrate-host)
    run_host_migrate
    ;;
  check-local-mode)
    bash "${ROOT_DIR}/scripts/check_local_mode.sh" --env-file "${ROOT_DIR}/.env"
    ;;
  beta-check)
    run_beta_check
    ;;
  preflight)
    run_preflight
    ;;
  verify-host)
    run_host_verify "$@"
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
