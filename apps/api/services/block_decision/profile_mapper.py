"""Map LearnerProfile to SpaceLayout.

Deterministic, rule-based mapping. No LLM needed.
Adapted from GenMentor's skill-gap -> learning-path scheduling pattern.
"""

from __future__ import annotations

from schemas.learner_profile import LearnerProfile

# (profile_field, block_type, size, config, priority)
# Lower priority = placed first in layout.
PROFILE_BLOCK_RULES: list[tuple[str, str, str, dict, int]] = [
    ("preferences.prefers_note_taking",      "notes",           "large",  {},                        10),
    ("preferences.prefers_visual_aids",      "knowledge_graph", "large",  {"mode": "interactive"},   20),
    ("preferences.prefers_active_recall",    "quiz",            "medium", {"difficulty": "adaptive"}, 30),
    ("preferences.prefers_active_recall",    "flashcards",      "medium", {},                        40),
    ("preferences.prefers_mistake_analysis", "wrong_answers",   "medium", {},                        50),
    ("preferences.prefers_spaced_review",    "review",          "medium", {},                        60),
    ("preferences.prefers_spaced_review",    "forecast",        "small",  {},                        70),
    ("preferences.prefers_planning",         "plan",            "medium", {},                        80),
]

CONTENT_STYLE_CONFIG: dict[str, dict] = {
    "step_by_step": {"note_format": "step_by_step"},
    "summary":      {"note_format": "summary"},
    "mind_map":     {"note_format": "mind_map"},
    "mixed":        {},
}

DURATION_CONSTRAINTS: dict[str, dict] = {
    "short":  {"max_blocks": 4, "columns": 2},
    "medium": {"max_blocks": 6, "columns": 2},
    "long":   {"max_blocks": 8, "columns": 3},
}

PATTERN_MODE_MAP: dict[str, str] = {
    "structured":     "course_following",
    "exploratory":    "self_paced",
    "exam_driven":    "exam_prep",
    "review_focused": "maintenance",
}


def _resolve_field(profile: LearnerProfile, dotted_path: str) -> bool:
    """Resolve a dotted field path like 'preferences.prefers_visual_aids'."""
    obj: object = profile
    for part in dotted_path.split("."):
        obj = getattr(obj, part, False)
    return bool(obj)


def profile_to_layout(profile: LearnerProfile) -> dict:
    """Convert a LearnerProfile to a SpaceLayout dict.

    1. Always include chapter_list
    2. Activate blocks whose profile condition is True
    3. Apply content_style config to notes block
    4. Apply session_duration constraints
    5. Always include progress block at the end
    6. Map study_pattern to learning mode
    """
    blocks: list[dict] = [
        {
            "type": "chapter_list",
            "size": "medium",
            "config": {},
            "position": 0,
            "visible": True,
            "source": "onboarding",
        },
    ]

    # Collect activated blocks sorted by priority
    activated: list[tuple[int, str, str, dict]] = []
    for field_path, block_type, size, config, priority in PROFILE_BLOCK_RULES:
        if _resolve_field(profile, field_path):
            activated.append((priority, block_type, size, config))
    activated.sort(key=lambda x: x[0])

    for _prio, block_type, size, config in activated:
        blocks.append({
            "type": block_type,
            "size": size,
            "config": dict(config),
            "position": len(blocks),
            "visible": True,
            "source": "onboarding",
        })

    # Apply content_style override to notes block
    style_config = CONTENT_STYLE_CONFIG.get(profile.preferences.content_style, {})
    if style_config:
        for block in blocks:
            if block["type"] == "notes":
                block["config"].update(style_config)
                break

    # Apply duration constraints
    constraints = DURATION_CONSTRAINTS[profile.behavior.session_duration]
    max_blocks = constraints["max_blocks"]
    columns: int = constraints["columns"]

    # Reserve 1 slot for progress
    if len(blocks) > max_blocks - 1:
        blocks = blocks[: max_blocks - 1]

    # Always add progress
    blocks.append({
        "type": "progress",
        "size": "small",
        "config": {},
        "position": len(blocks),
        "visible": True,
        "source": "onboarding",
    })

    # Renumber positions
    for i, block in enumerate(blocks):
        block["position"] = i

    mode = PATTERN_MODE_MAP.get(profile.behavior.study_pattern, "self_paced")

    return {
        "templateId": "ai_personalized",
        "blocks": blocks,
        "columns": columns,
        "mode": mode,
    }
