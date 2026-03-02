#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_BASE="${API_BASE:-http://127.0.0.1:8004}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"

OPENAI_KEY="${OPENAI_API_KEY:-}"
ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"
DEEPSEEK_KEY="${DEEPSEEK_API_KEY:-}"
OPENROUTER_KEY="${OPENROUTER_API_KEY:-}"
GEMINI_KEY="${GEMINI_API_KEY:-}"
GROQ_KEY="${GROQ_API_KEY:-}"
REAL_LLM_PROVIDER="${REAL_LLM_PROVIDER:-${LLM_PROVIDER:-}}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234}"
TEXTGENWEBUI_BASE_URL="${TEXTGENWEBUI_BASE_URL:-http://127.0.0.1:5000}"
REAL_LLM_MODEL="${REAL_LLM_MODEL:-${LLM_MODEL:-}}"

TMP_DIR="$(create_temp_dir)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "== Real LLM Integration Test =="
echo "API_BASE=${API_BASE}"

PROVIDER=""
MODEL=""
PAYLOAD=""

if [[ -n "${OPENAI_KEY}" ]]; then
  PROVIDER="openai"
  MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL" "$OPENAI_KEY"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True, "provider_keys": {sys.argv[1]: sys.argv[3]}}))
PY
)"
elif [[ -n "${ANTHROPIC_KEY}" ]]; then
  PROVIDER="anthropic"
  MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL" "$ANTHROPIC_KEY"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True, "provider_keys": {sys.argv[1]: sys.argv[3]}}))
PY
)"
elif [[ -n "${DEEPSEEK_KEY}" ]]; then
  PROVIDER="deepseek"
  MODEL="${DEEPSEEK_MODEL:-deepseek-chat}"
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL" "$DEEPSEEK_KEY"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True, "provider_keys": {sys.argv[1]: sys.argv[3]}}))
PY
)"
elif [[ -n "${OPENROUTER_KEY}" ]]; then
  PROVIDER="openrouter"
  MODEL="${OPENROUTER_MODEL:-openai/gpt-4o-mini}"
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL" "$OPENROUTER_KEY"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True, "provider_keys": {sys.argv[1]: sys.argv[3]}}))
PY
)"
elif [[ -n "${GEMINI_KEY}" ]]; then
  PROVIDER="gemini"
  MODEL="${GEMINI_MODEL:-gemini-2.0-flash}"
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL" "$GEMINI_KEY"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True, "provider_keys": {sys.argv[1]: sys.argv[3]}}))
PY
)"
elif [[ -n "${GROQ_KEY}" ]]; then
  PROVIDER="groq"
  MODEL="${GROQ_MODEL:-llama-3.3-70b-versatile}"
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL" "$GROQ_KEY"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True, "provider_keys": {sys.argv[1]: sys.argv[3]}}))
PY
)"
else
  PROVIDER="${REAL_LLM_PROVIDER:-$(detect_local_llm_provider || true)}"
  case "${PROVIDER}" in
    ollama)
      MODEL="${REAL_LLM_MODEL:-${OLLAMA_MODEL:-$(detect_ollama_model || true)}}"
      MODEL="${MODEL:-llama3.2:1b}"
      ;;
    lmstudio)
      MODEL="${REAL_LLM_MODEL:-${LMSTUDIO_MODEL:-default}}"
      ;;
    textgenwebui)
      MODEL="${REAL_LLM_MODEL:-${TEXTGENWEBUI_MODEL:-default}}"
      ;;
    *)
      echo "FAIL: No real LLM provider configured."
      echo "Set a cloud API key, or run a local backend and export REAL_LLM_PROVIDER=ollama|lmstudio|textgenwebui."
      exit 2
      ;;
  esac
  PAYLOAD="$(python3 - <<'PY' "$PROVIDER" "$MODEL"
import json, sys
print(json.dumps({"provider": sys.argv[1], "model": sys.argv[2], "llm_required": True}))
PY
)"
fi

status="$(curl -sS -o "$TMP_DIR/runtime.json" -w "%{http_code}" \
  -X PUT "${API_BASE}/api/preferences/runtime/llm" \
  -H "Content-Type: application/json" \
  --data "$PAYLOAD")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: runtime configuration failed (HTTP $status)"
  cat "$TMP_DIR/runtime.json" || true
  exit 1
fi
echo "PASS: configured real provider ${PROVIDER} (${MODEL})"

# Health check
status="$(curl -sS -o "$TMP_DIR/health.json" -w "%{http_code}" "${API_BASE}/api/health")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: health check failed (HTTP $status)"
  cat "$TMP_DIR/health.json" || true
  exit 1
fi
echo "PASS: health"

# Create a fresh course
course_name="LLM Integration $(date +%Y%m%d-%H%M%S)"
payload="{\"name\":\"${course_name}\",\"description\":\"real llm integration\"}"
status="$(curl -sS -o "$TMP_DIR/course.json" -w "%{http_code}" \
  -X POST "${API_BASE}/api/courses/" \
  -H "Content-Type: application/json" \
  --data "$payload")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: create course failed (HTTP $status)"
  cat "$TMP_DIR/course.json" || true
  exit 1
fi

course_id="$(python3 - <<'PY' "$TMP_DIR/course.json"
import json, sys
with open(sys.argv[1]) as f:
    print(json.load(f)["id"])
PY
)"
echo "PASS: created course ${course_id}"

# Real chat stream call (SSE)
chat_payload="{\"course_id\":\"${course_id}\",\"message\":\"Give me a concise summary of this course in 2 bullet points.\"}"
status="$(curl -sS -o "$TMP_DIR/chat.txt" -w "%{http_code}" \
  -X POST "${API_BASE}/api/chat/" \
  -H "Content-Type: application/json" \
  --data "$chat_payload" \
  --max-time "${TIMEOUT_SECONDS}")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: chat stream failed (HTTP $status)"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

if grep -Eq "No LLM API key configured|local fallback response" "$TMP_DIR/chat.txt"; then
  echo "FAIL: chat used mock fallback instead of real provider"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

if ! grep -Eq "event: message|event: done" "$TMP_DIR/chat.txt"; then
  echo "FAIL: chat stream did not contain expected SSE events"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi
echo "PASS: real chat stream"

# Real workflow call
status="$(curl -sS -o "$TMP_DIR/weekly.json" -w "%{http_code}" \
  "${API_BASE}/api/workflows/weekly-prep" \
  --max-time "${TIMEOUT_SECONDS}")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: weekly-prep failed (HTTP $status)"
  cat "$TMP_DIR/weekly.json" || true
  exit 1
fi

if grep -Eq "No LLM API key configured|local fallback response" "$TMP_DIR/weekly.json"; then
  echo "FAIL: weekly-prep used mock fallback instead of real provider"
  cat "$TMP_DIR/weekly.json" || true
  exit 1
fi
echo "PASS: real weekly-prep workflow"

echo "PASS: Real LLM integration checks completed"
