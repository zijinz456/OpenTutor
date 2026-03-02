"""OpenTutor plugin hook specifications (pluggy).

Defines all extension points that plugins can implement. Plugins register
by providing ``@hookimpl`` implementations and a ``register()`` entry point
or by being placed in the ``plugins/`` directory.

Hook categories:
- **Tool hooks**: Register new agent tools.
- **Lifecycle hooks**: Observe/modify agent pipeline stages.
- **Integration hooks**: Register external service integrations.
- **Event hooks**: React to learning events (xAPI).

Usage for plugin authors::

    from services.plugin.hookspec import hookimpl

    class MyPlugin:
        @hookimpl
        def register_tools(self, registry):
            registry.register(MyCustomTool())

        @hookimpl
        def on_post_agent(self, ctx, agent_name, response):
            # Log or modify response
            ...
"""

import pluggy

PROJECT_NAME = "opentutor"

hookspec = pluggy.HookspecMarker(PROJECT_NAME)
hookimpl = pluggy.HookimplMarker(PROJECT_NAME)


class OpenTutorHookSpec:
    """All available plugin hooks for OpenTutor."""

    # ── Tool Registration ──

    @hookspec
    def register_tools(self, registry) -> None:
        """Register new agent tools into the ToolRegistry.

        Called once during startup. The ``registry`` argument is the global
        ``ToolRegistry`` instance.

        Example::

            @hookimpl
            def register_tools(self, registry):
                registry.register(MyTool())
        """

    # ── Agent Lifecycle Hooks ──

    @hookspec(firstresult=False)
    def on_pre_routing(self, ctx, message: str) -> None:
        """Called before intent classification.

        Plugins can inspect or modify ``ctx`` (AgentContext) before the
        router decides which agent to invoke.
        """

    @hookspec(firstresult=False)
    def on_post_routing(self, ctx, intent: str, confidence: float, agent_name: str) -> None:
        """Called after intent classification, before agent selection.

        Plugins can override the selected agent by modifying ``ctx``.
        """

    @hookspec(firstresult=False)
    def on_pre_agent(self, ctx, agent_name: str) -> None:
        """Called before the selected agent processes the message."""

    @hookspec(firstresult=False)
    def on_post_agent(self, ctx, agent_name: str, response: str) -> None:
        """Called after the agent generates a response."""

    @hookspec(firstresult=False)
    def on_pre_tool(self, ctx, tool_name: str, parameters: dict) -> None:
        """Called before a tool is executed in the ReAct loop."""

    @hookspec(firstresult=False)
    def on_post_tool(self, ctx, tool_name: str, result: str, success: bool, duration_ms: float) -> None:
        """Called after a tool completes execution."""

    @hookspec(firstresult=False)
    def on_post_process(self, ctx, response: str) -> None:
        """Called after post-processing (memory encoding, signal extraction)."""

    # ── Integration Hooks ──

    @hookspec
    def register_integrations(self) -> list:
        """Register external service integrations.

        Return a list of integration descriptors::

            @hookimpl
            def register_integrations(self):
                return [{
                    "name": "google_calendar",
                    "type": "oauth2",
                    "scopes": ["calendar.events"],
                }]
        """

    # ── Learning Event Hooks ──

    @hookspec(firstresult=False)
    def on_learning_event(self, event) -> None:
        """Called when a learning event is emitted (xAPI-inspired).

        The ``event`` is a ``LearningEventData`` dataclass
        (from ``services.analytics.events``) with fields:
        user_id, verb, object_type, object_id, score, success,
        completion, duration_seconds, result_json, course_id,
        agent_name, session_id, context_json, timestamp.

        Plugins can use this to sync with external analytics, trigger
        notifications, or update custom models.
        """

    # ── Startup / Shutdown ──

    @hookspec
    def on_startup(self) -> None:
        """Called during application startup, after all plugins are loaded."""

    @hookspec
    def on_shutdown(self) -> None:
        """Called during application shutdown."""
