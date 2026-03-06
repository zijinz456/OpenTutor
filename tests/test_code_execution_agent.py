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


def test_code_execution_blocks_file_network_and_infinite_loop_patterns():
    agent = CodeExecutionAgent()

    assert agent._validate_code("import socket\nprint('x')")[0] is False
    assert agent._validate_code("open('tmp.txt', 'w')")[0] is False
    assert agent._validate_code("while True:\n    pass")[0] is False


