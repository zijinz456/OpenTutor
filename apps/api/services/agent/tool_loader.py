"""Scene-based tool loading for context-aware prompt optimization.

Borrows from:
- NanoBot: Progressive skill loading (always-loaded vs available)
- OpenClaw: Workspace-specific tool sets
- Spec Section 3: SceneContext with tab_type

Instead of injecting ALL NL tool definitions into every prompt,
load only the tools relevant to the current scene/tab. This saves ~30% system prompt tokens.
"""

import logging

logger = logging.getLogger(__name__)

# ── Tool Definitions by Scene ──

# Always-loaded tools (available in every scene)
CORE_TOOLS = """
## Quick Actions
- If the student seems confused, offer a simpler explanation
- If the student asks to change the display, use action markers
"""

# Layout tools (always available for UI control)
LAYOUT_TOOLS = """
## Layout Actions
Output action markers on their own line to control the interface.

Layout presets:
- [ACTION:set_layout_preset:balanced] — Equal panel sizes
- [ACTION:set_layout_preset:notesFocused] — Expand notes panel
- [ACTION:set_layout_preset:quizFocused] — Expand quiz panel
- [ACTION:set_layout_preset:chatFocused] — Expand chat panel
- [ACTION:set_layout_preset:fullNotes] — Maximize notes panel

Rules: Only output ONE action per response. Explain what changed.
"""

# Preference tools (only when preference changes are likely)
PREFERENCE_TOOLS = """
## Preference Actions
- [ACTION:set_preference:note_format:<value>] — bullet_point|table|mind_map|step_by_step|summary
- [ACTION:set_preference:detail_level:<value>] — concise|balanced|detailed
- [ACTION:set_preference:language:<value>] — en|zh|auto
- [ACTION:set_preference:explanation_style:<value>] — formal|conversational|socratic|example_heavy
"""

# Quiz tools (only in quiz/exercise scenes)
QUIZ_TOOLS = """
## Quiz Generation Guidelines
When generating quizzes:
- Number questions clearly (1, 2, 3...)
- For multiple choice, label options A/B/C/D
- Include difficulty level for each question
- Provide answer + explanation after each question
- Adapt difficulty to student's mastery level
"""

# Study plan tools (only in planning scenes)
PLAN_TOOLS = """
## Study Plan Guidelines
When creating study plans:
- Create day-by-day schedules
- Prioritize weak areas and upcoming deadlines
- Include review/spaced repetition sessions
- Be realistic about daily study capacity
- Output in clear markdown format with checkboxes
"""

# Error review tools (only in review scenes)
REVIEW_TOOLS = """
## Error Analysis Guidelines
When analyzing errors:
- Classify error type: conceptual / procedural / computational / reading / careless
- Explain the root cause
- Show correct approach step-by-step
- Suggest targeted practice
"""

# ── Scene → Tool Set Mapping ──

# v3 scene names aligned with scene system
SCENE_TOOL_MAP: dict[str, list[str]] = {
    # v3 canonical scene IDs
    "study_session": ["core", "layout", "quiz"],
    "exam_prep": ["core", "layout", "quiz", "review", "plan"],
    "assignment": ["core", "layout", "quiz"],
    "review_drill": ["core", "layout", "quiz", "review"],
    "note_organize": ["core", "layout"],
    # Legacy scene names (from detect_scene regex) — keep for backwards compatibility
    "general_study": ["core", "layout"],
    "concept_learning": ["core", "layout"],
    "problem_solving": ["core", "layout", "quiz"],
    "exam_review": ["core", "layout", "quiz", "review", "plan"],
    "reading": ["core", "layout"],
    "lecture_review": ["core", "layout"],
}

TOOL_REGISTRY: dict[str, str] = {
    "core": CORE_TOOLS,
    "layout": LAYOUT_TOOLS,
    "preference": PREFERENCE_TOOLS,
    "quiz": QUIZ_TOOLS,
    "plan": PLAN_TOOLS,
    "review": REVIEW_TOOLS,
}


def get_tools_for_scene(scene: str, include_preference: bool = False) -> str:
    """Get concatenated tool definitions for a given scene.

    Args:
        scene: Current study scene (from detect_scene)
        include_preference: Whether to include preference tools
                           (only when intent is PREFERENCE or LAYOUT)

    Returns:
        Concatenated tool prompt string
    """
    tool_keys = SCENE_TOOL_MAP.get(scene, ["core", "layout"])

    if include_preference and "preference" not in tool_keys:
        tool_keys = tool_keys + ["preference"]

    parts = []
    for key in tool_keys:
        tool_prompt = TOOL_REGISTRY.get(key, "")
        if tool_prompt:
            parts.append(tool_prompt)

    return "\n".join(parts)
