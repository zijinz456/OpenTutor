#!/usr/bin/env bash

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '%s\n' "$*"
}

step() {
  printf '\n== %s ==\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: ${cmd}"
  done
}

create_temp_dir() {
  mktemp -d "${TMPDIR:-/tmp}/opentutor.XXXXXX"
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if [[ -x "${ROOT_DIR}/apps/api/.venv/bin/python" ]]; then
    printf '%s\n' "${ROOT_DIR}/apps/api/.venv/bin/python"
    return 0
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    command -v python3.11
    return 0
  fi
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf '%s\n' "${ROOT_DIR}/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
}

require_python_311() {
  local py_bin="$1"
  local version

  version="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "${version}" != "3.11" ]]; then
    fail "OpenTutor requires Python 3.11 for local verification. Found ${version} at ${py_bin}."
  fi
}

json_get_field() {
  local json="$1"
  local field="$2"
  local py_bin="${PYTHON_BIN:-}"

  if [[ -z "${py_bin}" ]]; then
    py_bin="$(resolve_python_bin || true)"
  fi
  if [[ -z "${py_bin}" ]]; then
    py_bin="$(command -v python3 || command -v python || true)"
  fi
  if [[ -z "${py_bin}" ]]; then
    printf '\n'
    return 0
  fi

  JSON_INPUT="$json" "${py_bin}" - "$field" <<'PY'
import json
import os
import sys

field = sys.argv[1]
raw = os.environ.get("JSON_INPUT", "")
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)

if isinstance(data, dict):
    value = data.get(field, "")
    print("" if value is None else str(value))
else:
    print("")
PY
}

load_env_file() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || return 1
  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a
}

set_env_value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local py_bin="${PYTHON_BIN:-}"

  [[ -f "${env_file}" ]] || : > "${env_file}"

  if [[ -z "${py_bin}" ]]; then
    py_bin="$(resolve_python_bin || true)"
  fi
  if [[ -z "${py_bin}" ]]; then
    py_bin="$(command -v python3 || command -v python || true)"
  fi

  if [[ -n "${py_bin}" ]]; then
    "${py_bin}" - <<'PY' "${env_file}" "${key}" "${value}"
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
updated = False
result = []
for line in lines:
    if line.startswith(f"{key}="):
        result.append(f"{key}={value}")
        updated = True
    else:
        result.append(line)
if not updated:
    result.append(f"{key}={value}")
env_path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY
    return 0
  fi

  local tmp_file
  tmp_file="$(mktemp "${TMPDIR:-/tmp}/opentutor-env.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { updated = 0 }
    index($0, key "=") == 1 { print key "=" value; updated = 1; next }
    { print }
    END { if (!updated) print key "=" value }
  ' "${env_file}" > "${tmp_file}"
  mv "${tmp_file}" "${env_file}"
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local timeout_seconds="${3:-180}"
  local started_at
  local status

  started_at="$(date +%s)"
  while true; do
    status="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"
    if [[ "$status" =~ ^(2|3) ]]; then
      log "READY: ${label} (${url})"
      return 0
    fi
    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      fail "${label} did not become ready within ${timeout_seconds}s: ${url}"
    fi
    sleep 2
  done
}

has_real_llm_env() {
  local keys=(
    OPENAI_API_KEY
    ANTHROPIC_API_KEY
    DEEPSEEK_API_KEY
    OPENROUTER_API_KEY
    GEMINI_API_KEY
    GROQ_API_KEY
  )
  local key
  for key in "${keys[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      return 0
    fi
  done
  case "${PLAYWRIGHT_REAL_LLM_PROVIDER:-${REAL_LLM_PROVIDER:-${LLM_PROVIDER:-}}}" in
    ollama|lmstudio|textgenwebui|custom)
      return 0
      ;;
  esac
  if command -v curl >/dev/null 2>&1; then
    if curl -sS -o /dev/null -w '%{http_code}' "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}/api/tags" 2>/dev/null | grep -Eq '^(2|3)'; then
      return 0
    fi
    if curl -sS -o /dev/null -w '%{http_code}' "${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234}/v1/models" 2>/dev/null | grep -Eq '^(2|3)'; then
      return 0
    fi
    if curl -sS -o /dev/null -w '%{http_code}' "${TEXTGENWEBUI_BASE_URL:-http://127.0.0.1:5000}/v1/models" 2>/dev/null | grep -Eq '^(2|3)'; then
      return 0
    fi
  fi
  return 1
}

detect_local_llm_provider() {
  if curl -sS -o /dev/null -w '%{http_code}' "${OLLAMA_BASE_URL:-http://127.0.0.1:11434}/api/tags" 2>/dev/null | grep -Eq '^(2|3)'; then
    printf 'ollama\n'
    return 0
  fi
  if curl -sS -o /dev/null -w '%{http_code}' "${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234}/v1/models" 2>/dev/null | grep -Eq '^(2|3)'; then
    printf 'lmstudio\n'
    return 0
  fi
  if curl -sS -o /dev/null -w '%{http_code}' "${TEXTGENWEBUI_BASE_URL:-http://127.0.0.1:5000}/v1/models" 2>/dev/null | grep -Eq '^(2|3)'; then
    printf 'textgenwebui\n'
    return 0
  fi
  return 1
}

detect_ollama_model() {
  local base_url="${1:-${OLLAMA_BASE_URL:-http://127.0.0.1:11434}}"
  local py_bin="${PYTHON_BIN:-}"
  local tags_json

  tags_json="$(curl -fsS "${base_url}/api/tags" 2>/dev/null || true)"
  [[ -n "${tags_json}" ]] || return 1

  if [[ -z "${py_bin}" ]]; then
    py_bin="$(resolve_python_bin || true)"
  fi
  if [[ -z "${py_bin}" ]]; then
    py_bin="$(command -v python3 || command -v python || true)"
  fi

  if [[ -n "${py_bin}" ]]; then
    TAGS_JSON="${tags_json}" "${py_bin}" - <<'PY'
import json
import os

raw = os.environ.get("TAGS_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    raise SystemExit(1)

models = payload.get("models") or []
for item in models:
    name = item.get("name") or item.get("model")
    if name:
        print(name)
        raise SystemExit(0)

raise SystemExit(1)
PY
    return $?
  fi

  printf '%s\n' "${tags_json}" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p' | head -n 1
}

list_ollama_models() {
  local base_url="${1:-${OLLAMA_BASE_URL:-http://127.0.0.1:11434}}"
  local py_bin="${PYTHON_BIN:-}"
  local tags_json

  tags_json="$(curl -fsS "${base_url}/api/tags" 2>/dev/null || true)"
  [[ -n "${tags_json}" ]] || return 1

  if [[ -z "${py_bin}" ]]; then
    py_bin="$(resolve_python_bin || true)"
  fi
  if [[ -z "${py_bin}" ]]; then
    py_bin="$(command -v python3 || command -v python || true)"
  fi

  if [[ -n "${py_bin}" ]]; then
    TAGS_JSON="${tags_json}" "${py_bin}" - <<'PY'
import json
import os

raw = os.environ.get("TAGS_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    raise SystemExit(1)

models = payload.get("models") or []
names = []
for item in models:
    name = item.get("name") or item.get("model")
    if name:
        names.append(name)

if not names:
    raise SystemExit(1)

print("\n".join(names))
PY
    return $?
  fi

  printf '%s\n' "${tags_json}" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p'
}

has_cloud_llm_key() {
  local keys=(
    OPENAI_API_KEY
    ANTHROPIC_API_KEY
    DEEPSEEK_API_KEY
    OPENROUTER_API_KEY
    GEMINI_API_KEY
    GROQ_API_KEY
  )
  local key

  for key in "${keys[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      return 0
    fi
  done
  return 1
}

configure_local_ollama_env() {
  local env_file="${1:-}"
  local provider
  local models
  local first_model

  has_cloud_llm_key && return 1
  command -v ollama >/dev/null 2>&1 || return 1

  provider="$(detect_local_llm_provider || true)"
  [[ "${provider}" == "ollama" ]] || return 1

  models="$(list_ollama_models || true)"
  [[ -n "${models}" ]] || return 1

  first_model="$(printf '%s\n' "${models}" | head -n 1)"
  [[ -n "${first_model}" ]] || return 1

  export LLM_PROVIDER="ollama"
  export LLM_MODEL="${first_model}"

  if [[ -n "${env_file}" ]]; then
    set_env_value "${env_file}" "LLM_PROVIDER" "ollama"
    set_env_value "${env_file}" "LLM_MODEL" "${first_model}"
  fi

  printf '%s\n' "${models}"
}

has_compose() {
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  command -v docker-compose >/dev/null 2>&1
}

compose_name() {
  if docker compose version >/dev/null 2>&1; then
    printf '%s\n' "docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    printf '%s\n' "docker-compose"
    return 0
  fi
  return 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
    return
  fi
  fail "Missing Docker Compose. Install the 'docker compose' plugin or the legacy 'docker-compose' binary."
}
