"""TeachingAgent — handles LEARN intent with RAG + personalized explanation.

Borrows from:
- HelloAgents TutorAgent: structured teaching with context
- MetaGPT Role: profile/goal/constraints
- OpenClaw agent-scope: independent prompt + model config
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext
from services.agent.tool_loader import get_tools_for_scene

logger = logging.getLogger(__name__)


SOCRATIC_GUARDRAILS = """
## Socratic Teaching Rules (MUST follow — inspired by Khanmigo):
1. NEVER give the student the direct answer to their question.
2. Ask ONE guiding question at a time to scaffold their thinking.
3. If the student asks for help 3+ times on the same topic without showing effort:
   - Zoom out: "Which part of the hint is confusing you?"
   - Offer multiple choice as an absolute last resort.
4. After a correct answer, ask "Can you explain WHY that works?"
5. Match language complexity to the student's demonstrated level.
6. For math/science: verify your own calculations step-by-step before responding.
7. Acknowledge emotions: "I can see this is tricky" before guiding further.
8. Use the student's own words and examples when building explanations.
"""


class TeachingAgent(ReActMixin, BaseAgent):
    """Handles knowledge questions, explanations, and concept learning."""

    name = "teaching"
    profile = (
        "You are OpenTutor Zenus, a personalized learning assistant.\n"
        "Answer based on the course materials provided below.\n"
        "If the answer is not in the materials, use web_search to find current information. "
        "Always cite sources when using web results.\n"
        "Adapt your explanation style to the student's preferences.\n"
        "Cite specific sections when possible."
    )
    model_preference = "large"  # Teaching needs the best model
    react_tools = ["search_content", "lookup_progress", "get_course_outline", "generate_notes", "web_search", "write_file"]

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Teaching-specific prompt with scene-aware behavior + tools + RAG context."""
        # Base class handles: profile, scene behavior, preferences, memories, RAG
        base = super().build_system_prompt(ctx)
        # Add scene-based tool injection (saves ~30% tokens)
        scene_tools = get_tools_for_scene(ctx.scene, include_preference=False)

        # Socratic guardrails — suppress if student is explicitly frustrated
        fatigue_score = ctx.metadata.get("fatigue_score", 0.0)
        if fatigue_score <= 0.7:
            guardrails = SOCRATIC_GUARDRAILS
        else:
            guardrails = (
                "\n## Teaching Mode: Supportive\n"
                "The student seems frustrated. Be more direct and encouraging. "
                "Offer step-by-step worked examples rather than questions.\n"
            )

        # Cross-course connections (if available from context_builder)
        cross_course_section = ""
        cross_patterns = ctx.metadata.get("cross_course_patterns")
        if cross_patterns:
            lines = ["\n## Cross-Course Connections"]
            lines.append("Point these out when relevant to help the student connect knowledge:")
            for p in cross_patterns[:3]:
                courses_str = ", ".join(c.get("course_name", "?") for c in p.get("courses", []))
                mastery_info = ", ".join(
                    f"{c.get('course_name', '?')}: {c.get('mastery', '?')}"
                    for c in p.get("courses", [])
                )
                lines.append(f"- '{p.get('topic', '?')}' appears in: {courses_str} (mastery: {mastery_info})")
            cross_course_section = "\n".join(lines)

        return f"{base}\n{guardrails}\n{scene_tools}\n{cross_course_section}"

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate teaching response using RAG context."""
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)
        return ctx
