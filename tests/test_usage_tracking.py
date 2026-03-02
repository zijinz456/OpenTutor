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
