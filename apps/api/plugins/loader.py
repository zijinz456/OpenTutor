"""Plugin auto-discovery and registration.

Scans the plugins/ directory for Python files, imports them, finds all
Tool subclasses, and registers them into the global ToolRegistry.

Borrows from:
- MetaGPT ToolRegistry: file-scan + class introspection pattern
- NanoBot: progressive skill loading at startup

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

    Args:
        registry: Target registry. If None, uses the global singleton.

    Returns:
        Number of tools registered from plugins.
    """
    if registry is None:
        registry = get_tool_registry()

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

    if count:
        logger.info("Loaded %d plugin tool(s) from %s", count, _PLUGINS_DIR)
    return count
