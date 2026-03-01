"""Executable tool base class and registry.

Borrows from:
- HelloAgents Tool ABC: run(parameters) -> str, get_parameters()
- OpenAkita handler: result truncation, error isolation
- MetaGPT ToolRegistry: tag-based discovery, OpenAI schema generation
- NanoBot progressive loading: summary descriptions for context efficiency
"""

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Truncation limit for tool results (OpenAkita uses 16000; we use 6000
# to balance information completeness with context budget)
MAX_TOOL_RESULT_CHARS = 6000


# ── Data Classes ──


@dataclass
class ToolParameter:
    """Single parameter definition for a tool."""

    name: str
    type: str  # "string", "integer", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def truncated(self) -> "ToolResult":
        """Return a copy with truncated output to prevent context overflow."""
        if len(self.output) > MAX_TOOL_RESULT_CHARS:
            return ToolResult(
                success=self.success,
                output=self.output[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated]",
                error=self.error,
                metadata=self.metadata,
            )
        return self


# ── Tool ABC ──


class Tool(ABC):
    """Base class for all executable tools.

    Each tool has:
    - name: unique identifier used in function calling / text parsing
    - description: NL description for LLM to understand when to use it
    - domain: category tag (e.g. "education", "web", "file", "general")
    """

    name: str = "base_tool"
    description: str = "A base tool."
    domain: str = "general"

    @abstractmethod
    def get_parameters(self) -> list[ToolParameter]:
        """Return the parameter definitions for this tool."""
        ...

    @abstractmethod
    async def run(
        self,
        parameters: dict[str, Any],
        ctx: Any,  # AgentContext (avoid circular import)
        db: AsyncSession,
    ) -> ToolResult:
        """Execute the tool with the given parameters.

        Args:
            parameters: Parsed parameter dict from LLM output.
            ctx: Current AgentContext (user_id, course_id, etc.).
            db: Async database session.
        """
        ...

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function calling JSON schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.get_parameters():
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_text_description(self) -> str:
        """Convert to NL description for text-based parsing fallback.

        Format: - tool_name: description  (param1: type, param2: type)
        """
        params_parts = []
        for p in self.get_parameters():
            opt = "" if p.required else ", optional"
            params_parts.append(f"{p.name}: {p.type}{opt}")
        params_str = ", ".join(params_parts) if params_parts else "none"
        return f"- {self.name}: {self.description}  ({params_str})"


# ── Tool Registry ──


class ToolRegistry:
    """Central registry of all available tools.

    Supports registration from multiple sources:
    - Built-in education tools
    - Python plugins (plugins/ directory)
    - YAML declarative tools (config/tools/)
    - MCP Server tools (config/mcp_servers.yaml)

    Later registrations override earlier ones (user tools > built-in).
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Overwrites if name already exists."""
        if tool.name in self._tools:
            logger.info(
                "Tool '%s' overridden (old domain=%s, new domain=%s)",
                tool.name,
                self._tools[tool.name].domain,
                tool.domain,
            )
        self._tools[tool.name] = tool
        logger.debug("Tool registered: %s [%s]", tool.name, tool.domain)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools(self, names: list[str]) -> list[Tool]:
        """Get multiple tools by name, skipping unknown names."""
        return [self._tools[n] for n in names if n in self._tools]

    def get_all(self) -> list[Tool]:
        return list(self._tools.values())

    def get_by_domain(self, domain: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.domain == domain]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(
        self,
        name: str,
        parameters: dict[str, Any],
        ctx: Any,
        db: AsyncSession,
    ) -> ToolResult:
        """Execute a registered tool by name with error isolation."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                success=False, output="", error=f"Unknown tool: {name}"
            )
        try:
            result = await tool.run(parameters, ctx, db)
            return result.truncated()
        except Exception as e:
            logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
            return ToolResult(success=False, output="", error=f"Tool error: {e}")


# ── Global Singleton ──

_tool_registry: ToolRegistry | None = None
_tool_registry_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry.

    Registration order (later overrides earlier):
    1. Built-in education tools
    2. Python plugins (plugins/ directory)
    3. YAML declarative tools (config/tools/)
    4. MCP Server tools (config/mcp_servers.yaml)
    """
    global _tool_registry
    if _tool_registry is not None:
        return _tool_registry
    with _tool_registry_lock:
        if _tool_registry is not None:
            return _tool_registry
        registry = ToolRegistry()
        _register_builtin_tools(registry)
        _register_plugins(registry)
        _register_yaml_tools(registry)
        _tool_registry = registry
    return _tool_registry


def _register_builtin_tools(registry: ToolRegistry) -> None:
    """Register all built-in education-domain tools."""
    try:
        from services.agent.tools.education import get_builtin_tools

        for tool in get_builtin_tools():
            registry.register(tool)
        logger.info(
            "Registered %d built-in education tools",
            len(registry.get_by_domain("education")),
        )
    except Exception as e:
        logger.warning("Failed to load built-in tools: %s", e)


def _register_plugins(registry: ToolRegistry) -> None:
    """Register tools from Python plugins in plugins/ directory."""
    try:
        from plugins.loader import load_plugins

        load_plugins(registry)
    except Exception as e:
        logger.warning("Failed to load plugins: %s", e)


def _register_yaml_tools(registry: ToolRegistry) -> None:
    """Register tools from YAML files in config/tools/ directory."""
    try:
        from services.agent.tools.yaml_runner import load_yaml_tools

        load_yaml_tools(registry)
    except Exception as e:
        logger.warning("Failed to load YAML tools: %s", e)
