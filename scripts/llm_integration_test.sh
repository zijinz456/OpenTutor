#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_BASE="${API_BASE:-http://127.0.0.1:8004}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-90}"
CONTENT_READY_TIMEOUT="${CONTENT_READY_TIMEOUT:-60}"
UPLOAD_FILE="${UPLOAD_FILE:-${ROOT_DIR}/tests/e2e/fixtures/sample-course.md}"
LLM_SMOKE_REPORT="${LLM_SMOKE_REPORT:-}"

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

json_file_get() {
  local file_path="$1"
  local path_expr="$2"
  python3 - <<'PY' "$file_path" "$path_expr"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expr = sys.argv[2]
data = json.loads(path.read_text(encoding="utf-8"))
value = data
for part in expr.split("."):
    if not part:
        continue
    if isinstance(value, dict):
        value = value.get(part)
    elif isinstance(value, list):
        try:
            value = value[int(part)]
        except Exception:
            value = None
            break
    else:
        value = None
        break
if value is None:
    print("")
elif isinstance(value, (dict, list)):
    print(json.dumps(value))
else:
    print(value)
PY
}

extract_first_content_node() {
  local file_path="$1"
  python3 - <<'PY' "$file_path"
import json
import sys
from pathlib import Path

nodes = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

def walk(items):
    for item in items or []:
        if isinstance(item, dict):
            content = str(item.get("content") or "").strip()
            if content:
                print(f"{item.get('id','')}|{item.get('title','')}")
                return True
            if walk(item.get("children") or []):
                return True
    return False

walk(nodes if isinstance(nodes, list) else [])
PY
}

build_report() {
  local output_path="$1"
  python3 - <<'PY' "$output_path" \
    "${PROVIDER}" "${MODEL}" "${course_id}" "${UPLOAD_FILE}" \
    "${upload_nodes_created:-0}" "${content_node_id:-}" "${content_node_title:-}" \
    "${chat_ttft:-0}" "${chat_total:-0}" "${chat_warning_count:-0}" "${chat_response_preview:-}" "${chat_has_sorted_signal:-false}" \
    "${notes_total:-0}" "${notes_length:-0}" "${notes_format:-}" "${notes_has_topic_signal:-false}" \
    "${quiz_total:-0}" "${quiz_created:-0}" "${quiz_validated:-0}" "${quiz_repaired:-0}" "${quiz_discarded:-0}" "${quiz_warning_count:-0}" "${quiz_failure_count:-0}" "${quiz_repair_rate:-0}"
import json
import sys
from pathlib import Path

(
    output_path,
    provider,
    model,
    course_id,
    upload_file,
    upload_nodes_created,
    content_node_id,
    content_node_title,
    chat_ttft,
    chat_total,
    chat_warning_count,
    chat_response_preview,
    chat_has_sorted_signal,
    notes_total,
    notes_length,
    notes_format,
    notes_has_topic_signal,
    quiz_total,
    quiz_created,
    quiz_validated,
    quiz_repaired,
    quiz_discarded,
    quiz_warning_count,
    quiz_failure_count,
    quiz_repair_rate,
) = sys.argv[1:]

report = {
    "provider": provider,
    "model": model,
    "course_id": course_id,
    "upload": {
        "fixture": upload_file,
        "nodes_created": int(float(upload_nodes_created or 0)),
        "content_node_id": content_node_id or None,
        "content_node_title": content_node_title or None,
    },
    "chat": {
        "time_to_first_token_s": round(float(chat_ttft or 0), 3),
        "total_latency_s": round(float(chat_total or 0), 3),
        "warning_count": int(float(chat_warning_count or 0)),
        "has_expected_signal": str(chat_has_sorted_signal).lower() == "true",
        "response_preview": chat_response_preview,
    },
    "notes": {
        "latency_s": round(float(notes_total or 0), 3),
        "length": int(float(notes_length or 0)),
        "format_used": notes_format or None,
        "has_expected_signal": str(notes_has_topic_signal).lower() == "true",
    },
    "quiz_extract": {
        "latency_s": round(float(quiz_total or 0), 3),
        "problems_created": int(float(quiz_created or 0)),
        "validated_count": int(float(quiz_validated or 0)),
        "repaired_count": int(float(quiz_repaired or 0)),
        "discarded_count": int(float(quiz_discarded or 0)),
        "warning_count": int(float(quiz_warning_count or 0)),
        "node_failure_count": int(float(quiz_failure_count or 0)),
        "repair_rate": round(float(quiz_repair_rate or 0), 3),
    },
}
Path(output_path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(output_path)
PY
}

stream_chat_metrics() {
  local raw_output_path="$1"
  local metrics_output_path="$2"
  local message="$3"
  python3 - <<'PY' "${API_BASE}" "${course_id}" "${message}" "${TIMEOUT_SECONDS}" "${raw_output_path}" "${metrics_output_path}"
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

api_base, course_id, message, timeout_s, raw_output_path, metrics_output_path = sys.argv[1:]
payload = json.dumps({
    "course_id": course_id,
    "message": message,
}).encode("utf-8")
request = urllib.request.Request(
    f"{api_base}/api/chat/",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

warning_count = 0
response_text = ""
error_message = ""
status = 0
first_token_at = None
started_at = time.perf_counter()
current_event = "message"
data_lines: list[str] = []
raw_chunks: list[str] = []


def process_event(event_name: str, lines: list[str], current_response: str):
    global warning_count, first_token_at, error_message
    if not lines:
        return current_response
    payload_raw = "\n".join(lines)
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return current_response
    if event_name == "warning":
        warning_count += 1
        return current_response
    if event_name == "error":
        if isinstance(payload, dict):
            error_message = str(payload.get("error") or payload)
        else:
            error_message = str(payload)
        return current_response
    if event_name == "message" and isinstance(payload, dict) and payload.get("content"):
        if first_token_at is None:
            first_token_at = time.perf_counter() - started_at
        return current_response + str(payload["content"])
    if event_name == "replace" and isinstance(payload, dict) and payload.get("content"):
        if first_token_at is None:
            first_token_at = time.perf_counter() - started_at
        return str(payload["content"])
    return current_response


try:
    with urllib.request.urlopen(request, timeout=float(timeout_s)) as response:
        status = int(getattr(response, "status", 200) or 200)
        for raw_line in response:
            text_line = raw_line.decode("utf-8", errors="replace")
            raw_chunks.append(text_line)
            stripped = text_line.rstrip("\r\n")
            if stripped == "":
                response_text = process_event(current_event, data_lines, response_text)
                current_event = "message"
                data_lines = []
                continue
            if stripped.startswith("event:"):
                current_event = stripped.split(":", 1)[1].strip() or "message"
            elif stripped.startswith("data:"):
                data_lines.append(stripped.split(":", 1)[1].strip())
        response_text = process_event(current_event, data_lines, response_text)
except urllib.error.HTTPError as exc:
    status = int(exc.code or 500)
    body = exc.read().decode("utf-8", errors="replace")
    raw_chunks.append(body)
    error_message = body
except Exception as exc:  # pragma: no cover - runtime-only integration path
    status = 599
    error_message = str(exc)

total_s = time.perf_counter() - started_at
Path(raw_output_path).write_text("".join(raw_chunks), encoding="utf-8")
metrics = {
    "status": status,
    "time_to_first_token_s": round(first_token_at if first_token_at is not None else 0.0, 3),
    "total_latency_s": round(total_s, 3),
    "warning_count": warning_count,
    "response_preview": response_text.strip()[:240],
    "error": error_message[:500],
}
Path(metrics_output_path).write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(metrics_output_path)
PY
}

echo "== Real LLM Integration Test =="
echo "API_BASE=${API_BASE}"
echo "UPLOAD_FILE=${UPLOAD_FILE}"

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

if [[ ! -f "${UPLOAD_FILE}" ]]; then
  echo "FAIL: upload fixture not found: ${UPLOAD_FILE}"
  exit 1
fi

# Upload fixture content so real-provider checks are grounded in course material.
upload_status="$(curl -sS -o "$TMP_DIR/upload.json" -w "%{http_code}" \
  -X POST "${API_BASE}/api/content/upload" \
  -F "course_id=${course_id}" \
  -F "file=@${UPLOAD_FILE}")"
if [[ ! "$upload_status" =~ ^2 ]]; then
  echo "FAIL: upload failed (HTTP $upload_status)"
  cat "$TMP_DIR/upload.json" || true
  exit 1
fi
upload_nodes_created="$(json_file_get "$TMP_DIR/upload.json" "nodes_created")"
echo "PASS: uploaded fixture (${upload_nodes_created:-0} nodes created)"

content_node_id=""
content_node_title=""
for ((attempt=1; attempt<=CONTENT_READY_TIMEOUT; attempt++)); do
  tree_status="$(curl -sS -o "$TMP_DIR/content_tree.json" -w "%{http_code}" "${API_BASE}/api/courses/${course_id}/content-tree")"
  if [[ "$tree_status" =~ ^2 ]]; then
    node_info="$(extract_first_content_node "$TMP_DIR/content_tree.json" || true)"
    if [[ -n "$node_info" ]]; then
      content_node_id="${node_info%%|*}"
      content_node_title="${node_info#*|}"
      break
    fi
  fi
  sleep 1
done
if [[ -z "${content_node_id}" ]]; then
  echo "FAIL: content tree did not become ready within ${CONTENT_READY_TIMEOUT}s"
  cat "$TMP_DIR/content_tree.json" || true
  exit 1
fi
echo "PASS: content tree ready (${content_node_title})"

# Real chat stream call (SSE) with latency metrics and warning tracking.
stream_chat_metrics "$TMP_DIR/chat.txt" "$TMP_DIR/chat_metrics.json" "What prerequisite must hold before binary search works? Answer in one sentence." >/dev/null
chat_status="$(json_file_get "$TMP_DIR/chat_metrics.json" "status")"
chat_ttft="$(json_file_get "$TMP_DIR/chat_metrics.json" "time_to_first_token_s")"
chat_total="$(json_file_get "$TMP_DIR/chat_metrics.json" "total_latency_s")"
chat_warning_count="$(json_file_get "$TMP_DIR/chat_metrics.json" "warning_count")"
chat_response_preview="$(json_file_get "$TMP_DIR/chat_metrics.json" "response_preview")"
chat_error="$(json_file_get "$TMP_DIR/chat_metrics.json" "error")"
if [[ ! "$chat_status" =~ ^2 ]]; then
  echo "FAIL: chat stream failed (HTTP $chat_status)"
  if [[ -n "${chat_error}" ]]; then
    echo "${chat_error}"
  fi
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

if grep -Eq "No LLM API key configured|local fallback response" "$TMP_DIR/chat.txt"; then
  echo "FAIL: chat used mock fallback instead of real provider"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

if ! tr -d '\r' < "$TMP_DIR/chat.txt" | grep -Eq "^event: message$|^event: done$"; then
  echo "FAIL: chat stream did not contain expected SSE events"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

chat_has_sorted_signal="false"
if printf '%s' "$chat_response_preview" | grep -Eiq 'sorted|order'; then
  chat_has_sorted_signal="true"
fi
echo "PASS: real chat stream (ttft=${chat_ttft}s total=${chat_total}s warnings=${chat_warning_count})"

# Notes restructure check against a real content node.
notes_payload="{\"content_node_id\":\"${content_node_id}\"}"
read -r notes_status notes_total <<< "$(curl -sS -o "$TMP_DIR/notes.json" -w "%{http_code} %{time_total}" \
  -X POST "${API_BASE}/api/notes/restructure" \
  -H "Content-Type: application/json" \
  --data "$notes_payload" \
  --max-time "${TIMEOUT_SECONDS}")"
if [[ ! "$notes_status" =~ ^2 ]]; then
  echo "FAIL: notes restructuring failed (HTTP $notes_status)"
  cat "$TMP_DIR/notes.json" || true
  exit 1
fi
notes_length="$(python3 - <<'PY' "$TMP_DIR/notes.json"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
text = str(payload.get("ai_content") or "")
print(len(text.strip()))
PY
)"
notes_format="$(json_file_get "$TMP_DIR/notes.json" "format_used")"
notes_has_topic_signal="false"
if python3 - <<'PY' "$TMP_DIR/notes.json" >/dev/null
import json
import re
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
text = str(payload.get("ai_content") or "").lower()
if len(text.strip()) < 80:
    raise SystemExit(1)
if not re.search(r"binary|search|sorted", text):
    raise SystemExit(1)
PY
then
  notes_has_topic_signal="true"
fi
if [[ "${notes_has_topic_signal}" != "true" ]]; then
  echo "FAIL: notes output did not show expected topic grounding"
  cat "$TMP_DIR/notes.json" || true
  exit 1
fi
echo "PASS: notes restructuring (latency=${notes_total}s length=${notes_length})"

# Quiz extraction quality check.
quiz_payload="{\"course_id\":\"${course_id}\",\"content_node_id\":\"${content_node_id}\"}"
read -r quiz_status quiz_total <<< "$(curl -sS -o "$TMP_DIR/quiz.json" -w "%{http_code} %{time_total}" \
  -X POST "${API_BASE}/api/quiz/extract" \
  -H "Content-Type: application/json" \
  --data "$quiz_payload" \
  --max-time "${TIMEOUT_SECONDS}")"
if [[ ! "$quiz_status" =~ ^2 ]]; then
  echo "FAIL: quiz extraction failed (HTTP $quiz_status)"
  cat "$TMP_DIR/quiz.json" || true
  exit 1
fi

quiz_created="$(json_file_get "$TMP_DIR/quiz.json" "problems_created")"
quiz_validated="$(json_file_get "$TMP_DIR/quiz.json" "validated_count")"
quiz_repaired="$(json_file_get "$TMP_DIR/quiz.json" "repaired_count")"
quiz_discarded="$(json_file_get "$TMP_DIR/quiz.json" "discarded_count")"
quiz_warning_count="$(python3 - <<'PY' "$TMP_DIR/quiz.json"
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
warnings = payload.get("warnings") or []
print(len(warnings) if isinstance(warnings, list) else 0)
PY
)"
quiz_failure_count="$(python3 - <<'PY' "$TMP_DIR/quiz.json"
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
failures = payload.get("node_failures") or []
print(len(failures) if isinstance(failures, list) else 0)
PY
)"
quiz_repair_rate="$(python3 - <<'PY' "${quiz_validated:-0}" "${quiz_repaired:-0}"
import sys
validated = float(sys.argv[1] or 0)
repaired = float(sys.argv[2] or 0)
print(0 if validated <= 0 else repaired / validated)
PY
)"
if [[ "${quiz_validated:-0}" -lt 1 || "${quiz_created:-0}" -lt 1 ]]; then
  echo "FAIL: quiz extraction returned no usable questions"
  cat "$TMP_DIR/quiz.json" || true
  exit 1
fi
echo "PASS: quiz extraction (latency=${quiz_total}s created=${quiz_created} validated=${quiz_validated} repaired=${quiz_repaired} discarded=${quiz_discarded})"

report_path="${LLM_SMOKE_REPORT:-${TMP_DIR}/llm_quality_report.json}"
report_path="$(build_report "${report_path}")"
echo "REPORT: ${report_path}"
cat "${report_path}"

echo "PASS: Real LLM integration checks completed"
