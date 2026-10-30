"""Tests for LLM usage tracking and cost estimation."""

import pytest


def test_estimate_cost_openai_gpt4o_mini():
    from services.llm.usage import estimate_cost

    # gpt-4o-mini: $0.15/M input, $0.60/M output
    cost = estimate_cost("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
    assert abs(cost - expected) < 1e-6


def test_estimate_cost_openai_gpt4o():
    from services.llm.usage import estimate_cost

    # gpt-4o: $2.50/M input, $10.00/M output
    cost = estimate_cost("gpt-4o", input_tokens=10000, output_tokens=2000)
    expected = (10000 * 2.50 + 2000 * 10.00) / 1_000_000
    assert abs(cost - expected) < 1e-6


def test_estimate_cost_anthropic_sonnet():
    from services.llm.usage import estimate_cost

    # claude-sonnet-4: $3.00/M input, $15.00/M output
    cost = estimate_cost("claude-sonnet-4-20250514", input_tokens=5000, output_tokens=1000)
    expected = (5000 * 3.00 + 1000 * 15.00) / 1_000_000
    assert abs(cost - expected) < 1e-6


def test_estimate_cost_deepseek():
    from services.llm.usage import estimate_cost

    # deepseek-chat: $0.14/M input, $0.28/M output
    cost = estimate_cost("deepseek-chat", input_tokens=10000, output_tokens=5000)
    expected = (10000 * 0.14 + 5000 * 0.28) / 1_000_000
    assert abs(cost - expected) < 1e-6


def test_estimate_cost_local_model_is_free():
    from services.llm.usage import estimate_cost

    # Ollama / local models should be $0
    cost = estimate_cost("qwen2.5", input_tokens=50000, output_tokens=10000)
    assert cost == 0.0

    # Groq-hosted llama-3.3-70b has paid pricing
    cost = estimate_cost("llama-3.3-70b-versatile", input_tokens=1000, output_tokens=500)
    assert cost > 0.0  # Groq pricing, not free

    # Generic local llama (Ollama) is free
    cost = estimate_cost("llama3.2:latest", input_tokens=1000, output_tokens=500)
    assert cost == 0.0


def test_estimate_cost_unknown_model_uses_default():
    from services.llm.usage import estimate_cost, DEFAULT_PRICING

    cost = estimate_cost("totally-unknown-model-xyz", input_tokens=1000, output_tokens=1000)
    expected = (1000 * DEFAULT_PRICING[0] + 1000 * DEFAULT_PRICING[1]) / 1_000_000
    assert abs(cost - expected) < 1e-6


def test_estimate_cost_zero_tokens():
    from services.llm.usage import estimate_cost

    cost = estimate_cost("gpt-4o", input_tokens=0, output_tokens=0)
    assert cost == 0.0


def test_specificity_gpt4o_mini_before_gpt4o():
    from services.llm.usage import estimate_cost

    # "gpt-4o-mini" should match the mini pricing, not the gpt-4o pricing
    mini_cost = estimate_cost("gpt-4o-mini", input_tokens=1_000_000, output_tokens=0)
    full_cost = estimate_cost("gpt-4o", input_tokens=1_000_000, output_tokens=0)
    assert mini_cost < full_cost


# ── Client-level usage hook ──


class _HookClient:
    """Minimal LLMClient subclass exercising the _last_usage setter."""

    def __init__(self):
        from services.llm.base_client import LLMClient

        class _Impl(LLMClient):
            provider_name = "openai"
            model = "gpt-4o-mini"

            async def stream_chat(self, *a, **k):  # pragma: no cover - unused
                yield ""

            async def chat(self, *a, **k):  # pragma: no cover - unused
                return "", {}

            async def extract(self, *a, **k):  # pragma: no cover - unused
                return "", {}

        self.client = _Impl()


def test_usage_hook_receives_each_recorded_usage():
    from services.llm.base_client import set_usage_hook

    seen: list[tuple[str, str, dict]] = []
    set_usage_hook(lambda p, m, u: seen.append((p, m, u)))
    try:
        client = _HookClient().client
        client._last_usage = {"input_tokens": 7, "output_tokens": 3}
        client._last_usage = {"input_tokens": 1, "output_tokens": 1}
        client._last_usage = {}
    finally:
        set_usage_hook(None)

    assert seen == [
        ("openai", "gpt-4o-mini", {"input_tokens": 7, "output_tokens": 3}),
        ("openai", "gpt-4o-mini", {"input_tokens": 1, "output_tokens": 1}),
    ]
    assert client.get_last_usage() == {}


def test_usage_hook_errors_never_propagate():
    from services.llm.base_client import set_usage_hook

    def _boom(*_a):
        raise RuntimeError("hook failure")

    set_usage_hook(_boom)
    try:
        client = _HookClient().client
        client._last_usage = {"input_tokens": 2, "output_tokens": 2}
    finally:
        set_usage_hook(None)

    assert client.get_last_usage() == {"input_tokens": 2, "output_tokens": 2}


@pytest.mark.asyncio
async def test_on_usage_writes_event_with_attribution(monkeypatch):
    import asyncio
    import uuid

    from services.llm import usage as usage_module

    recorded: list[dict] = []

    async def _fake_record_usage(_db, **kwargs):
        recorded.append(kwargs)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(usage_module, "record_usage", _fake_record_usage)
    monkeypatch.setattr("database.async_session", lambda: _Session())

    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    with usage_module.usage_attribution(user_id=user_id, course_id=course_id, scene="study_session"):
        usage_module.update_usage_attribution(agent_name="tutor", metadata={"intent": "learn"})
        usage_module.on_usage("openai", "gpt-4o-mini", {"input_tokens": 10, "output_tokens": 5})
        # Local models are free and skipped
        usage_module.on_usage("ollama", "llama3.2:3b", {"input_tokens": 10, "output_tokens": 5})

    # Outside of attribution nothing is recorded
    usage_module.on_usage("openai", "gpt-4o-mini", {"input_tokens": 10, "output_tokens": 5})

    from services.agent.background_runtime import wait_for_background_tasks

    await wait_for_background_tasks()
    await asyncio.sleep(0)

    assert len(recorded) == 1
    event = recorded[0]
    assert event["user_id"] == user_id
    assert event["course_id"] == course_id
    assert event["agent_name"] == "tutor"
    assert event["scene"] == "study_session"
    assert event["model_provider"] == "openai"
    assert event["model_name"] == "gpt-4o-mini"
    assert event["input_tokens"] == 10
    assert event["output_tokens"] == 5
    assert event["metadata"] == {"intent": "learn"}
