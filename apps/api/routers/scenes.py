"""Scene management API — v3 scene system.

Endpoints for listing scenes, getting active scene, switching scenes, and creating custom scenes.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.scene import Scene
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.scene.manager import switch_scene, get_scene_config, load_snapshot
from libs.exceptions import ConflictError, NotFoundError

router = APIRouter()


# ── Schemas ──

class SceneResponse(BaseModel):
    scene_id: str
    display_name: str
    icon: str | None
    is_preset: bool
    tab_preset: list[dict]
    workflow: str

    model_config = {"from_attributes": True}


class ActiveSceneResponse(BaseModel):
    scene_id: str
    config: dict
    snapshot: dict | None


class SceneRecommendationResponse(BaseModel):
    scene_id: str
    confidence: float
    switch_recommended: bool
    reason: str
    scores: dict[str, float]
    features: dict


class SwitchSceneRequest(BaseModel):
    scene_id: str
    trigger_type: str = "manual"        # manual | ai_suggested | auto
    trigger_context: str | None = None
    current_ui_state: dict | None = None  # Snapshot of current scene's UI state


class SwitchSceneResponse(BaseModel):
    switched: bool
    scene_id: str
    from_scene: str | None = None
    config: dict
    tab_layout: list[dict] | None = None
    init_actions: list[dict] = []
    message: str | None = None
    explanation: dict | None = None


class CreateSceneRequest(BaseModel):
    scene_id: str
    display_name: str
    icon: str | None = None
    tab_preset: list[dict]
    workflow: str = "custom"
    ai_behavior: dict = {}
    preferences: dict | None = None


# ── Endpoints ──

@router.get("/", response_model=list[SceneResponse])
async def list_scenes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all available scenes (preset + user-created)."""
    result = await db.execute(select(Scene).order_by(Scene.is_preset.desc(), Scene.scene_id))
    scenes = result.scalars().all()

    # If no scenes in DB yet, return defaults from manager
    if not scenes:
        from services.scene.manager import SCENE_DEFAULTS
        return [
            SceneResponse(
                scene_id=s["scene_id"],
                display_name=s["display_name"],
                icon=s["icon"],
                is_preset=True,
                tab_preset=s["tab_preset"],
                workflow=s["workflow"],
            )
            for s in SCENE_DEFAULTS.values()
        ]

    return scenes


@router.get("/{course_id}/active", response_model=ActiveSceneResponse)
async def get_active_scene(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the active scene and its snapshot for a course."""
    course = await get_course_or_404(db, course_id, user_id=user.id)

    scene_id = course.active_scene or "study_session"
    config = await get_scene_config(db, scene_id)
    snapshot = await load_snapshot(db, course_id, scene_id)

    return ActiveSceneResponse(scene_id=scene_id, config=config, snapshot=snapshot)


@router.get("/{course_id}/recommend", response_model=SceneRecommendationResponse)
async def recommend_scene(
    course_id: uuid.UUID,
    message: str,
    active_tab: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recommend the best scene for a message via the scene policy engine."""
    course = await get_course_or_404(db, course_id, user_id=user.id)
    from services.scene.policy import resolve_scene_policy

    decision = await resolve_scene_policy(
        db,
        user_id=user.id,
        course_id=course_id,
        message=message,
        current_scene=course.active_scene or "study_session",
        active_tab=active_tab,
    )
    return SceneRecommendationResponse(
        scene_id=decision.scene_id,
        confidence=round(decision.confidence, 3),
        switch_recommended=decision.switch_recommended,
        reason=decision.reason,
        scores=decision.scores,
        features=decision.features,
    )


@router.post("/{course_id}/switch", response_model=SwitchSceneResponse)
async def switch_scene_endpoint(
    course_id: uuid.UUID,
    body: SwitchSceneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch the active scene for a course (6-step process)."""
    try:
        result = await switch_scene(
            db=db,
            course_id=course_id,
            user_id=user.id,
            new_scene_id=body.scene_id,
            trigger_type=body.trigger_type,
            trigger_context=body.trigger_context,
            current_ui_state=body.current_ui_state,
        )
    except ValueError as e:
        raise NotFoundError(str(e))
    await db.commit()
    return SwitchSceneResponse(**result)


@router.post("/custom", response_model=SceneResponse)
async def create_custom_scene(
    body: CreateSceneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a user-defined custom scene."""
    # Check if scene_id already exists
    existing = await db.execute(select(Scene).where(Scene.scene_id == body.scene_id))
    if existing.scalar_one_or_none():
        raise ConflictError(f"Scene '{body.scene_id}' already exists")

    scene = Scene(
        scene_id=body.scene_id,
        display_name=body.display_name,
        icon=body.icon,
        is_preset=False,
        tab_preset=body.tab_preset,
        workflow=body.workflow,
        ai_behavior=body.ai_behavior,
        preferences=body.preferences,
        created_by=user.id,
    )
    db.add(scene)
    await db.commit()
    await db.refresh(scene)
    return scene
