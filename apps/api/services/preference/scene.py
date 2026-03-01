"""Scene recognition for context-aware preference resolution.

Detects what the user is doing (reviewing, studying, exam prep, etc.)
to select scene-specific preferences from the 7-layer cascade.

v3 canonical scene IDs: study_session, exam_prep, assignment, review_drill, note_organize.

Reference: spec Section 3 — Unstructured fallback chain (regex → LLM).
Phase 1: Simple keyword regex. Phase 2: LLM classification.
"""

import re

from services.agent.state import SceneName

# v3 Scene patterns — ordered by specificity (most specific first)
# Maps to canonical v3 scene IDs used by scene_behavior.py and tool_loader.py
SCENE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (SceneName.EXAM_PREP, re.compile(
        r"(exam|test|midterm|final|quiz\s+prep|review\s+for|prepare\s+for|cram|last[-\s]?minute)", re.IGNORECASE
    )),
    (SceneName.REVIEW_DRILL, re.compile(
        r"(wrong\s+answer|mistake|review\s+mistake|error\s+cause|error\s+analysis|correct\s+error)", re.IGNORECASE
    )),
    (SceneName.ASSIGNMENT, re.compile(
        r"(homework|assignment|problem\s+set|exercise|question|practice\s+problem)", re.IGNORECASE
    )),
    (SceneName.NOTE_ORGANIZE, re.compile(
        r"(organize\s+(my\s+)?notes|note\s+organization|note\s+summary|summarize\s+(my\s+)?notes|compile\s+notes)",
        re.IGNORECASE,
    )),
    (SceneName.STUDY_SESSION, re.compile(
        r"(read|chapter|textbook|reading|coursebook|material|section|lecture|slide|courseware|handout|"
        r"what\s+is|explain|define|concept|definition|"
        r"solve|calculate|prove|derive|how\s+to)", re.IGNORECASE
    )),
]

DEFAULT_SCENE = SceneName.STUDY_SESSION


def explain_scene_detection(message: str, course_name: str | None = None) -> dict:
    """Fallback regex-based scene explanation used when policy context is unavailable."""
    text = f"{message} {course_name or ''}"

    for scene_name, pattern in SCENE_PATTERNS:
        match = pattern.search(text)
        if match:
            return {
                "scene": scene_name,
                "mode": "inferred",
                "matched_text": match.group(0),
                "reason": f"Matched study-mode cue '{match.group(0)}'.",
            }

    return {
        "scene": DEFAULT_SCENE,
        "mode": "default",
        "matched_text": None,
        "reason": "No explicit study-mode cue detected; using the default study session scene.",
    }


def detect_scene(message: str, course_name: str | None = None) -> str:
    """Detect the current study scene from user message.

    Phase 1: regex-based detection.
    Returns v3 canonical scene ID for preference cascade + scene behavior injection.
    """
    return explain_scene_detection(message, course_name)["scene"]
