"""Scene management API — v3 scene system.

Endpoints for listing scenes, getting active scene, switching scenes, and creating custom scenes.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.scene import Scene
from models.course import Course
from models.user import User
from services.auth.dependency import get_current_user
from services.scene.manager import switch_scene, get_scene_config, load_snapshot

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
    tab_layout: list[dict] | dict | None = None
    init_actions: list[dict] = []
    message: str | None = None


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
async def list_scenes(db: AsyncSession = Depends(get_db)):
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
async def get_active_scene(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get the active scene and its snapshot for a course."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    scene_id = course.active_scene or "study_session"
    config = await get_scene_config(db, scene_id)
    snapshot = await load_snapshot(db, course_id, scene_id)

    return ActiveSceneResponse(scene_id=scene_id, config=config, snapshot=snapshot)


@router.post("/{course_id}/switch", response_model=SwitchSceneResponse)
async def switch_scene_endpoint(
    course_id: uuid.UUID,
    body: SwitchSceneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch the active scene for a course (6-step process)."""
    result = await switch_scene(
        db=db,
        course_id=course_id,
        user_id=user.id,
        new_scene_id=body.scene_id,
        trigger_type=body.trigger_type,
        trigger_context=body.trigger_context,
        current_ui_state=body.current_ui_state,
    )
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
        raise HTTPException(status_code=409, detail=f"Scene '{body.scene_id}' already exists")

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
