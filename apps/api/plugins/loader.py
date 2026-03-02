"""Plugin auto-discovery and registration.

Scans the plugins/ directory for Python files, finds all Tool subclasses,
and registers them into the global ToolRegistry.  Also initializes the
pluggy-based plugin manager for lifecycle hooks.

Two systems work together:
1. **Tool loader** (this file) — registers Tool subclasses from plugins/.
2. **Plugin manager** (services/plugin/manager.py) — pluggy-based hook
   system for lifecycle hooks, integrations, and entry_point plugins.

Usage:
    from plugins.loader import load_plugins
    load_plugins()  # call once at startup
"""

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from services.agent.tools.base import Tool, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

# Directory containing user plugins
_PLUGINS_DIR = Path(__file__).parent


def load_plugins(registry: ToolRegistry | None = None) -> int:
    """Scan plugins/ directory and register all Tool subclasses.

    Also triggers the pluggy plugin manager to load hook-based plugins
    and call ``register_tools`` hooks.

    Args:
        registry: Target registry. If None, uses the global singleton.

    Returns:
        Number of tools registered from plugins.
    """
    if registry is None:
        registry = get_tool_registry()

    count = 0

    # 1. Classic file-scan for Tool subclasses
    count += _scan_tool_subclasses(registry)

    # 2. Pluggy-based plugin loading (hooks, entry_points, manifests)
    count += _load_pluggy_plugins(registry)

    if count:
        logger.info("Loaded %d plugin tool(s) total", count)
    return count


def _scan_tool_subclasses(registry: ToolRegistry) -> int:
    """Original file-scan approach: find Tool subclasses in plugins/."""
    count = 0
    package_name = "plugins"

    for importer, module_name, is_pkg in pkgutil.walk_packages(
        path=[str(_PLUGINS_DIR)],
        prefix=f"{package_name}.",
    ):
        if module_name.endswith(".__init__") or module_name.endswith(".loader"):
            continue
        # Skip examples/ directory — these are reference implementations
        # that must be copied to plugins/ root to activate
        if ".examples." in module_name or module_name.endswith(".examples"):
            continue
        # Skip extensions/ — handled by pluggy bridge
        if ".extensions." in module_name or module_name.endswith(".extensions"):
            continue

        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            logger.warning("Failed to import plugin %s: %s", module_name, e)
            continue

        for attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Tool)
                and obj is not Tool
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__  # only classes defined in this module
            ):
                try:
                    tool = obj()
                    registry.register(tool)
                    count += 1
                    logger.info(
                        "Plugin tool registered: %s from %s",
                        tool.name, module_name,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to instantiate plugin tool %s.%s: %s",
                        module_name, attr_name, e,
                    )

    return count


def _load_pluggy_plugins(registry: ToolRegistry) -> int:
    """Load pluggy-based plugins and call register_tools hooks."""
    try:
        from services.plugin.manager import get_plugin_manager

        pm = get_plugin_manager()
        pm.load_all()

        # Let plugins register their tools via the hook
        try:
            pm.hook.register_tools(registry=registry)
        except Exception as e:
            logger.warning("Plugin register_tools hooks failed: %s", e)

        return 0  # Tools registered via hooks are counted by the hook callers
    except Exception as e:
        logger.debug("Pluggy plugin loading skipped: %s", e)
        return 0
