"""TutorAgent — unified learning agent (Phase 2 consolidation).

Replaces: TeachingAgent, ExerciseAgent, ReviewAgent, CurriculumAgent,
           AssessmentAgent, MotivationAgent, CodeExecutionAgent.

Uses conditional prompt sections based on user message context to handle
teaching, quiz generation, review, assessment, curriculum, and code help.
"""

import logging
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext
from services.agent.tool_loader import get_all_tools

# Import prompt constants and helpers from split module
from services.agent.agents.prompts import (  # noqa: F401 — re-exported
    _QUIZ_RE,
    _REVIEW_RE,
    _ASSESS_RE,
    _CURRICULUM_RE,
    _CODE_RE,
    _FATIGUE_RE,
    _load_strategy_fragments,
    SOCRATIC_GUARDRAILS,
    _QUIZ_INSTRUCTIONS,
    _REVIEW_INSTRUCTIONS,
    _ASSESS_INSTRUCTIONS,
    _CURRICULUM_INSTRUCTIONS,
    _MOTIVATION_INSTRUCTIONS,
    _COMPREHENSION_PROBING,
    _MODE_INSTRUCTIONS,
)

# Import assessment data builder from split module
from services.agent.agents.assessment import build_assessment_data  # noqa: F401

logger = logging.getLogger(__name__)


class TutorAgent(ReActMixin, BaseAgent):
    """Unified learning agent handling teaching, quizzes, review, assessment, and more."""

    name = "tutor"
    profile = (
        "You are OpenTutor Zenus, a personalized learning assistant.\n"
        "Answer based on the course materials provided below.\n"
        "If the answer is not in the materials, use web_search to find current information.\n"
        "CITATION RULES:\n"
        "- Always cite your sources inline using [Source: filename] or [Source: section title].\n"
        "- When referencing course materials, cite the specific section, e.g. [Source: Lecture_02.pdf].\n"
        "- When using web results, include the URL.\n"
        "- At the end of your response, include a '**Sources:**' footer listing all cited materials.\n"
        "Adapt your explanation style to the student's preferences."
    )
    model_preference = "large"
    react_tools = [
        "search_content", "lookup_progress", "get_course_outline",
        "generate_notes", "web_search", "write_file", "update_workspace",
        # quiz/exercise tools
        "get_mastery_report", "list_wrong_answers", "generate_flashcards",
        "generate_quiz", "export_anki",
        # review tools
        "derive_diagnostic",
        # comprehension probing
        "record_comprehension",
        # assessment tools
        "list_recent_tasks",
        # planning-adjacent tools
        "list_study_goals", "list_assignments", "create_study_plan",
        "export_calendar", "list_files",
        # code tools
        "run_code",
        # memory tools
        "save_user_preference",
    ]

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Build a unified prompt with conditional sections based on message context."""
        base = super().build_system_prompt(ctx)
        msg = ctx.user_message
        fatigue_score = ctx.metadata.get("fatigue_score", 0.0)

        parts = [base]

        # ── Learning mode adaptation ──
        if ctx.learning_mode:
            mode_instructions = _MODE_INSTRUCTIONS.get(ctx.learning_mode)
            if mode_instructions:
                parts.append(mode_instructions)

        # ── Conditional section: quiz/exercise ──
        if _QUIZ_RE.search(msg):
            parts.append(_QUIZ_INSTRUCTIONS)
            if hasattr(ctx, "difficulty_guidance") and ctx.difficulty_guidance:
                parts.append(ctx.difficulty_guidance)

        # ── Conditional section: review/error analysis ──
        if _REVIEW_RE.search(msg):
            parts.append(_REVIEW_INSTRUCTIONS)
            grounding = self._build_grounding_context(ctx)
            if grounding:
                parts.append(grounding)
            error_patterns = ctx.metadata.get("error_patterns")
            if error_patterns:
                lines = ["\n## Student's Recurring Error Patterns"]
                for ep in error_patterns:
                    lines.append(f"- {ep['category']}: {ep['count']} errors ({ep['percentage']}%)")
                parts.append("\n".join(lines))

        # ── Conditional section: assessment ──
        if _ASSESS_RE.search(msg):
            parts.append(_ASSESS_INSTRUCTIONS)
            assessment_data = ctx.metadata.get("assessment_data", "")
            if assessment_data:
                parts.append(assessment_data)

        # ── Conditional section: curriculum ──
        if _CURRICULUM_RE.search(msg):
            parts.append(_CURRICULUM_INSTRUCTIONS)

        # ── Conditional section: fatigue/motivation ──
        if _FATIGUE_RE.search(msg) or fatigue_score > 0.6:
            parts.append(_MOTIVATION_INSTRUCTIONS)

        # ── Cognitive load adaptive guidance ──
        cl = ctx.metadata.get("cognitive_load")
        if cl and cl.get("guidance"):
            parts.append(cl["guidance"])

        # ── Teaching strategy ──
        if fatigue_score > 0.7:
            parts.append(
                "\n## Teaching Mode: Supportive\n"
                "The student seems frustrated. Be more direct and encouraging. "
                "Offer step-by-step worked examples rather than questions.\n"
            )
        else:
            # Only load relevant teaching strategy fragments (not all)
            fragments = _load_strategy_fragments()
            if fragments:
                # Select at most 2 relevant fragments based on message context
                relevant_keys = []
                msg_lower = msg.lower()
                for k in fragments:
                    k_lower = k.lower().replace("_", " ")
                    if any(word in msg_lower for word in k_lower.split()):
                        relevant_keys.append(k)
                if not relevant_keys:
                    # Default to first 2 fragments if none match
                    relevant_keys = list(fragments.keys())[:2]
                else:
                    relevant_keys = relevant_keys[:2]
                frag_text = "\n\n".join(f"### {k}\n{fragments[k]}" for k in relevant_keys)
                parts.append(f"\n## Teaching Strategies\n{frag_text}\n")
            parts.append(SOCRATIC_GUARDRAILS)
            parts.append(_COMPREHENSION_PROBING)

        # ── Socratic engine directive (stateful FSM) ──
        socratic_directive = ctx.metadata.get("socratic_directive")
        if socratic_directive:
            parts.append(socratic_directive)

        # ── Math image tutoring ──
        if ctx.metadata.get("_latex_extracted"):
            fragments = _load_strategy_fragments()
            math_fragment = fragments.get("math_image_tutoring", "")
            if math_fragment:
                parts.append(f"\n{math_fragment}\n")

        # ── Cross-course connections ──
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
            parts.append("\n".join(lines))

        # ── Block layout awareness ──
        layout_ctx = ctx.metadata.get("layout_context")
        if layout_ctx:
            parts.append(
                f"\n## Student's Workspace Layout\n{layout_ctx}\n"
                "When suggesting actions like adding blocks or changing modes, "
                "check the current layout first. Do not suggest adding blocks that already exist. "
                "Do not re-suggest dismissed block types."
            )

        # Scene-specific tools (only load relevant tools for current context)
        from services.agent.tool_loader import get_scene_tools
        scene = ctx.metadata.get("scene") or ctx.scene or ""
        scene_tools = get_scene_tools(scene, include_preference=False)
        parts.append(scene_tools)

        return "\n".join(parts)

    def _build_grounding_context(self, ctx: AgentContext) -> str:
        """Build grounding context from structured annotations for review mode."""
        parts = []
        metadata = getattr(ctx, "metadata", None) or {}

        error_detail = metadata.get("error_detail")
        if error_detail and isinstance(error_detail, dict):
            parts.append(
                f"## Error Classification (pre-analyzed — do not reclassify)\n"
                f"- Category: {error_detail.get('category', 'unknown')}\n"
                f"- Confidence: {error_detail.get('confidence', 'N/A')}\n"
                f"- Evidence: {error_detail.get('evidence', 'N/A')}\n"
                f"- Related concept: {error_detail.get('related_concept', 'N/A')}"
            )

        diagnosis = metadata.get("diagnosis")
        if diagnosis:
            parts.append(
                f"## Diagnostic Pair Results\n"
                f"Original question (Layer {metadata.get('original_layer', '?')}): {metadata.get('original_status', 'wrong')}\n"
                f"Simplified version (Layer 1, simplifications: {metadata.get('simplifications', 'N/A')}): {metadata.get('clean_status', 'unknown')}\n"
                f"Diagnosis result: **{diagnosis}**"
            )

        problem_meta = metadata.get("problem_metadata")
        if problem_meta and isinstance(problem_meta, dict):
            meta_parts = []
            if problem_meta.get("core_concept"):
                meta_parts.append(f"Core concept: {problem_meta['core_concept']}")
            if problem_meta.get("potential_traps"):
                meta_parts.append(f"Known traps: {', '.join(problem_meta['potential_traps'])}")
            if problem_meta.get("difficulty_layer"):
                meta_parts.append(f"Difficulty layer: {problem_meta['difficulty_layer']}")
            if meta_parts:
                parts.append("## Question Metadata (verified facts)\n" + "\n".join(meta_parts))

        return "\n\n".join(parts)

    async def _load_socratic(self, ctx: AgentContext, db: AsyncSession) -> None:
        """Load Socratic engine state and inject directive into metadata."""
        try:
            from services.agent.socratic_engine import load_socratic_engine

            # Get real mastery from LearningProgress
            mastery = 0.5
            try:
                from models.progress import LearningProgress
                progress_result = await db.execute(
                    select(LearningProgress).where(
                        LearningProgress.user_id == ctx.user_id,
                        LearningProgress.course_id == ctx.course_id,
                    )
                )
                progress = progress_result.scalars().all()
                if progress:
                    mastery = sum(p.mastery_score for p in progress) / len(progress)
            except (SQLAlchemyError, ImportError):
                logger.debug("Could not load mastery for Socratic engine")

            cl = ctx.metadata.get("cognitive_load", {})
            cognitive_load = cl.get("score", 0.0)
            error_type = ctx.metadata.get("last_error_category")

            engine = await load_socratic_engine(
                db, ctx.user_id, ctx.course_id,
                mastery=mastery,
                cognitive_load=cognitive_load,
                error_type=error_type,
            )
            ctx.metadata["socratic_directive"] = engine.get_prompt_directive()
            ctx.metadata["_socratic_engine"] = engine
        except (SQLAlchemyError, ConnectionError, TimeoutError, KeyError, ValueError) as e:
            logger.debug("Socratic engine loading skipped: %s", e)

    async def _save_socratic(self, ctx: AgentContext, db: AsyncSession) -> None:
        """Classify response quality, transition Socratic state, and persist."""
        engine = ctx.metadata.get("_socratic_engine")
        if not engine:
            return
        try:
            from services.agent.socratic_engine import (
                classify_response_quality, save_socratic_engine,
            )
            # Get last tutor message from history for classification context
            history = ctx.metadata.get("history", [])
            last_tutor = ""
            for h in reversed(history):
                if h.get("role") == "assistant":
                    last_tutor = h.get("content", "")[:500]
                    break
            if last_tutor and ctx.user_message:
                quality = await classify_response_quality(last_tutor, ctx.user_message)
                engine.transition(quality)
            await save_socratic_engine(db, ctx.user_id, ctx.course_id, engine)
        except (SQLAlchemyError, ConnectionError, TimeoutError, KeyError, ValueError) as e:
            logger.debug("Socratic state save skipped: %s", e)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate response using unified prompt with conditional sections."""
        msg = ctx.user_message

        # Pre-load assessment data if assessment keywords detected
        if _ASSESS_RE.search(msg):
            ctx.metadata["assessment_data"] = await self._build_assessment_data(ctx, db)

        # Load Socratic engine state
        await self._load_socratic(ctx, db)

        # LaTeX-OCR extraction for math images
        if ctx.images:
            try:
                from services.vision.latex_ocr import try_extract_latex
                latex_results = try_extract_latex(ctx.images)
                if latex_results:
                    latex_block = "\n".join(f"$$${l}$$$" for l in latex_results)
                    ctx.user_message = f"{ctx.user_message}\n\n[Extracted math formulas from image]\n{latex_block}"
                    ctx.metadata["_latex_extracted"] = latex_results
            except (ImportError, OSError, RuntimeError, ValueError) as e:
                logger.debug("LaTeX-OCR skipped: %s", e)

        # Code execution pre-processing
        if _CODE_RE.search(msg):
            await self._pre_execute_code(ctx)

        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)

        # Save Socratic state after response
        await self._save_socratic(ctx, db)

        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Pre-load assessment data if needed, then delegate to ReActMixin.stream()."""
        msg = ctx.user_message

        if _ASSESS_RE.search(msg):
            ctx.metadata["assessment_data"] = await self._build_assessment_data(ctx, db)

        # Load Socratic engine state
        await self._load_socratic(ctx, db)

        if ctx.images:
            try:
                from services.vision.latex_ocr import try_extract_latex
                latex_results = try_extract_latex(ctx.images)
                if latex_results:
                    latex_block = "\n".join(f"$$${l}$$$" for l in latex_results)
                    ctx.user_message = f"{ctx.user_message}\n\n[Extracted math formulas from image]\n{latex_block}"
                    ctx.metadata["_latex_extracted"] = latex_results
            except (ImportError, OSError, RuntimeError, ValueError) as e:
                logger.debug("LaTeX-OCR skipped: %s", e)

        if _CODE_RE.search(msg):
            await self._pre_execute_code(ctx)

        async for chunk in ReActMixin.stream(self, ctx, db):
            yield chunk

        # Save Socratic state after streaming completes
        await self._save_socratic(ctx, db)

    async def _pre_execute_code(self, ctx: AgentContext) -> None:
        """Extract and execute code from message before LLM call."""
        import asyncio as _asyncio
        try:
            from services.agent.code_execution import CodeExecutionAgent
            agent = CodeExecutionAgent()
            code = agent._extract_code(ctx.user_message)
            if code:
                safe, reason = agent._validate_code(code)
                if safe:
                    result = await _asyncio.to_thread(agent._execute_safe, code)
                    ctx.metadata["code_result"] = result
                    ctx.metadata["code_snippet"] = code
                    ctx.metadata["sandbox_backend"] = result.get("backend")
                else:
                    ctx.metadata["code_result"] = {"success": False, "output": "", "error": reason}
                    ctx.metadata["code_snippet"] = code
        except (ImportError, OSError, RuntimeError, ValueError) as e:
            logger.debug("Code pre-execution skipped: %s", e)

    async def _build_assessment_data(self, ctx: AgentContext, db: AsyncSession) -> str:
        """Delegate to standalone assessment data builder."""
        return await build_assessment_data(ctx, db)
