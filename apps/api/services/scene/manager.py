"""Scene manager — handles scene switching with 6-step logic.

switchScene flow:
1. Save current scene UI state snapshot → scene_snapshots
2. Load target scene config (historical snapshot or template default)
3. Compute Tab layout changes
4. Update course.active_scene
5. First-time scene initialization (e.g., exam_prep → generate review plan)
6. Log switch event → scene_switch_log
"""

import uuid
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scene import Scene, SceneSnapshot, SceneSwitchLog
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)


def _resolve_tab_layout(scene_config: dict[str, Any], snapshot: dict[str, Any] | None) -> list[dict]:
    """Restore tab layout from snapshot when possible, otherwise use scene defaults."""
    if snapshot:
        open_tabs = snapshot.get("open_tabs")
        if isinstance(open_tabs, list) and open_tabs:
            return open_tabs

    tab_preset = scene_config.get("tab_preset", [])
    return tab_preset if isinstance(tab_preset, list) else []


def _build_scene_switch_explanation(
    *,
    old_scene_id: str,
    new_scene_id: str,
    trigger_type: str,
    trigger_context: str | None,
    scene_config: dict[str, Any],
) -> dict[str, Any]:
    display_name = scene_config.get("display_name") or new_scene_id
    workflow = scene_config.get("workflow") or "custom"
    tab_types = [tab.get("type") for tab in scene_config.get("tab_preset", []) if isinstance(tab, dict)]
    if trigger_type == "ai_suggested":
        reason = f"Switched from {old_scene_id} to {display_name} because the assistant detected a better study mode."
    elif trigger_type == "auto":
        reason = f"Automatically switched into {display_name} to align the workspace with the current workflow."
    else:
        reason = f"Switched from {old_scene_id} to {display_name}."
    if trigger_context:
        reason = f"{reason} Trigger: {trigger_context}"
    return {
        "workflow": workflow,
        "recommended_tabs": tab_types,
        "reason": reason,
    }


async def switch_scene(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    new_scene_id: str,
    trigger_type: str = "manual",
    trigger_context: str | None = None,
    current_ui_state: dict | None = None,
) -> dict[str, Any]:
    """Execute the 6-step scene switch.

    Returns dict with new scene config, tab layout, and any initialization actions.
    """
    # Get current course state
    course = await get_course_or_404(db, course_id, user_id=user_id)

    old_scene_id = course.active_scene or "study_session"

    if old_scene_id == new_scene_id:
        # Already in target scene — return current config
        scene_config = await get_scene_config(db, new_scene_id)
        return {
            "switched": False,
            "scene_id": new_scene_id,
            "config": scene_config,
            "message": f"Already in {new_scene_id} scene",
        }

    # Step 1: Save current scene UI state snapshot
    if current_ui_state:
        await save_snapshot(db, course_id, old_scene_id, current_ui_state)

    # Step 2: Load target scene config
    scene_config = await get_scene_config(db, new_scene_id)

    # Step 3: Load historical snapshot or use scene defaults
    snapshot = await load_snapshot(db, course_id, new_scene_id)
    tab_layout = _resolve_tab_layout(scene_config, snapshot)

    # Step 4: Update course.active_scene
    course.active_scene = new_scene_id

    # Step 5: First-time initialization actions
    init_actions = await get_init_actions(db, course_id, user_id, new_scene_id)

    # Step 6: Log the switch
    log_entry = SceneSwitchLog(
        course_id=course_id,
        user_id=user_id,
        from_scene=old_scene_id,
        to_scene=new_scene_id,
        trigger_type=trigger_type,
        trigger_context=trigger_context,
    )
    db.add(log_entry)
    await db.flush()

    return {
        "switched": True,
        "scene_id": new_scene_id,
        "from_scene": old_scene_id,
        "config": scene_config,
        "tab_layout": tab_layout,
        "init_actions": init_actions,
        "explanation": _build_scene_switch_explanation(
            old_scene_id=old_scene_id,
            new_scene_id=new_scene_id,
            trigger_type=trigger_type,
            trigger_context=trigger_context,
            scene_config=scene_config,
        ),
    }


async def get_scene_config(db: AsyncSession, scene_id: str) -> dict[str, Any]:
    """Load scene configuration from DB or return defaults."""
    result = await db.execute(select(Scene).where(Scene.scene_id == scene_id))
    scene = result.scalar_one_or_none()

    if scene:
        return {
            "scene_id": scene.scene_id,
            "display_name": scene.display_name,
            "icon": scene.icon,
            "tab_preset": scene.tab_preset,
            "workflow": scene.workflow,
            "ai_behavior": scene.ai_behavior,
            "preferences": scene.preferences,
        }

    # Fallback to hardcoded defaults for unknown scenes
    return SCENE_DEFAULTS.get(scene_id, SCENE_DEFAULTS["study_session"])


async def save_snapshot(
    db: AsyncSession,
    course_id: uuid.UUID,
    scene_id: str,
    ui_state: dict,
) -> None:
    """Save or update a scene UI state snapshot."""
    result = await db.execute(
        select(SceneSnapshot).where(
            SceneSnapshot.course_id == course_id,
            SceneSnapshot.scene_id == scene_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.open_tabs = ui_state.get("open_tabs", existing.open_tabs)
        existing.layout_state = ui_state.get("layout_state", existing.layout_state)
        existing.scroll_positions = ui_state.get("scroll_positions")
        existing.last_active_tab = ui_state.get("last_active_tab")
    else:
        snapshot = SceneSnapshot(
            course_id=course_id,
            scene_id=scene_id,
            open_tabs=ui_state.get("open_tabs", []),
            layout_state=ui_state.get("layout_state", {}),
            scroll_positions=ui_state.get("scroll_positions"),
            last_active_tab=ui_state.get("last_active_tab"),
        )
        db.add(snapshot)

    await db.flush()


async def load_snapshot(
    db: AsyncSession,
    course_id: uuid.UUID,
    scene_id: str,
) -> dict | None:
    """Load a previous scene UI state snapshot, if one exists."""
    result = await db.execute(
        select(SceneSnapshot).where(
            SceneSnapshot.course_id == course_id,
            SceneSnapshot.scene_id == scene_id,
        )
    )
    snapshot = result.scalar_one_or_none()

    if not snapshot:
        return None

    return {
        "open_tabs": snapshot.open_tabs,
        "layout_state": snapshot.layout_state,
        "scroll_positions": snapshot.scroll_positions,
        "last_active_tab": snapshot.last_active_tab,
    }


async def get_init_actions(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    scene_id: str,
) -> list[dict]:
    """Generate initialization actions for first-time scene entry."""
    actions = []

    if scene_id == "exam_prep":
        # Check if user already has a study plan for this course
        from models.study_plan import StudyPlan
        result = await db.execute(
            select(StudyPlan).where(
                StudyPlan.course_id == course_id,
                StudyPlan.user_id == user_id,
                StudyPlan.scene_id == "exam_prep",
            ).limit(1)
        )
        if not result.scalar_one_or_none():
            actions.append({
                "type": "suggest",
                "action": "generate_study_plan",
                "message": "Would you like me to create an exam review plan based on your progress?",
            })

    elif scene_id == "review_drill":
        # Check if there are wrong answers to review
        from models.ingestion import WrongAnswer
        result = await db.execute(
            select(WrongAnswer).where(
                WrongAnswer.course_id == course_id,
                WrongAnswer.user_id == user_id,
                WrongAnswer.mastered.is_(False),
            ).limit(1)
        )
        if result.scalar_one_or_none():
            actions.append({
                "type": "auto",
                "action": "load_wrong_answers",
                "message": "Loading your unmastered wrong answers for review.",
            })

    return actions


# Hardcoded defaults matching the 5 preset scenes
SCENE_DEFAULTS: dict[str, dict] = {
    "study_session": {
        "scene_id": "study_session",
        "display_name": "Daily Study",
        "icon": "📚",
        "tab_preset": [
            {"type": "notes", "position": 0},
            {"type": "quiz", "position": 1},
            {"type": "chat", "position": 2},
        ],
        "workflow": "study",
        "ai_behavior": {"style": "thorough", "encourage_exploration": True},
        "preferences": None,
    },
    "exam_prep": {
        "scene_id": "exam_prep",
        "display_name": "Exam Prep",
        "icon": "🎯",
        "tab_preset": [
            {"type": "plan", "position": 0},
            {"type": "quiz", "position": 1},
            {"type": "review", "position": 2},
            {"type": "chat", "position": 3},
        ],
        "workflow": "exam",
        "ai_behavior": {"style": "concise", "focus": "weak_points", "quiz_priority": "high_freq"},
        "preferences": {"detail_level": "concise", "note_format": "bullet_point"},
    },
    "assignment": {
        "scene_id": "assignment",
        "display_name": "Homework",
        "icon": "✍️",
        "tab_preset": [
            {"type": "notes", "position": 0},
            {"type": "chat", "position": 1},
        ],
        "workflow": "assignment",
        "ai_behavior": {"style": "guided", "no_direct_answers": True, "progressive_hints": True},
        "preferences": {"explanation_style": "socratic"},
    },
    "review_drill": {
        "scene_id": "review_drill",
        "display_name": "Error Review",
        "icon": "🔄",
        "tab_preset": [
            {"type": "review", "position": 0},
            {"type": "quiz", "position": 1},
            {"type": "chat", "position": 2},
        ],
        "workflow": "review",
        "ai_behavior": {"style": "analytical", "error_classification": True, "derive_similar": True},
        "preferences": None,
    },
    "note_organize": {
        "scene_id": "note_organize",
        "display_name": "Notes",
        "icon": "📝",
        "tab_preset": [
            {"type": "notes", "position": 0},
            {"type": "chat", "position": 1},
        ],
        "workflow": "notes",
        "ai_behavior": {"style": "structural", "cross_chapter": True},
        "preferences": {"note_format": "mind_map"},
    },
}
