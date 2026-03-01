from services.agent.code_execution import CodeExecutionAgent


def test_code_execution_uses_subprocess_sandbox_for_basic_code():
    agent = CodeExecutionAgent()

    result = agent._execute_safe("print(sum([1, 2, 3]))")

    assert result["success"] is True
    assert result["output"].strip() == "6"


def test_code_execution_blocks_dangerous_imports_before_execution():
    agent = CodeExecutionAgent()

    safe, reason = agent._validate_code("import os\nprint('x')")

    assert safe is False
    assert "not allowed" in reason
