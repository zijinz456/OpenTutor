"""3-layer preference cascade resolver (Git Config pattern).

MVP layers: temporary → course → global → default.
Full 7-layer (+ course_scene, global_scene, template) deferred to Phase 1.

Reference: Git Config 5-layer model (system→global→local→worktree→CLI),
more specific scope overrides more general.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.preference import UserPreference
from schemas.preference import ResolvedPreferences

# System defaults — baseline preferences when nothing is configured
SYSTEM_DEFAULTS: dict[str, str] = {
    "note_format": "bullet_point",
    "detail_level": "moderate",
    "language": "en",
    "layout_preset": "balanced",
    "explanation_style": "step_by_step",
    "quiz_difficulty": "adaptive",
    "visual_preference": "auto",
}

# Priority order: later scopes override earlier ones (Git Config pattern)
SCOPE_PRIORITY = ["global", "course", "temporary"]


async def resolve_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> ResolvedPreferences:
    """Resolve all preferences using the cascade.

    For each dimension, check scopes in priority order (temporary → course → global).
    First match wins (highest priority first).

    ~30 lines of core logic, following Git Config pattern.
    """
    # Start with system defaults
    resolved: dict[str, str] = dict(SYSTEM_DEFAULTS)
    sources: dict[str, str] = {k: "default" for k in SYSTEM_DEFAULTS}

    # Load all user preferences in one query
    query = select(UserPreference).where(UserPreference.user_id == user_id)
    result = await db.execute(query)
    all_prefs = result.scalars().all()

    # Group by scope
    by_scope: dict[str, list[UserPreference]] = {scope: [] for scope in SCOPE_PRIORITY}
    for pref in all_prefs:
        if pref.scope in by_scope:
            by_scope[pref.scope].append(pref)

    # Apply in priority order (global first, then course overrides, then temporary overrides)
    for scope in SCOPE_PRIORITY:
        for pref in by_scope[scope]:
            # Course-scoped prefs only apply if course matches
            if scope == "course" and course_id and pref.course_id != course_id:
                continue
            resolved[pref.dimension] = pref.value
            sources[pref.dimension] = scope

    return ResolvedPreferences(preferences=resolved, sources=sources)
