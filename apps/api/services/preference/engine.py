"""Preference cascade resolver (Git Config pattern).

7-layer cascade: temporary → course_scene → course → global_scene → global → template → system_default.
Scene-scoped prefs (course_scene/global_scene) use UserPreference.scene_type to match the active scene.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.preference import UserPreference
from schemas.preference import ResolvedPreferences

# System defaults — baseline preferences when nothing is configured
SYSTEM_DEFAULTS: dict[str, str] = {
    "note_format": "bullet_point",
    "detail_level": "balanced",
    "language": "en",
    "layout_preset": "balanced",
    "explanation_style": "step_by_step",
    "quiz_difficulty": "adaptive",
    "visual_preference": "auto",
}

# Priority order: later scopes override earlier ones (Git Config pattern)
# Applied in order: system_default → template → global → global_scene → course → course_scene → temporary
# So 'temporary' has highest priority (last applied wins)
SCOPE_PRIORITY = [
    "template",
    "global",
    "global_scene",
    "course",
    "course_scene",
    "temporary",
]


async def resolve_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    scene: str | None = None,
) -> ResolvedPreferences:
    """Resolve all preferences using the 7-layer cascade.

    For each dimension, apply scopes in priority order.
    Last match wins (highest priority last).
    """
    # Layer 7: Start with system defaults
    resolved: dict[str, str] = dict(SYSTEM_DEFAULTS)
    sources: dict[str, str] = {k: "system_default" for k in SYSTEM_DEFAULTS}

    # Load all user preferences in one query
    query = select(UserPreference).where(UserPreference.user_id == user_id)
    result = await db.execute(query)
    all_prefs = result.scalars().all()

    # Group by scope
    by_scope: dict[str, list[UserPreference]] = {scope: [] for scope in SCOPE_PRIORITY}
    for pref in all_prefs:
        if pref.scope in by_scope:
            by_scope[pref.scope].append(pref)

    # Apply in priority order (template first → temporary last = highest priority)
    for scope in SCOPE_PRIORITY:
        for pref in by_scope[scope]:
            if pref.dismissed_at is not None:
                continue
            # Course-scoped prefs apply only when a matching course context exists.
            if scope in ("course", "course_scene"):
                if not course_id:
                    continue
                if pref.course_id != course_id:
                    continue

            # Scene-scoped prefs only apply if scene matches
            if scope in ("course_scene", "global_scene"):
                if not scene:
                    continue
                if pref.scene_type != scene:
                    continue

            resolved[pref.dimension] = pref.value
            sources[pref.dimension] = scope

    return ResolvedPreferences(preferences=resolved, sources=sources)


async def save_preference(
    db: AsyncSession,
    user_id: uuid.UUID,
    dimension: str,
    value: str,
    scope: str = "global",
    course_id: uuid.UUID | None = None,
    source: str = "behavior",
    confidence: float = 0.5,
    scene: str | None = None,
) -> UserPreference:
    """Save or update a preference at a specific scope level.

    Uses SELECT ... FOR UPDATE to prevent race conditions when concurrent
    requests try to save the same preference simultaneously.
    """
    # Check for existing preference at same scope + dimension + course + scene
    query = select(UserPreference).where(
        UserPreference.user_id == user_id,
        UserPreference.dimension == dimension,
        UserPreference.scope == scope,
    )
    if course_id:
        query = query.where(UserPreference.course_id == course_id)
    else:
        query = query.where(UserPreference.course_id.is_(None))
    if scene:
        query = query.where(UserPreference.scene_type == scene)
    else:
        query = query.where(UserPreference.scene_type.is_(None))

    # Use FOR UPDATE to prevent TOCTOU race condition
    query = query.with_for_update()

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = value
        existing.source = source
        existing.confidence = confidence
        return existing

    pref = UserPreference(
        user_id=user_id,
        course_id=course_id,
        scope=scope,
        dimension=dimension,
        value=value,
        source=source,
        confidence=confidence,
        scene_type=scene,
    )
    db.add(pref)
    return pref
