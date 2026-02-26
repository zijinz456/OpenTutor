"""Scene recognition for context-aware preference resolution.

Detects what the user is doing (reviewing, studying, exam prep, etc.)
to select scene-specific preferences from the 7-layer cascade.

Reference: spec Section 3 — Unstructured fallback chain (regex → LLM).
Phase 1: Simple keyword regex. Phase 2: LLM classification.
"""

import re

# Scene patterns — ordered by specificity (most specific first)
SCENE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("exam_review", re.compile(
        r"(exam|test|midterm|final|quiz\s+prep|复习|考试|期末|期中)", re.IGNORECASE
    )),
    ("assignment", re.compile(
        r"(homework|assignment|problem\s+set|作业|题目|练习)", re.IGNORECASE
    )),
    ("reading", re.compile(
        r"(read|chapter|textbook|阅读|课本|教材|章节)", re.IGNORECASE
    )),
    ("lecture_review", re.compile(
        r"(lecture|slide|presentation|class\s+note|课件|讲义|幻灯片|PPT)", re.IGNORECASE
    )),
    ("problem_solving", re.compile(
        r"(solve|calculate|prove|derive|how\s+to|解题|计算|证明|推导)", re.IGNORECASE
    )),
    ("concept_learning", re.compile(
        r"(what\s+is|explain|define|concept|什么是|解释|概念|定义)", re.IGNORECASE
    )),
]

DEFAULT_SCENE = "general_study"


def detect_scene(message: str, course_name: str | None = None) -> str:
    """Detect the current study scene from user message.

    Phase 1: regex-based detection (~30 lines, spec estimate).
    Returns scene name string for preference cascade lookup.
    """
    text = f"{message} {course_name or ''}"

    for scene_name, pattern in SCENE_PATTERNS:
        if pattern.search(text):
            return scene_name

    return DEFAULT_SCENE
