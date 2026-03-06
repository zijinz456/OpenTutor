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
import contextlib
import json
import logging
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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
        self._http_client: Any | None = None
        self._sse_task: asyncio.Task | None = None
        self._sse_ready = asyncio.Event()
        self._message_url: str | None = None
        self._streamable_http_url: str | None = None
        self._session_id: str | None = None
        self._pending_sse_requests: dict[int, asyncio.Future] = {}
        self._request_id = 0
        self._timeout = config.get("timeout", 30)  # Configurable per-server
        self._tools: list[Tool] = []  # Cache discovered tools for reconnection

    def _transport(self) -> str:
        return str(self.config.get("transport", "stdio")).strip().lower()

    async def connect(self) -> list[Tool]:
        """Connect to the MCP server and discover available tools."""
        transport = self._transport()
        if transport == "stdio":
            tools = await self._connect_stdio()
            if tools:
                self._tools = tools
            return tools
        elif transport == "sse":
            tools = await self._connect_sse()
            if tools:
                self._tools = tools
            return tools
        elif transport in {"streamable_http", "streamable-http", "http"}:
            tools = await self._connect_streamable_http()
            if tools:
                self._tools = tools
            return tools
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
        transport = self._transport()
        if transport == "sse":
            return self._http_client is not None and self._sse_task is not None and not self._sse_task.done()
        if transport in {"streamable_http", "streamable-http", "http"}:
            return self._http_client is not None and bool(self._streamable_http_url)
        return self._process is not None and self._process.poll() is None

    def _resolve_config_value(self, value: Any) -> Any:
        """Resolve ${ENV_VAR} placeholders inside config values."""
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return os.getenv(value[2:-1], "")
        if isinstance(value, dict):
            return {str(k): self._resolve_config_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_config_value(item) for item in value]
        return value

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

    async def _connect_sse(self) -> list[Tool]:
        """Connect to an MCP server via the legacy SSE transport."""
        import httpx

        sse_url = str(self.config.get("url", "")).strip()
        if not sse_url:
            logger.warning("MCP server %s: no SSE url specified", self.server_name)
            return []

        headers = self._resolve_config_value(self.config.get("headers", {})) or {}
        self._message_url = str(self._resolve_config_value(self.config.get("message_url", "")) or "").strip() or None
        self._sse_ready = asyncio.Event()

        timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
        self._http_client = httpx.AsyncClient(timeout=timeout, headers=headers)
        self._sse_task = asyncio.create_task(self._listen_sse_events(sse_url), name=f"mcp-sse-{self.server_name}")

        try:
            await asyncio.wait_for(self._sse_ready.wait(), timeout=min(float(self._timeout), 10.0))

            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "opentutor", "version": "0.1.0"},
            })
            if not init_result:
                logger.warning("MCP server %s: SSE initialization failed", self.server_name)
                self.close()
                return []

            await self._send_notification("notifications/initialized", {})
            tools_result = await self._send_request("tools/list", {})
            if not tools_result or "tools" not in tools_result:
                logger.info("MCP server %s: no tools available via SSE", self.server_name)
                self.close()
                return []

            return self._parse_tools(tools_result["tools"])
        except Exception as e:
            logger.warning("MCP server %s: SSE connection failed: %s", self.server_name, e)
            self.close()
            return []

    async def _connect_streamable_http(self) -> list[Tool]:
        """Connect to an MCP server via the current Streamable HTTP transport."""
        import httpx

        endpoint = str(self.config.get("url", "")).strip()
        if not endpoint:
            logger.warning("MCP server %s: no Streamable HTTP url specified", self.server_name)
            return []

        headers = self._resolve_config_value(self.config.get("headers", {})) or {}
        timeout = httpx.Timeout(connect=10.0, read=self._timeout, write=10.0, pool=10.0)
        self._http_client = httpx.AsyncClient(timeout=timeout, headers=headers)
        self._streamable_http_url = endpoint
        self._session_id = None

        try:
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "opentutor", "version": "0.1.0"},
            })
            if not init_result:
                logger.warning("MCP server %s: Streamable HTTP initialization failed", self.server_name)
                self.close()
                return []

            await self._send_notification("notifications/initialized", {})
            tools_result = await self._send_request("tools/list", {})
            if not tools_result or "tools" not in tools_result:
                logger.info("MCP server %s: no tools available via Streamable HTTP", self.server_name)
                self.close()
                return []

            return self._parse_tools(tools_result["tools"])
        except Exception as e:
            logger.warning("MCP server %s: Streamable HTTP connection failed: %s", self.server_name, e)
            self.close()
            return []

    async def _listen_sse_events(self, sse_url: str) -> None:
        """Background task that consumes SSE events and resolves pending requests."""
        if self._http_client is None:
            raise RuntimeError("SSE HTTP client not initialized")

        try:
            async with self._http_client.stream(
                "GET",
                sse_url,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                if self._message_url:
                    self._message_url = urljoin(str(response.url), self._message_url)
                    self._sse_ready.set()

                event_name = "message"
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        await self._handle_sse_event(event_name, "\n".join(data_lines), base_url=str(response.url))
                        event_name = "message"
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip() or "message"
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].lstrip())

                if data_lines:
                    await self._handle_sse_event(event_name, "\n".join(data_lines), base_url=str(response.url))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._message_url or not self._sse_ready.is_set():
                logger.warning("MCP server %s: SSE listener stopped: %s", self.server_name, exc)
        finally:
            self._fail_pending_sse_requests(ConnectionError(f"MCP SSE connection closed for {self.server_name}"))
            self._sse_ready.clear()

    async def _handle_sse_event(self, event_name: str, data: str, *, base_url: str) -> None:
        """Handle a single SSE event frame."""
        if not data:
            return
        if event_name == "endpoint":
            endpoint = data
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(data)
                if isinstance(payload, dict):
                    endpoint = str(payload.get("url") or payload.get("endpoint") or endpoint)
            self._message_url = urljoin(base_url, endpoint)
            self._sse_ready.set()
            return

        if event_name != "message":
            logger.debug("MCP server %s: ignoring SSE event '%s'", self.server_name, event_name)
            return

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("MCP server %s: invalid SSE JSON payload: %s", self.server_name, data[:200])
            return

        request_id = payload.get("id")
        if request_id is None:
            return
        future = self._pending_sse_requests.pop(int(request_id), None)
        if future and not future.done():
            future.set_result(payload)

    async def _parse_event_stream_response(self, response, request_id: int | None = None) -> dict[str, Any] | None:
        """Parse a `text/event-stream` response into a JSON-RPC payload."""
        event_name = "message"
        data_lines: list[str] = []
        base_url = str(response.url)

        async for line in response.aiter_lines():
            if line == "":
                payload = await self._parse_event_stream_frame(
                    event_name,
                    "\n".join(data_lines),
                    base_url=base_url,
                    request_id=request_id,
                )
                if payload is not None:
                    return payload
                event_name = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip() or "message"
                continue
            if line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())

        if data_lines:
            return await self._parse_event_stream_frame(
                event_name,
                "\n".join(data_lines),
                base_url=base_url,
                request_id=request_id,
            )
        return None

    async def _parse_event_stream_frame(
        self,
        event_name: str,
        data: str,
        *,
        base_url: str,
        request_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Parse a single SSE frame for either transport variant."""
        if not data:
            return None
        if event_name == "endpoint":
            endpoint = data
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(data)
                if isinstance(payload, dict):
                    endpoint = str(payload.get("url") or payload.get("endpoint") or endpoint)
            self._message_url = urljoin(base_url, endpoint)
            self._sse_ready.set()
            return None
        if event_name != "message":
            logger.debug("MCP server %s: ignoring SSE event '%s'", self.server_name, event_name)
            return None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("MCP server %s: invalid SSE JSON payload: %s", self.server_name, data[:200])
            return None

        payload_id = payload.get("id")
        if request_id is not None and payload_id == request_id:
            return payload
        if payload_id is None:
            return None
        future = self._pending_sse_requests.pop(int(payload_id), None)
        if future and not future.done():
            future.set_result(payload)
        return None

    def _fail_pending_sse_requests(self, exc: BaseException) -> None:
        """Reject any in-flight SSE requests when the stream drops."""
        for request_id, future in list(self._pending_sse_requests.items()):
            if not future.done():
                future.set_exception(exc)
            self._pending_sse_requests.pop(request_id, None)

    async def _post_sse_message(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC payload to the MCP SSE message endpoint."""
        if self._http_client is None:
            raise RuntimeError("SSE HTTP client not initialized")
        if not self._message_url:
            raise RuntimeError(f"MCP server '{self.server_name}' did not provide a message endpoint")

        response = await self._http_client.post(
            self._message_url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type and response.content:
            return response.json()
        if response.content:
            with contextlib.suppress(json.JSONDecodeError):
                return json.loads(response.text)
        return None

    async def _post_streamable_http_message(self, payload: dict[str, Any], *, expect_response: bool) -> dict[str, Any] | None:
        """Send a JSON-RPC payload to a Streamable HTTP MCP endpoint."""
        if self._http_client is None or not self._streamable_http_url:
            raise RuntimeError("Streamable HTTP client not initialized")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        response = await self._http_client.post(self._streamable_http_url, json=payload, headers=headers)
        if response.status_code == 404 and self._session_id:
            old_session = self._session_id
            self._session_id = None
            raise RuntimeError(f"MCP session expired for {self.server_name}: {old_session}")
        response.raise_for_status()

        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        if not expect_response:
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                await self._parse_event_stream_response(response)
            return None

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type and response.content:
            return response.json()
        if "text/event-stream" in content_type:
            return await self._parse_event_stream_response(response, request_id=payload.get("id"))
        if response.content:
            with contextlib.suppress(json.JSONDecodeError):
                return json.loads(response.text)
        return None

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
        transport = self._transport()
        if transport == "sse":
            return await self._send_request_sse(method, params)
        if transport in {"streamable_http", "streamable-http", "http"}:
            return await self._send_request_streamable_http(method, params)
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

    async def _send_request_sse(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request over the legacy SSE transport."""
        if self._http_client is None:
            return None

        self._request_id += 1
        request_id = self._request_id
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_sse_requests[request_id] = future

        try:
            response_payload = await self._post_sse_message(request)
            if response_payload is not None:
                self._pending_sse_requests.pop(request_id, None)
                if "error" in response_payload:
                    logger.warning("MCP %s error: %s", method, response_payload["error"])
                    return None
                return response_payload.get("result")

            response = await asyncio.wait_for(future, timeout=self._timeout)
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
        finally:
            self._pending_sse_requests.pop(request_id, None)

    async def _send_request_streamable_http(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request over the Streamable HTTP transport."""
        if self._http_client is None:
            return None

        self._request_id += 1
        request_id = self._request_id
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            response_payload = await self._post_streamable_http_message(request, expect_response=True)
            if response_payload is None:
                return None
            if "error" in response_payload:
                logger.warning("MCP %s error: %s", method, response_payload["error"])
                return None
            return response_payload.get("result")
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
        transport = self._transport()
        if transport == "sse":
            await self._send_notification_sse(method, params)
            return
        if transport in {"streamable_http", "streamable-http", "http"}:
            await self._send_notification_streamable_http(method, params)
            return
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

    async def _send_notification_sse(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification over the legacy SSE transport."""
        try:
            await self._post_sse_message({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            })
        except Exception as e:
            logger.warning("MCP notification %s failed: %s", method, e)

    async def _send_notification_streamable_http(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification over Streamable HTTP."""
        try:
            await self._post_streamable_http_message({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }, expect_response=False)
        except Exception as e:
            logger.warning("MCP notification %s failed: %s", method, e)

    def close(self):
        """Terminate the MCP server subprocess and close pipes."""
        self._fail_pending_sse_requests(ConnectionError(f"MCP provider '{self.server_name}' closed"))
        if self._sse_task:
            self._sse_task.cancel()
            self._sse_task = None
        if self._streamable_http_url and self._session_id and self._http_client is not None:
            with contextlib.suppress(RuntimeError):
                loop = asyncio.get_running_loop()
                session_id = self._session_id
                endpoint = self._streamable_http_url
                client = self._http_client
                loop.create_task(
                    client.delete(
                        endpoint,
                        headers={"Mcp-Session-Id": session_id},
                    )
                )
        if self._http_client is not None:
            with contextlib.suppress(RuntimeError):
                loop = asyncio.get_running_loop()
                loop.create_task(self._http_client.aclose())
            self._http_client = None
        self._message_url = None
        self._streamable_http_url = None
        self._session_id = None
        self._sse_ready.clear()
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
    """Log an MCP-related event (audit DB persistence removed in Phase 1.3)."""
    logger.debug("MCP audit: %s %s %s", server_name, outcome, details)


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
