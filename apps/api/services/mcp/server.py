"""MCP Server — exposes OpenTutor tools via Model Context Protocol.

Provides a JSON-RPC endpoint compatible with MCP clients (Claude Desktop, etc.)
that allows external AI agents to use OpenTutor's education tools.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# MCP protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"


def _list_tools() -> list[dict]:
    """Convert registered tools to MCP tool format."""
    from services.agent.tools.base import get_tool_registry

    registry = get_tool_registry()
    mcp_tools = []

    for tool in registry.get_all():
        schema = tool.to_openai_schema()
        func = schema.get("function", {})
        mcp_tools.append({
            "name": func.get("name", tool.name),
            "description": func.get("description", tool.description),
            "inputSchema": func.get("parameters", {"type": "object", "properties": {}}),
        })

    return mcp_tools


async def handle_mcp_request(request_body: dict) -> dict | None:
    """Handle a single MCP JSON-RPC request.

    Supports:
    - initialize
    - tools/list
    - tools/call
    """
    method = request_body.get("method", "")
    req_id = request_body.get("id")
    params = request_body.get("params", {})

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "opentutor-mcp",
                        "version": "1.0.0",
                    },
                },
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": _list_tools(),
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            from services.agent.tools.base import get_tool_registry
            registry = get_tool_registry()

            # Execute tool (no agent context in MCP mode)
            result = await registry.execute(tool_name, arguments, ctx=None, db=None)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": result.output if result.success else (result.error or "Unknown error"),
                        },
                    ],
                    "isError": not result.success,
                },
            }

        elif method == "notifications/initialized":
            # Client acknowledgment - no response needed
            return None

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

    except Exception as e:
        logger.error("MCP request failed: %s", e, exc_info=True)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32603,
                "message": str(e),
            },
        }
