"""Code sandbox policy regressions."""

from services.agent.code_execution import (
    CodeExecutionAgent,
    pop_sandbox_backend_override,
    push_sandbox_backend_override,
    sandbox_runtime_available,
)


def test_auto_backend_fails_closed_when_container_unavailable_and_process_fallback_disabled(monkeypatch):
    agent = CodeExecutionAgent()
    token = push_sandbox_backend_override("auto")
    monkeypatch.setattr("services.agent.code_execution.process_sandbox_allowed", lambda: False)
    try:
        result = agent._execute_safe("print(1)")
    finally:
        pop_sandbox_backend_override(token)

    assert result["success"] is False
    assert result["backend"] == "container"
    assert "unavailable" in result["error"].lower()


def test_auto_backend_uses_process_fallback_only_when_explicitly_allowed(monkeypatch):
    agent = CodeExecutionAgent()
    token = push_sandbox_backend_override("auto")
    monkeypatch.setattr("services.agent.code_execution.process_sandbox_allowed", lambda: True)
    try:
        result = agent._execute_safe("print(6)")
    finally:
        pop_sandbox_backend_override(token)

    assert result["success"] is True
    assert result["output"].strip() == "6"
    assert result["backend"] == "process"


def test_sandbox_runtime_available_reflects_policy_and_runtime(monkeypatch):
    token = push_sandbox_backend_override("auto")
    monkeypatch.setattr("services.agent.code_execution._container_runtime_available", lambda: False)
    try:
        monkeypatch.setattr("services.agent.code_execution.process_sandbox_allowed", lambda: False)
        assert sandbox_runtime_available() is False

        monkeypatch.setattr("services.agent.code_execution.process_sandbox_allowed", lambda: True)
        assert sandbox_runtime_available() is True
    finally:
        pop_sandbox_backend_override(token)
