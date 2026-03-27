"""Executable tool base class, data classes, and helper constructors.

Borrows from:
- HelloAgents Tool ABC: run(parameters) -> str, get_parameters()
- OpenAkita handler: result truncation, error isolation
- MetaGPT ToolRegistry: tag-based discovery, OpenAI schema generation
- NanoBot progressive loading: summary descriptions for context efficiency

Registry and registration logic lives in services.agent.tools.registry.
All public names are re-exported here for backward compatibility.
"""

import hashlib
import json as _json
import logging
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

    # Map Python type names to JSON Schema type names.
    _PY_TO_JSON_TYPE: dict[str, str] = {
        "str": "string", "int": "integer", "float": "number",
        "bool": "boolean", "list": "array", "dict": "object",
    }

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function calling JSON schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.get_parameters():
            json_type = self._PY_TO_JSON_TYPE.get(param.type, param.type)
            prop: dict[str, Any] = {
                "type": json_type,
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
        """Human-readable explanation of what this tool call will do."""
        if not parameters:
            return f"Running {self.name}"
        parts = ", ".join(f"{k}={v!r}" for k, v in list(parameters.items())[:3])
        return f"Running {self.name} with {parts}"

    def explain_result(self, result: "ToolResult") -> str:
        """Human-readable explanation of a tool result."""
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


# ── Backward-compatibility re-exports from registry ──
# These were originally defined in this file; import them so existing
# `from services.agent.tools.base import ToolRegistry, get_tool_registry`
# statements continue to work.

from services.agent.tools.registry import ToolRegistry, get_tool_registry  # noqa: E402, F401

__all__ = [
    "MAX_TOOL_RESULT_CHARS",
    "IDEMPOTENCY_WINDOW_SECONDS",
    "ToolCategory",
    "ToolParameter",
    "ToolResult",
    "Tool",
    "param",
    "FunctionTool",
    "tool",
    "ToolRegistry",
    "get_tool_registry",
]
