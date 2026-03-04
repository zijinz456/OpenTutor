"""Application router registration."""

from __future__ import annotations

from fastapi import FastAPI

from config import settings
from routers import (
    agenda,
    auth,
    canvas,
    chat,
    courses,
    evaluation,
    experiments,
    export,
    flashcards,
    goals,
    health,
    integrations,
    learning_events,
    notes,
    notification_settings,
    notifications,
    podcast,
    preferences,
    progress,
    push,
    quiz,
    reports,
    scrape,
    tasks,
    upload,
    usage,
    voice,
    workflows,
    workspace,
    wrong_answers,
)
from routers.mcp import router as mcp_router


CORE_ROUTERS = (
    (health.router, "/api", ["health"]),
    (upload.router, "/api/content", ["content"]),
    (chat.router, "/api/chat", ["chat"]),
    (courses.router, "/api/courses", ["courses"]),
    (preferences.router, "/api/preferences", ["preferences"]),
    (quiz.router, "/api/quiz", ["quiz"]),
    (notes.router, "/api/notes", ["notes"]),
    (workflows.router, "/api/workflows", ["workflows"]),
    (progress.router, "/api/progress", ["progress"]),
    (flashcards.router, "/api/flashcards", ["flashcards"]),
    (canvas.router, "/api/canvas", ["canvas"]),
    (notifications.router, "/api/notifications", ["notifications"]),
    (scrape.router, "/api/scrape", ["scrape"]),
    (wrong_answers.router, "/api/wrong-answers", ["wrong-answers"]),
    (tasks.router, "/api/tasks", ["tasks"]),
    (goals.router, "/api/goals", ["goals"]),
    (agenda.router, "/api/agent", ["agenda"]),
    (evaluation.router, "/api/eval", ["evaluation"]),
    (experiments.router, "/api/experiments", ["experiments"]),
    (push.router, "/api/notifications/push", ["notifications"]),
    (notification_settings.router, "/api/notifications", ["notifications"]),
    (reports.router, "/api/reports", ["reports"]),
    (usage.router, None, None),
    (export.router, "/api", ["export"]),
    (learning_events.router, "/api/learning-events", ["learning-events"]),
    (voice.router, "/api/voice", ["voice"]),
    (podcast.router, "/api/podcast", ["podcast"]),
    (workspace.router, "/api", ["workspace"]),
    (integrations.router, "/api", ["integrations"]),
    (mcp_router, "/api", None),
)


def _include_router(app: FastAPI, router, prefix: str | None = None, tags: list[str] | None = None) -> None:
    kwargs = {}
    if prefix is not None:
        kwargs["prefix"] = prefix
    if tags is not None:
        kwargs["tags"] = tags
    app.include_router(router, **kwargs)


def register_routers(app: FastAPI) -> None:
    if settings.auth_enabled:
        _include_router(app, auth.router, prefix="/api/auth", tags=["auth"])

    for router, prefix, tags in CORE_ROUTERS:
        _include_router(app, router, prefix=prefix, tags=tags)

    if settings.enabled_channels:
        from routers import webhooks

        _include_router(app, webhooks.router, prefix="/api/webhooks", tags=["webhooks"])

    # Built-in lightweight UI for CLI mode (no Node.js required).
    # Disabled when the full Next.js frontend handles the UI.
    import os

    if os.environ.get("SERVE_BUILTIN_UI", "true") != "false":
        from routers.ui import router as ui_router

        _include_router(app, ui_router, tags=["ui"])
