"""Extension/Plugin API for the agent lifecycle.

Provides hook points at each stage of the agent orchestration pipeline,
allowing plugins to observe or modify behavior without touching core code.

Hook points:
- PRE_ROUTING: Before intent classification
- POST_ROUTING: After intent classification, before agent selection
- PRE_AGENT: Before agent execution
- POST_AGENT: After agent execution, before post-processing
- PRE_TOOL: Before a tool is executed
- POST_TOOL: After a tool completes
- POST_PROCESS: After post-processing (memory, signals, etc.)
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ExtensionHook(str, Enum):
    """Lifecycle hook points in the agent pipeline."""

    PRE_ROUTING = "pre_routing"
    POST_ROUTING = "post_routing"
    PRE_AGENT = "pre_agent"
    POST_AGENT = "post_agent"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    POST_PROCESS = "post_process"


class Extension(ABC):
    """Base class for agent lifecycle extensions.

    Subclass and override on_hook() to add custom behavior
    at specific points in the agent pipeline.
    """

    name: str = "base_extension"
    hooks: list[ExtensionHook] = []  # Which hooks this extension subscribes to

    @abstractmethod
    async def on_hook(
        self,
        hook: ExtensionHook,
        ctx: Any,
        **kwargs: Any,
    ) -> None:
        """Called when a subscribed hook fires.

        Args:
            hook: Which lifecycle point triggered this call.
            ctx: The current AgentContext (mutable).
            **kwargs: Hook-specific data:
                PRE_ROUTING: message=str
                POST_ROUTING: intent=str, confidence=float, agent_name=str
                PRE_AGENT: agent_name=str
                POST_AGENT: agent_name=str, response=str
                PRE_TOOL: tool_name=str, parameters=dict
                POST_TOOL: tool_name=str, result=str, success=bool, duration_ms=float
                POST_PROCESS: response=str
        """
        ...


class ExtensionRegistry:
    """Central registry for agent lifecycle extensions."""

    def __init__(self):
        self._extensions: list[Extension] = []
        self._by_hook: dict[ExtensionHook, list[Extension]] = {
            hook: [] for hook in ExtensionHook
        }

    def register(self, extension: Extension) -> None:
        """Register an extension. Later registrations run after earlier ones."""
        self._extensions.append(extension)
        for hook in extension.hooks:
            self._by_hook[hook].append(extension)
        logger.info(
            "Extension registered: %s (hooks: %s)",
            extension.name,
            [h.value for h in extension.hooks],
        )

    def unregister(self, name: str) -> bool:
        """Remove an extension by name."""
        before = len(self._extensions)
        self._extensions = [e for e in self._extensions if e.name != name]
        for hook in ExtensionHook:
            self._by_hook[hook] = [
                e for e in self._by_hook[hook] if e.name != name
            ]
        removed = before - len(self._extensions)
        if removed:
            logger.info("Extension unregistered: %s", name)
        return removed > 0

    async def run_hooks(
        self,
        hook: ExtensionHook,
        ctx: Any,
        **kwargs: Any,
    ) -> None:
        """Fire a hook, calling all subscribed extensions in order.

        Errors in individual extensions are logged but don't block others.
        """
        extensions = self._by_hook.get(hook, [])
        if not extensions:
            return

        for ext in extensions:
            try:
                await ext.on_hook(hook, ctx, **kwargs)
            except Exception as e:
                logger.warning(
                    "Extension '%s' failed on hook '%s': %s",
                    ext.name,
                    hook.value,
                    e,
                )

    @property
    def registered_extensions(self) -> list[str]:
        return [e.name for e in self._extensions]


# ── Global singleton ──

_extension_registry: ExtensionRegistry | None = None


def get_extension_registry() -> ExtensionRegistry:
    """Get or create the global extension registry."""
    global _extension_registry
    if _extension_registry is None:
        _extension_registry = ExtensionRegistry()
        _load_builtin_extensions(_extension_registry)
    return _extension_registry


def _load_builtin_extensions(registry: ExtensionRegistry) -> None:
    """Load any built-in extensions (e.g., from plugins/ directory)."""
    try:
        from pathlib import Path

        plugins_dir = Path(__file__).parent.parent.parent / "plugins" / "extensions"
        if not plugins_dir.is_dir():
            return

        import importlib
        import sys

        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module_name = f"plugins.extensions.{path.stem}"
            try:
                if module_name in sys.modules:
                    mod = sys.modules[module_name]
                else:
                    spec = importlib.util.spec_from_file_location(module_name, path)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = mod
                        spec.loader.exec_module(mod)
                    else:
                        continue

                # Look for register_extension(registry) function
                register_fn = getattr(mod, "register_extension", None)
                if callable(register_fn):
                    register_fn(registry)
            except Exception as e:
                logger.warning("Failed to load extension plugin %s: %s", path.name, e)
    except Exception as e:
        logger.debug("Extension plugin loading skipped: %s", e)
