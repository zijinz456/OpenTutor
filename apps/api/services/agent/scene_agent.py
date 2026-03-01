"""SceneAgent — handles SCENE_SWITCH intent for v3 scene transition suggestions.

Detects the target scene from user message, generates a natural suggestion with
action markers, and handles the case where user is already in the target scene.
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase
from services.agent.teaching import TeachingAgent

logger = logging.getLogger(__name__)

# Map of recognized scene IDs with their display info
SCENE_INFO = {
    "study_session": {"display": "日常学习", "icon": "📚", "keywords": ["学习", "study", "learn"]},
    "exam_prep": {"display": "考前冲刺", "icon": "🎯", "keywords": ["考试", "exam", "test", "midterm", "final", "复习"]},
    "assignment": {"display": "写作业", "icon": "✍️", "keywords": ["作业", "homework", "assignment", "hw"]},
    "review_drill": {"display": "错题专练", "icon": "🔄", "keywords": ["错题", "wrong", "mistake", "review"]},
    "note_organize": {"display": "笔记整理", "icon": "📝", "keywords": ["笔记", "notes", "整理", "organize"]},
}


def explain_scene_switch(message: str, current_scene: str) -> dict | None:
    """Infer target scene and expose the matched cues for provenance."""
    msg_lower = message.lower()
    for scene_id, info in SCENE_INFO.items():
        if scene_id == current_scene:
            continue
        matched = [kw for kw in info["keywords"] if kw in msg_lower]
        if matched:
            return {
                "current_scene": current_scene,
                "target_scene": scene_id,
                "matched_keywords": matched[:3],
                "reason": (
                    f"Detected {info['display']} intent from "
                    f"{', '.join(repr(keyword) for keyword in matched[:3])}."
                ),
            }
    return None


def infer_target_scene(message: str, current_scene: str) -> str | None:
    """Infer the most likely target scene from the user's message."""
    explanation = explain_scene_switch(message, current_scene)
    return explanation["target_scene"] if explanation else None


class SceneAgent(BaseAgent):
    """Suggests scene transitions based on detected goal/mode changes."""

    name = "scene"
    profile = (
        "You are OpenTutor's Scene Manager.\n"
        "You detect when the student's learning goal changes and suggest switching modes.\n\n"
        "Available scenes:\n"
        "- 📚 study_session (日常学习): Complete explanations, explore freely\n"
        "- 🎯 exam_prep (考前冲刺): Concise summaries, weak point focus, timed quizzes\n"
        "- ✍️ assignment (写作业): Step-by-step guidance, no direct answers\n"
        "- 🔄 review_drill (错题专练): Error analysis, derived questions, spaced review\n"
        "- 📝 note_organize (笔记整理): Structure optimization, cross-chapter integration\n\n"
        "When suggesting a scene switch:\n"
        "1. Briefly acknowledge the student's goal\n"
        "2. Explain what the new mode offers\n"
        "3. Output the action marker for the frontend\n"
        "4. Be natural and helpful, not robotic\n\n"
        "Action marker: [ACTION:suggest_scene_switch:<scene_id>]\n"
        "If the student is already in the right scene, just help them with their request normally."
    )
    model_preference = "small"

    def build_system_prompt(self, ctx: AgentContext) -> str:
        parts = [self.profile]
        parts.append(f"\nCurrent scene: {ctx.scene}")

        target = infer_target_scene(ctx.user_message, ctx.scene)
        if target and target in SCENE_INFO:
            info = SCENE_INFO[target]
            parts.append(f"\nDetected target scene: {info['icon']} {info['display']} ({target})")
        else:
            parts.append("\nNo clear target scene detected. Help the student with their request.")

        if ctx.preferences:
            pref_lines = [f"- {k}: {v}" for k, v in ctx.preferences.items()]
            parts.append(f"\nUser preferences:\n" + "\n".join(pref_lines))

        return "\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        from services.llm.router import get_llm_client

        scene_switch = explain_scene_switch(ctx.user_message, ctx.scene)
        target = scene_switch["target_scene"] if scene_switch else None
        if scene_switch:
            ctx.metadata["scene_switch"] = scene_switch
        if not target:
            return await TeachingAgent().run(ctx, db)

        system_prompt = self.build_system_prompt(ctx)
        client = get_llm_client()
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        from services.llm.router import get_llm_client

        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        # If no scene switch is needed, continue with normal teaching behavior.
        scene_switch = explain_scene_switch(ctx.user_message, ctx.scene)
        target = scene_switch["target_scene"] if scene_switch else None
        if scene_switch:
            ctx.metadata["scene_switch"] = scene_switch
        if not target:
            async for chunk in TeachingAgent().stream(ctx, db):
                yield chunk
            return

        system_prompt = self.build_system_prompt(ctx)
        client = get_llm_client()

        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message):
            full_response += chunk
            yield chunk
        ctx.response = full_response
