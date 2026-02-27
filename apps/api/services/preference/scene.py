"""Scene recognition for context-aware preference resolution.

Detects what the user is doing (reviewing, studying, exam prep, etc.)
to select scene-specific preferences from the 7-layer cascade.

v3 canonical scene IDs: study_session, exam_prep, assignment, review_drill, note_organize.

Reference: spec Section 3 — Unstructured fallback chain (regex → LLM).
Phase 1: Simple keyword regex. Phase 2: LLM classification.
"""

import re

# v3 Scene patterns — ordered by specificity (most specific first)
# Maps to canonical v3 scene IDs used by scene_behavior.py and tool_loader.py
SCENE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("exam_prep", re.compile(
        r"(exam|test|midterm|final|quiz\s+prep|复习|考试|期末|期中|考前|冲刺)", re.IGNORECASE
    )),
    ("review_drill", re.compile(
        r"(错题|wrong\s+answer|mistake|review\s+mistake|错因|error\s+analysis|纠错)", re.IGNORECASE
    )),
    ("assignment", re.compile(
        r"(homework|assignment|problem\s+set|作业|题目|练习)", re.IGNORECASE
    )),
    ("note_organize", re.compile(
        r"(organize\s+notes|整理笔记|笔记整理|note\s+summary|归纳|总结笔记)", re.IGNORECASE
    )),
    ("study_session", re.compile(
        r"(read|chapter|textbook|阅读|课本|教材|章节|lecture|slide|课件|讲义|"
        r"what\s+is|explain|define|concept|什么是|解释|概念|定义|"
        r"solve|calculate|prove|derive|how\s+to|解题|计算|证明|推导)", re.IGNORECASE
    )),
]

DEFAULT_SCENE = "study_session"


def detect_scene(message: str, course_name: str | None = None) -> str:
    """Detect the current study scene from user message.

    Phase 1: regex-based detection.
    Returns v3 canonical scene ID for preference cascade + scene behavior injection.
    """
    text = f"{message} {course_name or ''}"

    for scene_name, pattern in SCENE_PATTERNS:
        if pattern.search(text):
            return scene_name

    return DEFAULT_SCENE
