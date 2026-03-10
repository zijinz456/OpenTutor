"""Preference CRUD and local runtime configuration endpoints.

The implementation has been split into focused modules:
- preferences_crud.py:    preference CRUD, profile, signals listing, resolve
- preferences_signals.py: signal dismiss/restore, memory CRUD
- preferences_llm.py:     LLM runtime config, Ollama models, NL parsing

This file composes the sub-routers into one ``router`` so that
``services/router_registry.py`` continues to work unchanged.
"""

from fastapi import APIRouter

from routers.preferences_crud import router as crud_router
from routers.preferences_signals import router as signals_router
from routers.preferences_llm import router as llm_router

router = APIRouter()
router.include_router(crud_router)
router.include_router(signals_router)
router.include_router(llm_router)
