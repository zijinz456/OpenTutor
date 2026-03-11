"""Learner profile schema extracted during onboarding interview.

Adapted from GenMentor's LearnerProfile (github.com/GeminiLight/gen-mentor)
with OpenTutor block-system mappings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class LearningPreferences(BaseModel):
    """Content format and activity preferences — maps to BlockType decisions.

    Adapted from GenMentor's LearningPreferences schema.
    """

    prefers_visual_aids: bool = False       # -> knowledge_graph block
    prefers_note_taking: bool = False       # -> notes block (large)
    prefers_active_recall: bool = False     # -> quiz + flashcards blocks
    prefers_spaced_review: bool = False     # -> review + forecast blocks
    prefers_mistake_analysis: bool = False  # -> wrong_answers block
    prefers_planning: bool = False          # -> plan block

    content_style: Literal[
        "step_by_step",  # Detailed walkthroughs
        "summary",       # Condensed overviews
        "mind_map",      # Visual/spatial organization
        "mixed",         # No strong preference
    ] = "mixed"


class BehavioralPatterns(BaseModel):
    """How the learner studies — influences layout density and pacing.

    Adapted from GenMentor's BehavioralPatterns schema.
    """

    session_duration: Literal["short", "medium", "long"] = "medium"
    # short: <30min -> 3-4 blocks, 2 columns
    # medium: 30-60min -> 5-6 blocks, 2 columns
    # long: >60min -> 6-8 blocks, 3 columns

    study_pattern: Literal[
        "structured",      # Step-by-step, plan-driven
        "exploratory",     # Free-form, curiosity-driven
        "exam_driven",     # Practice-heavy, deadline-focused
        "review_focused",  # Spaced repetition, consolidation
    ] = "structured"

    learning_style: Literal[
        "visual",       # Diagrams, graphs, mind maps
        "reading",      # Text-heavy, note-taking
        "kinesthetic",  # Hands-on, practice-first
        "mixed",        # No dominant style
    ] = "mixed"


class LearnerProfile(BaseModel):
    """Complete learner profile extracted from onboarding interview.

    Flat boolean preferences for direct block mapping (no indirection).
    GenMentor-style behavioral dimensions for layout decisions.
    Raw description preserved for memory pipeline (natural language).
    """

    preferences: LearningPreferences = Field(default_factory=LearningPreferences)
    behavior: BehavioralPatterns = Field(default_factory=BehavioralPatterns)

    raw_description: str = ""
    confidence: float = Field(0.5, ge=0, le=1)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    learning_goal: str | None = None
    background_level: Literal[
        "beginner", "intermediate", "advanced", "unknown"
    ] = "unknown"
