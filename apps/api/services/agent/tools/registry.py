"""Tool registry and global singleton with built-in tool registration.

Separated from base.py for modularity. The ToolRegistry manages discovery,
registration, and execution of all tools. Registration helpers load tools
from built-in modules, YAML configs, and optional extension points.
"""

import logging
import threading
from typing import Any

from config import settings

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


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
        except (ValueError, KeyError, TypeError) as e:
            logger.exception("Tool '%s' failed with data error: %s", name, e)
            return ToolResult(success=False, output="", error=f"Tool error: {e}")
        except SQLAlchemyError as e:
            logger.exception("Tool '%s' failed with DB error: %s", name, e)
            return ToolResult(success=False, output="", error=f"Tool database error: {e}")
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.exception("Tool '%s' failed with network/IO error: %s", name, e)
            return ToolResult(success=False, output="", error=f"Tool error: {e}")
        except Exception as e:
            from libs.exceptions import AppError
            if isinstance(e, AppError):
                raise
            logger.exception("Tool '%s' failed with unexpected error: %s", name, e)
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
    except (ImportError, AttributeError) as e:
        logger.exception("Failed to load built-in tools: %s", e)

    _register_web_tools(registry)
    _register_export_tools(registry)
    _register_file_tools(registry)
    _register_mutation_tools(registry)
    _register_workspace_tools(registry)
    _register_preference_tools(registry)


def _register_web_tools(registry: ToolRegistry) -> None:
    """Register web-domain tools (search, etc.)."""
    if not settings.enable_experimental_browser:
        logger.info("Experimental browser/web-search tool is dormant (ENABLE_EXPERIMENTAL_BROWSER=false)")
        return
    try:
        from services.agent.tools.web_search import WebSearchTool

        registry.register(WebSearchTool())
        logger.info("Registered web search tool")
    except (ImportError, AttributeError) as e:
        logger.exception("Failed to load web tools: %s", e)


def _register_export_tools(registry: ToolRegistry) -> None:
    """Register export tools (Anki, calendar)."""
    try:
        from services.agent.tools.anki import ExportAnkiTool

        registry.register(ExportAnkiTool())
    except (ImportError, AttributeError) as e:
        logger.exception("Failed to load Anki export tool: %s", e)
    try:
        from services.agent.tools.calendar import ExportCalendarTool

        registry.register(ExportCalendarTool())
    except (ImportError, AttributeError) as e:
        logger.exception("Failed to load calendar export tool: %s", e)

    if settings.enable_experimental_notion_export:
        try:
            from services.agent.tools.notion import ExportNotionTool

            registry.register(ExportNotionTool())
            logger.info("Registered experimental Notion export tool")
        except (ImportError, AttributeError) as e:
            logger.exception("Failed to load Notion export tool: %s", e)
    else:
        logger.info("Experimental Notion export tool is dormant (ENABLE_EXPERIMENTAL_NOTION_EXPORT=false)")
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
    except (ImportError, AttributeError) as e:
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
    except (AttributeError, TypeError) as e:
        logger.exception("Failed to load content mutation tools: %s", e)


def _register_workspace_tools(registry: ToolRegistry) -> None:
    """Register workspace control tools (UI navigation, layout)."""
    try:
        from services.agent.tools.workspace import update_workspace

        registry.register(update_workspace)
        logger.info("Registered workspace control tool")
    except (ImportError, AttributeError) as e:
        logger.exception("Failed to load workspace tools: %s", e)


def _register_preference_tools(registry: ToolRegistry) -> None:
    """Register preference tools (save_user_preference)."""
    try:
        from services.agent.tools.preference_tools import save_user_preference

        registry.register(save_user_preference)
        logger.info("Registered preference tools")
    except (ImportError, AttributeError) as e:
        logger.exception("Failed to load preference tools: %s", e)


def _register_yaml_tools(registry: ToolRegistry) -> None:
    """Register tools from YAML files in config/tools/ directory."""
    try:
        from services.agent.tools.yaml_runner import load_yaml_tools

        load_yaml_tools(registry)
    except (ImportError, OSError, ValueError) as e:
        logger.exception("Failed to load YAML tools: %s", e)
