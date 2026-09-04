"""Tests for user-friendly LLM failure diagnostics (issue #23)."""

import pytest

from services.llm.circuit_breaker import CircuitBreakerMixin
from services.llm.errors import classify_llm_error, describe_llm_error


# ── Classification ──

@pytest.mark.parametrize("error,expected", [
    ("ConnectError: [Errno 111] Connection refused", "connection_refused"),
    ("[WinError 10061] No connection could be made", "connection_refused"),
    ("all connection attempts failed", "connection_refused"),
    ("Cannot connect to host localhost:11434", "connection_refused"),
    ("ReadTimeout: timed out", "timeout"),
    ("APITimeoutError: Request timeout", "timeout"),
    ("Error code: 401 - Incorrect API key provided", "auth"),
    ("AuthenticationError: invalid x-api-key", "auth"),
    ("Error code: 403 Forbidden", "auth"),
    ("model 'llama9:999b' not found, try pulling it first", "model_not_found"),
    ("NotFoundError: The model `gpt-9` does not exist or you do not have access to it", "model_not_found"),
    ("Error code: 404 - unknown model", "model_not_found"),
    ("Error code: 429 - Rate limit reached", "rate_limit"),
    ("insufficient_quota: You exceeded your current quota", "rate_limit"),
    ("getaddrinfo failed", "dns"),
    ("Name or service not known", "dns"),
    ("something inexplicable", "unknown"),
])
def test_classification(error, expected):
    assert classify_llm_error(error) == expected


def test_classification_accepts_exceptions():
    assert classify_llm_error(ConnectionRefusedError(111, "Connection refused")) == "connection_refused"
    assert classify_llm_error(TimeoutError("timed out")) == "timeout"


# ── Message content: provider, endpoint, and actionable hint ──

def test_connection_refused_names_provider_url_and_start_hint():
    msg = describe_llm_error(
        "Connection refused",
        provider="ollama", base_url="http://localhost:11434", model="llama3.2:3b",
    )
    assert "ollama" in msg
    assert "http://localhost:11434" in msg
    assert "ollama serve" in msg
    assert "Connection refused" in msg  # Raw error preserved for debugging


def test_timeout_suggests_model_size_or_load():
    msg = describe_llm_error("timed out", provider="vllm", base_url="http://gpu:8000/v1", model="qwen-72b")
    assert "qwen-72b" in msg and "http://gpu:8000/v1" in msg
    assert "smaller model" in msg or "overloaded" in msg


def test_auth_names_the_key_env_var():
    msg = describe_llm_error("Error code: 401 - Incorrect API key", provider="openai")
    assert "OPENAI_API_KEY" in msg


def test_model_not_found_suggests_ollama_pull():
    msg = describe_llm_error(
        "model 'mistral' not found, try pulling it first",
        provider="ollama", base_url="http://localhost:11434", model="mistral",
    )
    assert "ollama pull mistral" in msg


def test_model_not_found_cloud_suggests_settings_check():
    msg = describe_llm_error(
        "NotFoundError: The model `gpt-9` does not exist or you do not have access to it",
        provider="openai", model="gpt-9",
    )
    assert "gpt-9" in msg and "model name" in msg


def test_unknown_error_still_names_provider_and_keeps_raw():
    msg = describe_llm_error("kaboom", provider="groq", base_url="https://api.groq.com")
    assert "groq" in msg and "kaboom" in msg


# ── Circuit breaker integration ──

class _FakeClient(CircuitBreakerMixin):
    provider_name = "ollama"

    def __init__(self):
        super().__init__()
        self.base_url = "http://localhost:11434"
        self.model = "llama3.2:3b"


def test_mark_unhealthy_records_diagnostic():
    client = _FakeClient()
    assert client.last_error_detail is None
    client.mark_unhealthy("Connection refused")
    assert client.last_error_detail is not None
    assert "ollama" in client.last_error_detail
    assert "http://localhost:11434" in client.last_error_detail


def test_mark_healthy_keeps_last_diagnostic_for_postmortem():
    client = _FakeClient()
    client.mark_unhealthy("timed out")
    client.mark_healthy()
    assert client.is_healthy
    assert "timed out" in client.last_error_detail


# ── Router aggregation ──

def test_router_unhealthy_error_includes_per_provider_reasons():
    from services.llm.router import ProviderRegistry

    registry = ProviderRegistry()
    client = _FakeClient()
    registry.register("ollama", client, primary=True)
    # Trip the breaker fully so is_healthy stays False
    for _ in range(5):
        client.mark_unhealthy("Connection refused")

    with pytest.raises(RuntimeError) as exc:
        registry.get()
    msg = str(exc.value)
    assert "All LLM providers are unhealthy" in msg
    assert "ollama serve" in msg  # The actionable diagnostic surfaced
