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

Supported actions (PRD v1):
- [ACTION:add_block:flashcards:medium] — Add a block
- [ACTION:remove_block:quiz] — Remove a block by type
- [ACTION:reorder_blocks:quiz,notes,progress] — Reorder blocks by priority
- [ACTION:resize_block:notes:large] — Resize a block
- [ACTION:apply_template:quick_reviewer] — Apply a workspace template
- [ACTION:agent_insight:review_needed:3 concepts are fading] — Add agent insight block
- [ACTION:data_updated:notes] — Notify frontend data refresh
- [ACTION:focus_topic:<nodeId>] — Focus a specific concept/unit

Rules:
- Put each action marker on its own line.
- When both explanation and layout changes are needed, explain first, then output action markers.
- Multiple actions are allowed when the user asks for combined operations.
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


def get_all_tools(include_preference: bool = False) -> str:
    """Get concatenated tool definitions for all tool categories.

    Args:
        include_preference: Whether to include preference tools
                           (only when intent is PREFERENCE or LAYOUT)

    Returns:
        Concatenated tool prompt string
    """
    parts = []
    for key, tool_prompt in TOOL_REGISTRY.items():
        if key == "preference" and not include_preference:
            continue
        if tool_prompt:
            parts.append(tool_prompt)

    return "\n".join(parts)


def get_scene_tools(scene: str, include_preference: bool = False) -> str:
    """Get tool definitions filtered by the current scene.

    Only loads tools relevant to the scene, saving ~30% prompt tokens
    compared to get_all_tools().

    Falls back to core + layout if scene is unknown.
    """
    tool_keys = SCENE_TOOL_MAP.get(scene, ["core", "layout"])
    if include_preference and "preference" not in tool_keys:
        tool_keys = list(tool_keys) + ["preference"]

    parts = []
    for key in tool_keys:
        tool_prompt = TOOL_REGISTRY.get(key, "")
        if tool_prompt:
            parts.append(tool_prompt)

    return "\n".join(parts)
