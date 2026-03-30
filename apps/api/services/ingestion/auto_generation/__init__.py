"""Auto-generation functions extracted from pipeline.py.

Handles post-ingestion content generation:
- AI title summarization
- Notes, flashcards, quiz auto-generation
- Course auto-configuration (layout + welcome message)
- Learning content generation (practice problems)

This package re-exports all public symbols so that existing imports
of the form ``from services.ingestion.auto_generation import X`` continue
to work unchanged.
"""

from services.ingestion.auto_generation.titles import auto_summarize_titles
from services.ingestion.auto_generation.notes import auto_generate_notes
from services.ingestion.auto_generation.practice import (
    auto_generate_flashcards,
    auto_generate_quiz,
    _auto_generate_learning_content,
)
from services.ingestion.auto_generation.configure import (
    auto_configure_course,
)
from services.ingestion.auto_generation.orchestrator import auto_prepare

__all__ = [
    "auto_summarize_titles",
    "auto_generate_notes",
    "auto_generate_flashcards",
    "auto_generate_quiz",
    "auto_prepare",
    "auto_configure_course",
    "_auto_generate_learning_content",
]
