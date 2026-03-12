"""YAML declarative tool runner.

Borrows from:
- NanoBot Skill system: lowest-barrier tool definition via YAML
- Dify tool YAML schema: endpoint + parameter + auth pattern

Allows non-technical users to define tools with zero Python code.
Each .yaml file in config/tools/ defines one tool.

Supported endpoint types:
- http: Make HTTP requests with template-based body/URL
- python_function: Call a dotted Python function path

Usage:
    from services.agent.tools.yaml_runner import load_yaml_tools
    load_yaml_tools()  # call at startup
"""

import asyncio
import importlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolParameter, ToolResult, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

_TOOLS_DIR = Path(__file__).parents[3] / "config" / "tools"


_BLOCKED_ENV_VARS = {
    "JWT_SECRET_KEY", "DATABASE_URL", "SECRET_KEY", "AWS_SECRET_ACCESS_KEY",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
    "LLM_API_KEY", "DB_PASSWORD", "POSTGRES_PASSWORD",
}


def _resolve_env_vars(text: str) -> str:
    """Replace ${VAR_NAME} with environment variable values."""
    def replacer(match):
        var_name = match.group(1)
        if var_name in _BLOCKED_ENV_VARS:
            logger.warning("SECURITY | Blocked env var reference in YAML tool: %s", var_name)
            return ""
        return os.getenv(var_name, "")
    return re.sub(r"\$\{(\w+)\}", replacer, text)


def _render_template(template: str, params: dict) -> str:
    """Simple {{param}} template rendering."""
    result = template
    for key, value in params.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def _extract_json_path(data: Any, path: str) -> Any:
    """Extract value from nested data using dot/bracket notation.

    Supports: "key", "key.subkey", "key[0]", "key[0].subkey"
    """
    if not path:
        return data

    parts = re.split(r"\.|\[(\d+)\]", path)
    current = data
    for part in parts:
        if part is None or part == "":
            continue
        if part.isdigit():
            idx = int(part)
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


class YAMLTool(Tool):
    """Tool defined by a YAML configuration file."""

    domain = "yaml"

    def __init__(self, config: dict):
        self.name = config["name"]
        self.description = config.get("description", f"YAML tool: {self.name}")
        self.domain = config.get("domain", "yaml")
        self._config = config
        self._parameters = self._parse_parameters(config.get("parameters", []))

    def _parse_parameters(self, raw_params: list[dict]) -> list[ToolParameter]:
        params = []
        for p in raw_params:
            params.append(ToolParameter(
                name=p["name"],
                type=p.get("type", "string"),
                description=p.get("description", ""),
                required=p.get("required", True),
                enum=p.get("enum"),
                default=p.get("default"),
            ))
        return params

    def get_parameters(self) -> list[ToolParameter]:
        return self._parameters

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        # Validate required parameters
        for p in self._parameters:
            if p.required and p.name not in parameters:
                return ToolResult(success=False, output="", error=f"Missing required parameter: {p.name}")

        endpoint = self._config.get("endpoint", {})
        endpoint_type = endpoint.get("type", "http")

        if endpoint_type == "http":
            return await self._run_http(endpoint, parameters)
        elif endpoint_type == "python_function":
            return await self._run_python_function(endpoint, parameters)
        else:
            return ToolResult(success=False, output="", error=f"Unknown endpoint type: {endpoint_type}")

    async def _run_http(self, endpoint: dict, parameters: dict) -> ToolResult:
        """Execute an HTTP endpoint."""
        try:
            import httpx
        except ImportError:
            return ToolResult(success=False, output="", error="httpx not installed. Run: pip install httpx")

        url = _resolve_env_vars(endpoint.get("url", ""))
        method = endpoint.get("method", "GET").upper()
        headers = {}
        for key, val in endpoint.get("headers", {}).items():
            headers[key] = _resolve_env_vars(str(val))

        # Build request body from template
        body = None
        body_template = endpoint.get("body_template")
        if body_template:
            rendered = _render_template(_resolve_env_vars(body_template), parameters)
            try:
                body = json.loads(rendered)
            except json.JSONDecodeError:
                body = rendered

        # URL template rendering
        url = _render_template(url, parameters)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers, params=parameters)
                elif method == "POST":
                    if isinstance(body, dict):
                        resp = await client.post(url, headers=headers, json=body)
                    else:
                        resp = await client.post(url, headers=headers, content=body)
                else:
                    resp = await client.request(method, url, headers=headers, json=body)

                resp.raise_for_status()

                # Parse response — try JSON first, fall back to text
                content_type = resp.headers.get("content-type", "")
                if "json" in content_type:
                    data = resp.json()
                else:
                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        return ToolResult(success=True, output=resp.text[:4000])

            # Extract result using path
            result_path = endpoint.get("result_path", "")
            if result_path:
                extracted = _extract_json_path(data, result_path)
                output = str(extracted) if extracted is not None else "No data at specified path"
            else:
                output = json.dumps(data, ensure_ascii=False, indent=2)[:4000]

            return ToolResult(success=True, output=output)

        except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
            logger.exception("YAML HTTP tool %s failed: %s", self.name, e)
            return ToolResult(success=False, output="", error=str(e))

    # Safe module prefixes for python_function endpoint type.
    # Only functions under these modules can be called from YAML tools.
    _ALLOWED_MODULE_PREFIXES = ("services.", "plugins.", "utils.")

    async def _run_python_function(self, endpoint: dict, parameters: dict) -> ToolResult:
        """Call a Python function by dotted path (restricted to safe modules)."""
        func_path = endpoint.get("function", "")
        if not func_path:
            return ToolResult(success=False, output="", error="No function specified")

        try:
            module_path, func_name = func_path.rsplit(".", 1)
        except ValueError:
            return ToolResult(success=False, output="", error=f"Invalid function path: {func_path}")

        # Security: only allow functions from whitelisted module prefixes
        if not any(module_path.startswith(p) for p in self._ALLOWED_MODULE_PREFIXES):
            return ToolResult(
                success=False, output="",
                error=f"Module '{module_path}' not in allowed prefixes: {self._ALLOWED_MODULE_PREFIXES}",
            )

        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ValueError, ImportError, AttributeError) as e:
            return ToolResult(success=False, output="", error=f"Cannot resolve function '{func_path}': {e}")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**parameters)
            else:
                result = func(**parameters)

            return ToolResult(success=True, output=str(result))
        except (ValueError, TypeError, KeyError, RuntimeError, AttributeError) as e:
            logger.exception("YAML python_function tool %s failed: %s", self.name, e)
            return ToolResult(success=False, output="", error=str(e))


def load_yaml_tools(registry: ToolRegistry | None = None) -> int:
    """Load tools from YAML files in config/tools/ directory.

    Args:
        registry: Target registry. If None, uses the global singleton.

    Returns:
        Number of tools registered.
    """
    if registry is None:
        registry = get_tool_registry()

    if yaml is None:
        logger.debug("pyyaml not installed, skipping YAML tools")
        return 0

    if not _TOOLS_DIR.exists():
        logger.debug("No YAML tools directory at %s, skipping", _TOOLS_DIR)
        return 0

    count = 0
    for yaml_file in sorted(_TOOLS_DIR.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                config = yaml.safe_load(f)

            if not config or not config.get("name"):
                logger.warning("YAML tool %s: missing 'name' field, skipping", yaml_file.name)
                continue

            tool = YAMLTool(config)
            registry.register(tool)
            count += 1
            logger.info("YAML tool registered: %s from %s", tool.name, yaml_file.name)

        except (ValueError, KeyError, TypeError, OSError) as e:
            logger.exception("Failed to load YAML tool %s: %s", yaml_file.name, e)

    if count:
        logger.info("Loaded %d YAML tool(s) from %s", count, _TOOLS_DIR)
    return count
