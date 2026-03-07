"""Executable tool base class and registry.

Borrows from:
- HelloAgents Tool ABC: run(parameters) -> str, get_parameters()
- OpenAkita handler: result truncation, error isolation
- MetaGPT ToolRegistry: tag-based discovery, OpenAI schema generation
- NanoBot progressive loading: summary descriptions for context efficiency
"""

import hashlib
import json as _json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Truncation limit for tool results (OpenAkita uses 16000; we use 6000
# to balance information completeness with context budget)
MAX_TOOL_RESULT_CHARS = 6000

# Idempotency window: skip duplicate write-tool calls within this many seconds
IDEMPOTENCY_WINDOW_SECONDS = 120


class ToolCategory(str, Enum):
    """Classification of tool side-effect behaviour."""
    READ = "read"       # No side effects (search, lookup)
    WRITE = "write"     # Creates / mutates data (generate, save)
    COMPUTE = "compute" # Pure computation (run_code)


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
    - category: READ (no side effects), WRITE (creates data), COMPUTE (pure computation)
    """

    name: str = "base_tool"
    description: str = "A base tool."
    domain: str = "general"
    category: ToolCategory = ToolCategory.READ

    def idempotency_key(self, parameters: dict[str, Any], ctx: Any) -> str | None:
        """Compute a deduplication key for this tool call.

        Returns None for READ/COMPUTE tools (no dedup needed).
        WRITE tools return a SHA-256 hash of (course_id, tool_name, sorted_params).
        Override in subclasses for custom dedup logic.
        """
        if self.category != ToolCategory.WRITE:
            return None
        normalized = _json.dumps(
            {"course_id": str(getattr(ctx, "course_id", "")), "tool": self.name, **parameters},
            sort_keys=True,
            default=str,
        ).lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

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

    def explain_args(self, parameters: dict[str, Any]) -> str:
        """Human-readable explanation of what this tool call will do.

        Override in subclasses for domain-specific explanations.
        Default: "Running {name} with {key1}=val1, key2=val2"
        """
        if not parameters:
            return f"Running {self.name}"
        parts = ", ".join(f"{k}={v!r}" for k, v in list(parameters.items())[:3])
        return f"Running {self.name} with {parts}"

    def explain_result(self, result: "ToolResult") -> str:
        """Human-readable explanation of a tool result.

        Override in subclasses for domain-specific summaries.
        Default: first 120 chars of output or error message.
        """
        if not result.success:
            return f"Failed: {result.error or 'unknown error'}"
        preview = result.output[:120].replace("\n", " ")
        if len(result.output) > 120:
            preview += "..."
        return preview

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


# ── Function-based tool helpers ──


def param(
    name: str,
    type: str,
    description: str,
    *,
    required: bool = True,
    enum: list[str] | None = None,
    default: Any = None,
) -> ToolParameter:
    """Shorthand constructor for ToolParameter."""
    return ToolParameter(
        name=name, type=type, description=description,
        required=required, enum=enum, default=default,
    )


class FunctionTool(Tool):
    """Tool wrapping a plain async function — eliminates class boilerplate."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        fn: Any,
        domain: str = "education",
        category: ToolCategory = ToolCategory.READ,
        params: list[ToolParameter] | None = None,
    ):
        self.name = name
        self.description = description
        self.domain = domain
        self.category = category
        self._params = params or []
        self._fn = fn

    def get_parameters(self) -> list[ToolParameter]:
        return self._params

    async def run(
        self,
        parameters: dict[str, Any],
        ctx: Any,
        db: AsyncSession,
    ) -> ToolResult:
        return await self._fn(parameters, ctx, db)


def tool(
    *,
    name: str,
    description: str,
    domain: str = "education",
    category: ToolCategory = ToolCategory.READ,
    params: list[ToolParameter] | None = None,
):
    """Decorator that wraps an async function into a FunctionTool instance."""
    def decorator(fn: Any) -> FunctionTool:
        return FunctionTool(
            name=name, description=description, domain=domain,
            category=category, params=params, fn=fn,
        )
    return decorator


# ── Tool Registry ──


class ToolRegistry:
    """Central registry of all available tools.

    Supports registration from multiple sources:
    - Built-in education tools
    - YAML declarative tools (config/tools/)

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
        agent_name: str | None = None,
    ) -> ToolResult:
        """Execute a registered tool by name with error isolation.

        Args:
            agent_name: If provided, check capability permissions before running.
                        None = no check (backward compat).
        """
        # Capability check (defense in depth — ReActMixin also filters)
        if agent_name is not None:
            from services.agent.capabilities import check_tool_permission

            if not check_tool_permission(agent_name, name):
                logger.warning(
                    "Tool '%s' blocked for agent '%s' (capability violation)",
                    name, agent_name,
                )
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Agent '{agent_name}' is not allowed to use tool '{name}'.",
                )

        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                success=False, output="", error=f"Unknown tool: {name}"
            )

        # Idempotency: skip duplicate WRITE calls within the same turn
        idem_key = tool.idempotency_key(parameters, ctx)
        if idem_key is not None:
            if idem_key in ctx._idem_cache:
                logger.info(
                    "Idempotent skip: tool '%s' with key %s (returning cached result)",
                    name, idem_key,
                )
                return ctx._idem_cache[idem_key]

        try:
            result = await tool.run(parameters, ctx, db)
            truncated = result.truncated()

            # Cache result for same-turn idempotency
            if idem_key is not None:
                ctx._idem_cache[idem_key] = truncated

            return truncated
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
    2. YAML declarative tools (config/tools/)
    """
    global _tool_registry
    if _tool_registry is not None:
        return _tool_registry
    with _tool_registry_lock:
        if _tool_registry is not None:
            return _tool_registry
        registry = ToolRegistry()
        _register_builtin_tools(registry)
        _register_yaml_tools(registry)
        _tool_registry = registry
    return _tool_registry


def _register_builtin_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools (education + web + export + file)."""
    try:
        from services.agent.tools.education import get_builtin_tools

        for tool in get_builtin_tools():
            registry.register(tool)
        logger.info(
            "Registered %d built-in education tools",
            len(registry.get_by_domain("education")),
        )
    except Exception as e:
        logger.exception("Failed to load built-in tools: %s", e)

    _register_web_tools(registry)
    _register_export_tools(registry)
    _register_file_tools(registry)
    _register_mutation_tools(registry)
    _register_workspace_tools(registry)


def _register_web_tools(registry: ToolRegistry) -> None:
    """Register web-domain tools (search, etc.)."""
    try:
        from services.agent.tools.web_search import WebSearchTool

        registry.register(WebSearchTool())
        logger.info("Registered web search tool")
    except Exception as e:
        logger.exception("Failed to load web tools: %s", e)


def _register_export_tools(registry: ToolRegistry) -> None:
    """Register export tools (Anki, calendar)."""
    try:
        from services.agent.tools.anki import ExportAnkiTool

        registry.register(ExportAnkiTool())
    except Exception as e:
        logger.exception("Failed to load Anki export tool: %s", e)
    try:
        from services.agent.tools.calendar import ExportCalendarTool

        registry.register(ExportCalendarTool())
    except Exception as e:
        logger.exception("Failed to load calendar export tool: %s", e)
    logger.info("Registered export tools")


def _register_file_tools(registry: ToolRegistry) -> None:
    """Register filesystem tools (write, list, read)."""
    try:
        from services.agent.tools.filesystem import (
            WriteFileTool,
            ListFilesTool,
            ReadFileTool,
        )

        registry.register(WriteFileTool())
        registry.register(ListFilesTool())
        registry.register(ReadFileTool())
        logger.info("Registered %d file tools", len(registry.get_by_domain("file")))
    except Exception as e:
        logger.exception("Failed to load file tools: %s", e)


def _register_mutation_tools(registry: ToolRegistry) -> None:
    """Register content mutation tools (rewrite, annotate, lock, etc.)."""
    try:
        from services.agent.tools.content_mutations import get_mutation_tools

        tools = get_mutation_tools()
        for tool in tools:
            registry.register(tool)
        logger.info("Registered %d content mutation tools", len(tools))
    except ImportError:
        logger.debug("content_mutations module removed; skipping mutation tools")
    except Exception as e:
        logger.exception("Failed to load content mutation tools: %s", e)


def _register_workspace_tools(registry: ToolRegistry) -> None:
    """Register workspace control tools (UI navigation, layout)."""
    try:
        from services.agent.tools.workspace import update_workspace

        registry.register(update_workspace)
        logger.info("Registered workspace control tool")
    except Exception as e:
        logger.exception("Failed to load workspace tools: %s", e)



def _register_yaml_tools(registry: ToolRegistry) -> None:
    """Register tools from YAML files in config/tools/ directory."""
    try:
        from services.agent.tools.yaml_runner import load_yaml_tools

        load_yaml_tools(registry)
    except Exception as e:
        logger.exception("Failed to load YAML tools: %s", e)
