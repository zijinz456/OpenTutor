"""MCP (Model Context Protocol) client for connecting to external tool servers.

Borrows from:
- MiroThinker: MCP-based tool management (400+ tools via MCP servers)
- Anthropic MCP spec: stdio and SSE transport protocols

Connects to MCP servers defined in config/mcp_servers.yaml, discovers their
tools, and wraps each as a Tool instance in the global ToolRegistry.

MCP servers can provide any type of tool — web search, file management,
database access, API integrations, etc. This is the most powerful extension
mechanism for technical users.

Transport protocols:
- stdio: Launch a subprocess, communicate via stdin/stdout JSON-RPC
- sse: Connect to an HTTP SSE endpoint for JSON-RPC

Usage:
    from services.agent.tools.mcp_client import load_mcp_tools
    await load_mcp_tools()  # call at startup
"""

import asyncio
import json
import logging
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolParameter, ToolResult, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "mcp_servers.yaml"

# Retry constants for MCP connection resilience
MCP_MAX_RETRIES = 3
MCP_BASE_BACKOFF_SECONDS = 1.0  # 1s, 2s, 4s exponential backoff


# ── MCP Tool Wrapper ──


class MCPTool(Tool):
    """Tool backed by an MCP server."""

    domain = "mcp"

    def __init__(self, name: str, description: str, parameters: list[ToolParameter], provider: "MCPProvider"):
        self.name = name
        self.description = description
        self._parameters = parameters
        self._provider = provider

    def get_parameters(self) -> list[ToolParameter]:
        return self._parameters

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        return await self._provider.call_tool(self.name, parameters)


# ── MCP Provider (transport abstraction) ──


class MCPProvider:
    """Manages connection to a single MCP server."""

    def __init__(self, name: str, config: dict):
        self.server_name = name
        self.config = config
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._timeout = config.get("timeout", 30)  # Configurable per-server
        self._tools: list[Tool] = []  # Cache discovered tools for reconnection

    async def connect(self) -> list[Tool]:
        """Connect to the MCP server and discover available tools."""
        transport = self.config.get("transport", "stdio")
        if transport == "stdio":
            tools = await self._connect_stdio()
            if tools:
                self._tools = tools
            return tools
        elif transport == "sse":
            logger.warning("MCP SSE transport not yet implemented for %s", self.server_name)
            return []
        else:
            logger.warning("Unknown MCP transport '%s' for %s", transport, self.server_name)
            return []

    async def connect_with_retry(self) -> list[Tool]:
        """Connect with exponential backoff retries.

        Attempts up to MCP_MAX_RETRIES connections. On each failure, waits
        with exponential backoff (1s, 2s, 4s) before retrying.

        Returns:
            List of discovered tools (empty if all retries exhausted).
        """
        last_error: Exception | None = None
        for attempt in range(MCP_MAX_RETRIES):
            try:
                tools = await self.connect()
                if tools:
                    if attempt > 0:
                        logger.info(
                            "MCP server '%s': connected on attempt %d/%d",
                            self.server_name, attempt + 1, MCP_MAX_RETRIES,
                        )
                    return tools
                # connect() returned [] — treat as retriable if not final attempt
                if attempt < MCP_MAX_RETRIES - 1:
                    backoff = MCP_BASE_BACKOFF_SECONDS * (2 ** attempt)
                    logger.info(
                        "MCP server '%s': no tools on attempt %d/%d, retrying in %.1fs",
                        self.server_name, attempt + 1, MCP_MAX_RETRIES, backoff,
                    )
                    await asyncio.sleep(backoff)
            except Exception as e:
                last_error = e
                if attempt < MCP_MAX_RETRIES - 1:
                    backoff = MCP_BASE_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        "MCP server '%s': attempt %d/%d failed (%s), retrying in %.1fs",
                        self.server_name, attempt + 1, MCP_MAX_RETRIES, e, backoff,
                    )
                    self.close()
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "MCP server '%s': all %d connection attempts exhausted: %s",
                        self.server_name, MCP_MAX_RETRIES, e,
                    )

        return []

    async def _try_reconnect(self) -> bool:
        """Attempt to reconnect a dropped MCP connection.

        Uses exponential backoff. Returns True if reconnection succeeded.
        """
        logger.info("MCP server '%s': connection dropped, attempting reconnection", self.server_name)
        self.close()
        tools = await self.connect_with_retry()
        if tools:
            self._tools = tools
            logger.info("MCP server '%s': reconnected successfully (%d tools)", self.server_name, len(tools))
            return True
        logger.warning("MCP server '%s': reconnection failed after %d attempts", self.server_name, MCP_MAX_RETRIES)
        return False

    @property
    def is_connected(self) -> bool:
        """Check whether the MCP subprocess is still alive."""
        return self._process is not None and self._process.poll() is None

    async def _connect_stdio(self) -> list[Tool]:
        """Connect via stdio subprocess."""
        command = self.config.get("command", "")
        args = self.config.get("args", [])

        if not command:
            logger.warning("MCP server %s: no command specified", self.server_name)
            return []

        # Resolve environment variables
        env = {**os.environ}
        for key, val in self.config.get("env", {}).items():
            if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
                env_var = val[2:-1]
                env[key] = os.getenv(env_var, "")
            else:
                env[key] = str(val)

        try:
            self._process = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            # Initialize MCP connection
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "opentutor", "version": "0.1.0"},
            })

            if not init_result:
                logger.warning("MCP server %s: initialization failed", self.server_name)
                self.close()
                return []

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            # List tools
            tools_result = await self._send_request("tools/list", {})
            if not tools_result or "tools" not in tools_result:
                logger.info("MCP server %s: no tools available", self.server_name)
                self.close()
                return []

            return self._parse_tools(tools_result["tools"])

        except FileNotFoundError:
            logger.warning("MCP server %s: command '%s' not found", self.server_name, command)
            return []
        except Exception as e:
            logger.warning("MCP server %s: connection failed: %s", self.server_name, e)
            self.close()
            return []

    def _parse_tools(self, raw_tools: list[dict]) -> list[Tool]:
        """Convert MCP tool definitions to Tool instances."""
        tools = []
        for t in raw_tools:
            name = t.get("name", "")
            if not name:
                continue

            params = []
            input_schema = t.get("inputSchema", {})
            properties = input_schema.get("properties", {})
            required = set(input_schema.get("required", []))

            for param_name, param_def in properties.items():
                params.append(ToolParameter(
                    name=param_name,
                    type=param_def.get("type", "string"),
                    description=param_def.get("description", ""),
                    required=param_name in required,
                    enum=param_def.get("enum"),
                    default=param_def.get("default"),
                ))

            tools.append(MCPTool(
                name=name,
                description=t.get("description", f"MCP tool: {name}"),
                parameters=params,
                provider=self,
            ))

        return tools

    async def call_tool(self, name: str, arguments: dict) -> ToolResult:
        """Execute a tool on the MCP server.

        If the server process has died, attempts reconnection with exponential
        backoff before returning a failure.
        """
        # If server is down, try to reconnect before giving up
        if not self.is_connected:
            reconnected = await self._try_reconnect()
            if not reconnected:
                return ToolResult(
                    success=False, output="",
                    error=f"MCP server '{self.server_name}' unavailable after reconnection attempts",
                )

        try:
            result = await self._send_request("tools/call", {
                "name": name,
                "arguments": arguments,
            })

            # Check if process died during the request — attempt reconnect + retry once
            if self._process and self._process.poll() is not None:
                logger.warning("MCP server '%s' crashed during tool execution, attempting reconnect", self.server_name)
                reconnected = await self._try_reconnect()
                if not reconnected:
                    return ToolResult(
                        success=False, output="",
                        error=f"MCP server '{self.server_name}' crashed during tool execution and reconnection failed",
                    )
                # Retry the tool call once after reconnect
                result = await self._send_request("tools/call", {
                    "name": name,
                    "arguments": arguments,
                })

            if result is None:
                return ToolResult(success=False, output="", error="No response from MCP server")

            # MCP returns content as array of content blocks
            content_parts = result.get("content", [])
            text_parts = []
            for part in content_parts:
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))

            is_error = result.get("isError", False)
            output = "\n".join(text_parts)

            return ToolResult(
                success=not is_error,
                output=output,
                error=output if is_error else None,
            )

        except Exception as e:
            logger.error("MCP tool %s call failed: %s", name, e)
            return ToolResult(success=False, output="", error=str(e))

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request and read the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            line = json.dumps(request) + "\n"
            # Wrap both write and read in to_thread to avoid blocking the event loop
            await asyncio.to_thread(self._write_stdin, line.encode())

            # Read response (with configurable timeout)
            response_line = await asyncio.wait_for(
                asyncio.to_thread(self._read_stdout_line),
                timeout=self._timeout,
            )

            if not response_line:
                return None

            response = json.loads(response_line.decode())
            if "error" in response:
                logger.warning("MCP %s error: %s", method, response["error"])
                return None

            return response.get("result")

        except asyncio.TimeoutError:
            logger.warning("MCP request %s timed out", method)
            return None
        except Exception as e:
            logger.warning("MCP request %s failed: %s", method, e)
            return None

    def _write_stdin(self, data: bytes) -> None:
        """Blocking write to subprocess stdin (called via to_thread)."""
        if self._process and self._process.stdin:
            self._process.stdin.write(data)
            self._process.stdin.flush()

    def _read_stdout_line(self) -> bytes:
        """Blocking readline from subprocess stdout (called via to_thread)."""
        if self._process and self._process.stdout:
            return self._process.stdout.readline()
        return b""

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            line = json.dumps(notification) + "\n"
            await asyncio.to_thread(self._write_stdin, line.encode())
        except Exception as e:
            logger.warning("MCP notification %s failed: %s", method, e)

    def close(self):
        """Terminate the MCP server subprocess and close pipes."""
        if self._process:
            try:
                # Close pipes first to signal EOF
                for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
                    if pipe:
                        try:
                            pipe.close()
                        except Exception:
                            pass
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


# ── Global MCP providers ──

_mcp_providers: list[MCPProvider] = []


async def _record_mcp_audit(
    server_name: str,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an MCP-related event to the audit log.

    Uses a short-lived session so audit writes don't interfere with the
    caller's transaction.  Failures are swallowed and logged — audit
    recording must never crash the startup path.
    """
    try:
        from database import async_session
        from services.audit import record_audit_log

        async with async_session() as db:
            await record_audit_log(
                db,
                actor_user_id=None,  # system-level event
                tool_name=server_name,
                action_kind="mcp_connection",
                outcome=outcome,
                details_json=details,
            )
            await db.commit()
    except Exception as e:
        # Never let audit failures break MCP loading
        logger.debug("Failed to write MCP audit log: %s", e)


async def load_mcp_tools(registry: ToolRegistry | None = None) -> int:
    """Load tools from all configured MCP servers.

    Uses exponential-backoff retries per server.  If a server is still
    unreachable after all retries, the failure is logged to the audit table
    and the system continues without those tools (graceful degradation).

    Args:
        registry: Target registry. If None, uses the global singleton.

    Returns:
        Number of tools registered from MCP servers.
    """
    if registry is None:
        registry = get_tool_registry()

    if yaml is None:
        logger.debug("pyyaml not installed, skipping MCP config")
        return 0

    if not _CONFIG_PATH.exists():
        logger.debug("No MCP config at %s, skipping", _CONFIG_PATH)
        return 0

    try:
        with open(_CONFIG_PATH) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.warning("Failed to read MCP config: %s", e)
        return 0

    servers = config.get("servers", [])
    if not servers:
        return 0

    count = 0
    failed_servers: list[str] = []

    for server_config in servers:
        name = server_config.get("name", "unknown")
        provider = MCPProvider(name, server_config)

        try:
            tools = await provider.connect_with_retry()
            if tools:
                for tool in tools:
                    registry.register(tool)
                    count += 1
                _mcp_providers.append(provider)
                logger.info("MCP server '%s': %d tools registered", name, len(tools))
                await _record_mcp_audit(name, "connected", {"tool_count": len(tools)})
            else:
                # All retries exhausted with no tools — graceful degradation
                failed_servers.append(name)
                provider.close()
                logger.warning(
                    "MCP server '%s': unavailable after %d retries, continuing without its tools",
                    name, MCP_MAX_RETRIES,
                )
                await _record_mcp_audit(name, "failed", {
                    "reason": "no_tools_after_retries",
                    "max_retries": MCP_MAX_RETRIES,
                })
        except Exception as e:
            failed_servers.append(name)
            provider.close()
            logger.warning("MCP server '%s' failed: %s", name, e)
            await _record_mcp_audit(name, "failed", {
                "reason": str(e),
                "traceback": traceback.format_exc(),
                "max_retries": MCP_MAX_RETRIES,
            })

    if failed_servers:
        logger.warning(
            "MCP graceful degradation: %d server(s) unavailable (%s), system continues without their tools",
            len(failed_servers), ", ".join(failed_servers),
        )

    return count


async def shutdown_mcp_providers() -> None:
    """Close all MCP server connections. Call at shutdown."""
    for provider in _mcp_providers:
        provider.close()
    _mcp_providers.clear()
    logger.info("All MCP providers shut down")
