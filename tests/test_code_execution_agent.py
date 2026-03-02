from services.agent.code_execution import CodeExecutionAgent


def test_code_execution_uses_subprocess_sandbox_for_basic_code():
    agent = CodeExecutionAgent()
    from services.agent.code_execution import pop_sandbox_backend_override, push_sandbox_backend_override

    token = push_sandbox_backend_override("process")
    try:
        result = agent._execute_safe("print(sum([1, 2, 3]))")
    finally:
        pop_sandbox_backend_override(token)

    assert result["success"] is True
    assert result["output"].strip() == "6"
    assert result["backend"] == "process"


def test_code_execution_blocks_dangerous_imports_before_execution():
    agent = CodeExecutionAgent()

    safe, reason = agent._validate_code("import os\nprint('x')")

    assert safe is False
    assert "not allowed" in reason


def test_code_execution_falls_back_when_container_runtime_missing(monkeypatch):
    agent = CodeExecutionAgent()

    monkeypatch.setattr("services.agent.container_sandbox.container_runtime_available", lambda: False)
    monkeypatch.setattr("services.agent.code_execution.settings.code_sandbox_backend", "auto")

    result = agent._execute_safe("print('hi')")

    assert result["success"] is True
    assert result["backend"] == "process"


def test_code_execution_reports_error_when_container_backend_required(monkeypatch):
    agent = CodeExecutionAgent()

    monkeypatch.setattr("services.agent.code_execution.settings.code_sandbox_backend", "container")
    monkeypatch.setattr("services.agent.container_sandbox.container_runtime_available", lambda: False)

    result = agent._execute_safe("print('hi')")

    assert result["success"] is False
    assert result["backend"] == "container"
    assert "not available" in result["error"]


def test_code_execution_auto_mode_stays_strict_without_dev_override(monkeypatch):
    agent = CodeExecutionAgent()

    monkeypatch.setattr("services.agent.code_execution.settings.code_sandbox_backend", "auto")
    monkeypatch.setattr("services.agent.container_sandbox.container_runtime_available", lambda: False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_PROCESS_SANDBOX", raising=False)

    result = agent._execute_safe("print('hi')")

    assert result["success"] is False
    assert result["backend"] == "container"
    assert "not available" in result["error"]


def test_code_execution_blocks_file_network_and_infinite_loop_patterns():
    agent = CodeExecutionAgent()

    assert agent._validate_code("import socket\nprint('x')")[0] is False
    assert agent._validate_code("open('tmp.txt', 'w')")[0] is False
    assert agent._validate_code("while True:\n    pass")[0] is False


def test_container_sandbox_command_includes_strict_isolation_flags():
    from pathlib import Path

    from services.agent.container_sandbox import _build_container_command

    command = _build_container_command(Path("/tmp/sandbox_runner.py"))

    assert "--read-only" in command
    assert "--network" in command and "none" in command
    assert "--memory" in command and "256m" in command
    assert "--memory-swap" in command and "256m" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "--tmpfs" in command
