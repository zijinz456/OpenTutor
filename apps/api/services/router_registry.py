"""Application router registration."""

from __future__ import annotations

from fastapi import FastAPI

from config import settings
from routers import (
    agenda,
    auth,
    block_routes,
    canvas,
    chat,
    courses,
    export,
    flashcards,
    goals,
    health,
    notes,
    notifications,
    onboarding,
    preferences,
    progress,
    quiz,
    scrape,
    tasks,
    upload,
    usage,
    workflows,
    wrong_answers,
)


CORE_ROUTERS = (
    (health.router, "/api", ["health"]),
    (upload.router, "/api/content", ["content"]),
    (chat.router, "/api/chat", ["chat"]),
    (courses.router, "/api/courses", ["courses"]),
    (preferences.router, "/api/preferences", ["preferences"]),
    (quiz.router, "/api/quiz", ["quiz"]),
    (notes.router, "/api/notes", ["notes"]),
    (progress.router, "/api/progress", ["progress"]),
    (flashcards.router, "/api/flashcards", ["flashcards"]),
    (canvas.router, "/api/canvas", ["canvas"]),
    (scrape.router, "/api/scrape", ["scrape"]),
    (wrong_answers.router, "/api/wrong-answers", ["wrong-answers"]),
    (tasks.router, "/api/tasks", ["tasks"]),
    (goals.router, "/api/goals", ["goals"]),
    (agenda.router, "/api/agent", ["agenda"]),
    (usage.router, None, None),
    (export.router, "/api", ["export"]),
    (notifications.router, "/api", ["notifications"]),
    (workflows.router, "/api/workflows", ["workflows"]),
    (block_routes.router, "/api/blocks", ["blocks"]),
    (onboarding.router, "/api/onboarding", ["onboarding"]),
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

    # Built-in lightweight UI for CLI mode (no Node.js required).
    # Disabled when the full Next.js frontend handles the UI.
    import os

    if os.environ.get("SERVE_BUILTIN_UI", "false") != "false":
        from routers.ui import router as ui_router

        _include_router(app, ui_router, tags=["ui"])
