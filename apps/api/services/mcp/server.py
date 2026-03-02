"""MCP Server — exposes OpenTutor tools via Model Context Protocol.

Two MCP servers run in parallel:

1. **FastApiMCP** (mounted in main.py) — auto-exposes all FastAPI routes as
   MCP tools via Streamable HTTP at ``/mcp``.

2. **edu_mcp** (this module) — curated high-level education tools via
   FastMCP.  Exposed as a sub-application at ``/mcp/education``.

Legacy JSON-RPC handler is kept for backward compatibility with clients
that use the ``POST /api/mcp/`` endpoint directly.
"""

import logging

logger = logging.getLogger(__name__)

# MCP protocol version (legacy endpoint)
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

    # Note: education MCP tools are NOT included here — they are served
    # via the dedicated /mcp/education endpoint.  Including them in this
    # legacy list would be misleading because tools/call only dispatches
    # through the main ToolRegistry.

    return mcp_tools


def _list_education_tools() -> list[dict]:
    """List tools from the education FastMCP server.

    Uses the public ``list_tools()`` method on the FastMCP instance
    (available since mcp SDK 1.0).  Falls back gracefully if the SDK
    version differs.
    """
    try:
        from services.mcp.education_server import edu_mcp

        tools = []
        # FastMCP exposes list_tools() as a public coroutine in some versions
        # and as a sync accessor in others.  Try the public API first.
        tool_list = None
        if hasattr(edu_mcp, "list_tools"):
            tool_list = edu_mcp.list_tools()
        elif hasattr(edu_mcp, "_tool_manager"):
            tool_list = edu_mcp._tool_manager.list_tools()

        if tool_list is None:
            return []

        for tool in tool_list:
            schema = {"type": "object", "properties": {}}
            if hasattr(tool, "parameters") and tool.parameters:
                try:
                    schema = tool.parameters.model_json_schema()
                except Exception:
                    pass
            tools.append({
                "name": f"edu_{tool.name}",
                "description": getattr(tool, "description", "") or "",
                "inputSchema": schema,
            })
        return tools
    except Exception as e:
        logger.debug("Could not list education MCP tools: %s", e)
        return []


async def handle_mcp_request(request_body: dict) -> dict | None:
    """Handle a single MCP JSON-RPC request (legacy endpoint).

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
                        "version": "2.0.0",
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


def mount_education_mcp(app) -> None:
    """Mount the education FastMCP server as a sub-application.

    This provides the curated education tools at ``/mcp/education``
    using the official MCP SDK's Streamable HTTP transport.
    """
    try:
        from services.mcp.education_server import edu_mcp

        # FastMCP provides a streamable HTTP app (mcp SDK >= 1.0)
        if hasattr(edu_mcp, "streamable_http_app"):
            mcp_app = edu_mcp.streamable_http_app()
        elif hasattr(edu_mcp, "http_app"):
            mcp_app = edu_mcp.http_app()
        else:
            logger.warning("Education MCP: no compatible HTTP app method found on FastMCP")
            return

        app.mount("/mcp/education", mcp_app)
        logger.info("Education MCP server mounted at /mcp/education")
    except Exception as exc:
        logger.warning("Education MCP server mount failed: %s", exc)
