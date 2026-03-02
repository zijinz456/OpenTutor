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
from services.scene.policy import resolve_scene_policy

logger = logging.getLogger(__name__)

# Map of recognized scene IDs with their display info
SCENE_INFO = {
    "study_session": {"display": "Daily Study", "icon": "📚", "keywords": ["study", "learn"]},
    "exam_prep": {"display": "Exam Prep", "icon": "🎯", "keywords": ["exam", "test", "midterm", "final", "review"]},
    "assignment": {"display": "Homework", "icon": "✍️", "keywords": ["homework", "assignment", "hw"]},
    "review_drill": {"display": "Error Drill", "icon": "🔄", "keywords": ["wrong", "mistake", "review"]},
    "note_organize": {"display": "Note Organization", "icon": "📝", "keywords": ["notes", "organize"]},
}


async def explain_scene_switch(ctx: AgentContext, db: AsyncSession) -> dict | None:
    """Infer target scene through the shared policy engine."""
    try:
        decision = await resolve_scene_policy(
            db,
            user_id=ctx.user_id,
            course_id=ctx.course_id,
            message=ctx.user_message,
            current_scene=ctx.scene,
            active_tab=ctx.active_tab,
        )
    except Exception as exc:
        logger.warning("Scene policy failed inside SceneAgent: %s", exc)
        return None
    ctx.metadata["scene_policy"] = {
        "recommended_scene": decision.scene_id,
        "confidence": round(decision.confidence, 3),
        "scores": decision.scores,
        "features": decision.features,
        "reason": decision.reason,
        "switch_recommended": decision.switch_recommended,
        "expected_benefit": getattr(decision, "expected_benefit", ""),
        "reversible_action": getattr(decision, "reversible_action", True),
        "layout_policy": getattr(decision, "layout_policy", "balanced_exploration"),
        "reasoning_policy": getattr(decision, "reasoning_policy", "broad_then_deep"),
        "workflow_policy": getattr(decision, "workflow_policy", "interactive_tutoring"),
    }
    if not decision.switch_recommended:
        return None
    return {
        "current_scene": ctx.scene,
        "target_scene": decision.scene_id,
        "reason": decision.reason,
        "policy_confidence": round(decision.confidence, 3),
        "expected_benefit": getattr(decision, "expected_benefit", ""),
        "reversible_action": getattr(decision, "reversible_action", True),
        "layout_policy": getattr(decision, "layout_policy", "balanced_exploration"),
        "reasoning_policy": getattr(decision, "reasoning_policy", "broad_then_deep"),
        "workflow_policy": getattr(decision, "workflow_policy", "interactive_tutoring"),
        "score_margin": round(
            decision.scores[decision.scene_id] - max(
                score for scene, score in decision.scores.items() if scene != decision.scene_id
            ),
            3,
        ),
    }


class SceneAgent(BaseAgent):
    """Suggests scene transitions based on detected goal/mode changes."""

    name = "scene"
    profile = (
        "You are OpenTutor Zenus's Scene Manager.\n"
        "You detect when the student's learning goal changes and suggest switching modes.\n\n"
        "Available scenes:\n"
        "- 📚 study_session (Daily Study): Complete explanations, explore freely\n"
        "- 🎯 exam_prep (Exam Prep): Concise summaries, weak point focus, timed quizzes\n"
        "- ✍️ assignment (Homework): Step-by-step guidance, no direct answers\n"
        "- 🔄 review_drill (Error Drill): Error analysis, derived questions, spaced review\n"
        "- 📝 note_organize (Note Organization): Structure optimization, cross-chapter integration\n\n"
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

        target = (ctx.metadata.get("scene_switch") or {}).get("target_scene")
        if target and target in SCENE_INFO:
            info = SCENE_INFO[target]
            parts.append(f"\nDetected target scene: {info['icon']} {info['display']} ({target})")
        else:
            parts.append("\nNo clear target scene detected. Help the student with their request.")

        if ctx.metadata.get("scene_policy"):
            policy = ctx.metadata["scene_policy"]
            parts.append(
                "\nScene strategy:\n"
                f"- layout_policy: {policy.get('layout_policy', 'balanced_exploration')}\n"
                f"- reasoning_policy: {policy.get('reasoning_policy', 'broad_then_deep')}\n"
                f"- workflow_policy: {policy.get('workflow_policy', 'interactive_tutoring')}\n"
                f"- expected_benefit: {policy.get('expected_benefit', '')}"
            )

        if ctx.preferences:
            pref_lines = [f"- {k}: {v}" for k, v in ctx.preferences.items()]
            parts.append(f"\nUser preferences:\n" + "\n".join(pref_lines))

        return "\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        from services.llm.router import get_llm_client

        scene_switch = await explain_scene_switch(ctx, db)
        target = scene_switch["target_scene"] if scene_switch else None
        if scene_switch:
            ctx.metadata["scene_switch"] = scene_switch
        if not target:
            return await TeachingAgent().run(ctx, db)

        system_prompt = self.build_system_prompt(ctx)
        client = get_llm_client("fast")
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        from services.llm.router import get_llm_client

        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        # If no scene switch is needed, continue with normal teaching behavior.
        scene_switch = await explain_scene_switch(ctx, db)
        target = scene_switch["target_scene"] if scene_switch else None
        if scene_switch:
            ctx.metadata["scene_switch"] = scene_switch
        if not target:
            async for chunk in TeachingAgent().stream(ctx, db):
                yield chunk
            return

        system_prompt = self.build_system_prompt(ctx)
        client = get_llm_client("fast")

        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message, images=ctx.images or None):
            full_response += chunk
            yield chunk
        ctx.response = full_response
