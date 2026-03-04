"""TeachingAgent — handles LEARN intent with RAG + personalized explanation.

Borrows from:
- HelloAgents TutorAgent: structured teaching with context
- MetaGPT Role: profile/goal/constraints
- OpenClaw agent-scope: independent prompt + model config
"""

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext
from services.agent.tool_loader import get_tools_for_scene

logger = logging.getLogger(__name__)

# ---------- Teaching strategy prompt fragments (loaded once) ----------
_STRATEGY_FRAGMENTS: dict[str, str] = {}


def _load_strategy_fragments() -> dict[str, str]:
    """Parse prompts/teaching_strategies.md into {strategy_name: prompt_text}."""
    if _STRATEGY_FRAGMENTS:
        return _STRATEGY_FRAGMENTS

    md_path = Path(__file__).resolve().parents[2] / "prompts" / "teaching_strategies.md"
    if not md_path.exists():
        return _STRATEGY_FRAGMENTS

    current_key: str | None = None
    current_lines: list[str] = []

    for line in md_path.read_text().splitlines():
        if line.startswith("## ") and not line.startswith("## #"):
            if current_key and current_lines:
                _STRATEGY_FRAGMENTS[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key and current_lines:
        _STRATEGY_FRAGMENTS[current_key] = "\n".join(current_lines).strip()

    return _STRATEGY_FRAGMENTS


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

        # --- Adaptive teaching strategy (Thompson Sampling bandit) ---
        strategy_section = ""
        selected_strategy = ctx.metadata.get("_selected_strategy")
        fatigue_score = ctx.metadata.get("fatigue_score", 0.0)

        if fatigue_score > 0.7:
            # Fatigue override: always use supportive worked-examples mode
            guardrails = (
                "\n## Teaching Mode: Supportive\n"
                "The student seems frustrated. Be more direct and encouraging. "
                "Offer step-by-step worked examples rather than questions.\n"
            )
        elif selected_strategy:
            # Bandit chose a strategy — load its prompt fragment
            fragments = _load_strategy_fragments()
            fragment = fragments.get(selected_strategy, "")
            if fragment:
                strategy_section = f"\n## Adaptive Teaching Strategy\n{fragment}\n"
            # Use softer guardrails alongside bandit strategy
            guardrails = SOCRATIC_GUARDRAILS
        else:
            guardrails = SOCRATIC_GUARDRAILS

        # --- Math image tutoring (inject when LaTeX-OCR extracted formulas) ---
        math_section = ""
        if ctx.metadata.get("_latex_extracted"):
            fragments = _load_strategy_fragments()
            math_fragment = fragments.get("math_image_tutoring", "")
            if math_fragment:
                math_section = f"\n{math_fragment}\n"

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

        return f"{base}\n{guardrails}\n{strategy_section}\n{math_section}\n{scene_tools}\n{cross_course_section}"

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate teaching response using RAG context + adaptive strategy."""

        # --- Step 1: Select teaching strategy via Thompson Sampling bandit ---
        try:
            from services.experiment.bandit import select_strategy_for_context

            mastery = ctx.metadata.get("current_mastery", 0.5)
            difficulty = ctx.metadata.get("difficulty_level", 0.5)
            bandit_result = await select_strategy_for_context(
                db,
                ctx.user_id,
                ctx.course_id,
                mastery_score=mastery,
                difficulty_level=difficulty,
            )
            ctx.metadata["_selected_strategy"] = bandit_result["strategy"]
            ctx.metadata["_strategy_idx"] = bandit_result["strategy_idx"]
            ctx.metadata["_strategy_context"] = bandit_result["context_vector"]
            logger.debug(
                "Bandit selected strategy '%s' for user %s",
                bandit_result["strategy"], ctx.user_id,
            )
        except Exception as e:
            logger.debug("Bandit strategy selection skipped: %s", e)

        # --- Step 1b: LaTeX-OCR extraction for math images ---
        if ctx.images:
            try:
                from services.vision.latex_ocr import try_extract_latex

                latex_results = try_extract_latex(ctx.images)
                if latex_results:
                    latex_block = "\n".join(f"$$${l}$$$" for l in latex_results)
                    ctx.user_message = (
                        f"{ctx.user_message}\n\n"
                        f"[Extracted math formulas from image]\n{latex_block}"
                    )
                    ctx.metadata["_latex_extracted"] = latex_results
                    logger.debug("LaTeX-OCR extracted %d formulas", len(latex_results))
            except Exception as e:
                logger.debug("LaTeX-OCR skipped: %s", e)

        # --- Step 2: Generate response ---
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)

        # --- Step 3: Store bandit context for deferred reward ---
        # The reward is recorded when the student's next quiz answer is
        # evaluated (see routers/quiz.py).  Persist via KV store so it
        # survives across requests.
        if "_strategy_idx" in ctx.metadata:
            try:
                from services.agent.kv_store import kv_set

                await kv_set(
                    db, ctx.user_id, "bandit", "pending_reward",
                    value={
                        "strategy_idx": ctx.metadata["_strategy_idx"],
                        "context_vector": ctx.metadata["_strategy_context"],
                        "strategy": ctx.metadata["_selected_strategy"],
                    },
                    course_id=ctx.course_id,
                )
            except Exception as e:
                logger.debug("Bandit KV store write skipped: %s", e)

        return ctx
