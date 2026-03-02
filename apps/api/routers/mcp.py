"""MCP (Model Context Protocol) endpoint.

Provides JSON-RPC endpoint for MCP clients to discover and invoke
OpenTutor's education tools.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("/")
async def mcp_endpoint(request: Request):
    """Handle MCP JSON-RPC requests."""
    from services.mcp.server import handle_mcp_request

    body = await request.json()
    result = await handle_mcp_request(body)

    if result is None:
        return JSONResponse(content={}, status_code=204)

    return JSONResponse(content=result)
