"""Plugin manager — discovery, loading, and lifecycle management.

Discovers plugins from three sources (later overrides earlier):
1. **Built-in plugins**: ``plugins/`` directory (auto-scanned).
2. **Entry points**: ``pip install``-able packages with
   ``opentutor`` entry point group.
3. **Legacy extensions**: ``plugins/extensions/`` directory
   (backward-compatible bridge to old Extension system).

Each plugin can optionally provide a ``manifest.py`` with metadata::

    MANIFEST = {
        "name": "google-calendar",
        "version": "1.0.0",
        "description": "Google Calendar integration",
        "author": "OpenTutor",
        "requires": {"opentutor": ">=1.0"},
        "tools": ["create_calendar_event", "get_upcoming_exams"],
        "integrations": ["google_calendar"],
    }
"""

import importlib
import inspect
import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pluggy

from services.plugin.hookspec import PROJECT_NAME, OpenTutorHookSpec, hookimpl

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Metadata about a loaded plugin."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    requires: dict[str, str] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    source: str = "unknown"  # "directory" | "entry_point" | "legacy"


class PluginManager:
    """Central plugin manager for OpenTutor.

    Wraps pluggy's PluginManager with manifest tracking, safe loading,
    and integration with the existing Extension system.
    """

    def __init__(self):
        self._pm = pluggy.PluginManager(PROJECT_NAME)
        self._pm.add_hookspecs(OpenTutorHookSpec)
        self._manifests: dict[str, PluginManifest] = {}
        self._initialized = False

    @property
    def hook(self):
        """Access the hook caller (e.g., ``manager.hook.on_pre_agent(...)``)."""
        return self._pm.hook

    @property
    def manifests(self) -> dict[str, PluginManifest]:
        """Return all loaded plugin manifests."""
        return dict(self._manifests)

    def register_plugin(self, plugin: object, name: Optional[str] = None) -> bool:
        """Register a plugin object (class instance with @hookimpl methods)."""
        plugin_name = name or getattr(plugin, "name", type(plugin).__name__)
        try:
            self._pm.register(plugin, name=plugin_name)
            logger.info("Plugin registered: %s", plugin_name)
            return True
        except Exception as e:
            logger.warning("Failed to register plugin '%s': %s", plugin_name, e)
            return False

    def unregister_plugin(self, name: str) -> bool:
        """Unregister a plugin by name."""
        plugin = self._pm.get_plugin(name)
        if plugin:
            self._pm.unregister(plugin, name=name)
            self._manifests.pop(name, None)
            logger.info("Plugin unregistered: %s", name)
            return True
        return False

    def load_all(self) -> int:
        """Load plugins from all sources. Returns total count."""
        if self._initialized:
            return len(self._manifests)

        count = 0
        count += self._load_directory_plugins()
        count += self._load_entry_point_plugins()
        count += self._load_legacy_extensions()
        self._initialized = True

        logger.info("Loaded %d plugin(s) total", count)
        return count

    def _load_directory_plugins(self) -> int:
        """Scan plugins/ directory for plugin modules."""
        plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        if not plugins_dir.is_dir():
            return 0

        count = 0
        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_") or path.name == "loader.py":
                continue
            count += self._try_load_module(
                f"plugins.{path.stem}", path, source="directory"
            )

        # Also scan subdirectories (each is a plugin package)
        for pkg_dir in sorted(plugins_dir.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name.startswith("_"):
                continue
            if pkg_dir.name in ("examples", "extensions", "__pycache__"):
                continue
            init_file = pkg_dir / "__init__.py"
            if init_file.exists():
                count += self._try_load_module(
                    f"plugins.{pkg_dir.name}", init_file, source="directory"
                )

        return count

    def _load_entry_point_plugins(self) -> int:
        """Load plugins registered via setuptools entry_points."""
        count = 0
        try:
            if sys.version_info >= (3, 10):
                from importlib.metadata import entry_points
                eps = entry_points(group=PROJECT_NAME)
            else:
                from importlib.metadata import entry_points
                all_eps = entry_points()
                eps = all_eps.get(PROJECT_NAME, [])

            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    plugin = plugin_cls() if inspect.isclass(plugin_cls) else plugin_cls
                    if self.register_plugin(plugin, name=ep.name):
                        self._manifests[ep.name] = PluginManifest(
                            name=ep.name,
                            source="entry_point",
                        )
                        count += 1
                except Exception as e:
                    logger.warning("Entry point plugin '%s' failed: %s", ep.name, e)
        except Exception as e:
            logger.debug("Entry point loading skipped: %s", e)

        return count

    def _load_legacy_extensions(self) -> int:
        """Bridge: load old-style Extension subclasses as pluggy plugins."""
        ext_dir = Path(__file__).parent.parent.parent / "plugins" / "extensions"
        if not ext_dir.is_dir():
            return 0

        count = 0
        for path in sorted(ext_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                module_name = f"plugins.extensions.{path.stem}"
                if module_name in sys.modules:
                    mod = sys.modules[module_name]
                else:
                    spec = importlib.util.spec_from_file_location(module_name, path)
                    if not spec or not spec.loader:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)

                # Old-style: look for register_extension(registry) function
                # New-style: look for Plugin class with @hookimpl methods
                register_fn = getattr(mod, "register_extension", None)
                if callable(register_fn):
                    bridge = _LegacyExtensionBridge(path.stem, register_fn)
                    if self.register_plugin(bridge, name=f"legacy_{path.stem}"):
                        self._manifests[f"legacy_{path.stem}"] = PluginManifest(
                            name=path.stem,
                            source="legacy",
                        )
                        count += 1

                # Also check for direct hookimpl classes
                for attr_name, obj in inspect.getmembers(mod, inspect.isclass):
                    if obj.__module__ == module_name and _has_hookimpls(obj):
                        plugin = obj()
                        name = getattr(plugin, "name", attr_name)
                        if self.register_plugin(plugin, name=name):
                            count += 1
            except Exception as e:
                logger.warning("Legacy extension '%s' failed: %s", path.name, e)

        return count

    def _try_load_module(self, module_name: str, path: Path, source: str) -> int:
        """Try to load a single plugin module and register its hooks."""
        try:
            if module_name in sys.modules:
                mod = sys.modules[module_name]
            else:
                mod = importlib.import_module(module_name)

            # Look for a Plugin class or a register() function
            plugin_obj = None
            manifest = None

            # Check for MANIFEST dict
            raw_manifest = getattr(mod, "MANIFEST", None)
            if isinstance(raw_manifest, dict):
                manifest = PluginManifest(**{
                    k: v for k, v in raw_manifest.items()
                    if k in PluginManifest.__dataclass_fields__
                })
                manifest.source = source

            # Check for Plugin class with hookimpl methods
            for attr_name, obj in inspect.getmembers(mod, inspect.isclass):
                if obj.__module__ == module_name and _has_hookimpls(obj):
                    plugin_obj = obj()
                    break

            # Check for register() function
            if plugin_obj is None:
                register_fn = getattr(mod, "register", None)
                if callable(register_fn):
                    plugin_obj = _FunctionPlugin(module_name, register_fn)

            if plugin_obj is None:
                return 0

            plugin_name = (
                manifest.name if manifest
                else getattr(plugin_obj, "name", Path(path).stem)
            )

            if self.register_plugin(plugin_obj, name=plugin_name):
                if manifest is None:
                    manifest = PluginManifest(name=plugin_name, source=source)
                self._manifests[plugin_name] = manifest
                return 1

        except Exception as e:
            logger.warning("Plugin module '%s' failed to load: %s", module_name, e)

        return 0

    async def startup(self) -> None:
        """Call on_startup hooks for all loaded plugins."""
        try:
            self._pm.hook.on_startup()
        except Exception as e:
            logger.warning("Plugin startup hooks failed: %s", e)

    async def shutdown(self) -> None:
        """Call on_shutdown hooks for all loaded plugins."""
        try:
            self._pm.hook.on_shutdown()
        except Exception as e:
            logger.warning("Plugin shutdown hooks failed: %s", e)


def _has_hookimpls(cls: type) -> bool:
    """Check if a class has any pluggy hookimpl-decorated methods."""
    for name in dir(cls):
        method = getattr(cls, name, None)
        if callable(method) and hasattr(method, PROJECT_NAME + "_impl"):
            return True
    return False


class _LegacyExtensionBridge:
    """Bridges old-style Extension plugins to the pluggy system.

    Wraps a ``register_extension(registry)`` function so it can be
    called during the pluggy tool registration phase.
    """

    def __init__(self, name: str, register_fn):
        self.name = name
        self._register_fn = register_fn

    @hookimpl
    def register_tools(self, registry):
        """Bridge: call the old register_extension with the extension registry."""
        try:
            from services.agent.extensions import get_extension_registry
            ext_registry = get_extension_registry()
            self._register_fn(ext_registry)
        except Exception as e:
            logger.warning("Legacy extension bridge '%s' failed: %s", self.name, e)


class _FunctionPlugin:
    """Wraps a module-level register() function as a plugin object."""

    def __init__(self, name: str, register_fn):
        self.name = name
        self._register_fn = register_fn

    @hookimpl
    def register_tools(self, registry):
        self._register_fn(registry)


# ── Global Singleton ──

_plugin_manager: PluginManager | None = None
_plugin_manager_lock = threading.Lock()


def get_plugin_manager() -> PluginManager:
    """Get or create the global plugin manager (thread-safe)."""
    global _plugin_manager
    if _plugin_manager is not None:
        return _plugin_manager
    with _plugin_manager_lock:
        if _plugin_manager is not None:
            return _plugin_manager
        _plugin_manager = PluginManager()
    return _plugin_manager
