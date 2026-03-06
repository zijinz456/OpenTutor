"""TutorAgent — unified learning agent (Phase 2 consolidation).

Replaces: TeachingAgent, ExerciseAgent, ReviewAgent, CurriculumAgent,
           AssessmentAgent, MotivationAgent, CodeExecutionAgent.

Uses conditional prompt sections based on user message context to handle
teaching, quiz generation, review, assessment, curriculum, and code help.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext
from services.agent.tool_loader import get_all_tools

logger = logging.getLogger(__name__)

# ── Keyword detectors for conditional prompt sections ──

_QUIZ_RE = re.compile(
    r"(quiz|exercise|test\s+me|practice|generate\s+(quiz|question|problem)|"
    r"give\s+me\s+(a\s+)?question|flashcard)", re.IGNORECASE,
)
_REVIEW_RE = re.compile(
    r"(wrong|mistake|error\s+analysis|review\s+my|what\s+did\s+I\s+get\s+wrong|"
    r"where\s+did\s+I\s+go\s+wrong|why\s+(is|was)\s+(it|this)\s+wrong)", re.IGNORECASE,
)
_ASSESS_RE = re.compile(
    r"(assessment|my\s+progress|progress\s+report|weak\s+area|"
    r"how\s+am\s+I\s+doing|exam\s+readiness|mastery|learning\s+status)", re.IGNORECASE,
)
_CURRICULUM_RE = re.compile(
    r"(course\s+structure|knowledge\s+graph|outline|syllabus|curriculum|"
    r"prerequisite|topic\s+hierarchy|learning\s+path|dependency)", re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"(run\s+(this|my|the)\s+code|debug|```python|code\s+execution|"
    r"write\s+a?\s*program|compile)", re.IGNORECASE,
)
_FATIGUE_RE = re.compile(
    r"(don'?t\s+want\s+to\s+study|give\s+up|so\s+tired|can'?t\s+keep\s+going|"
    r"hate\s+this|can'?t\s+do\s+it|too\s+hard|frustrated|forget\s+it|ugh|whatever)", re.IGNORECASE,
)

# ── Teaching strategy fragments (loaded once) ──

_STRATEGY_FRAGMENTS: dict[str, str] = {}


def _load_strategy_fragments() -> dict[str, str]:
    if _STRATEGY_FRAGMENTS:
        return _STRATEGY_FRAGMENTS
    md_path = Path(__file__).resolve().parents[3] / "prompts" / "teaching_strategies.md"
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
## Socratic Teaching Rules (MUST follow):
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

_QUIZ_INSTRUCTIONS = """
## Quiz / Exercise Generation
When generating practice problems, organize them in 3 difficulty layers:

Layer 1 (Basic): Direct concept recall/comprehension. Bloom's: remember, understand
Layer 2 (Standard): Applied knowledge, moderate complexity. Bloom's: apply, analyze
Layer 3 (Advanced): Traps, distractors, edge cases. Bloom's: evaluate, create

For EACH question, include structured metadata:
- question_type, question, options, correct_answer, explanation
- difficulty_layer, core_concept, bloom_level, potential_traps

If the user asks for a practice set, output valid JSON. Otherwise present in readable markdown.
"""

_REVIEW_INSTRUCTIONS = """
## Error Review & Analysis
Analyze student errors using structured data and diagnostic results.

Error categories (from pre-classification, do not reclassify):
1. conceptual: Misunderstanding of core concepts
2. procedural: Wrong steps or method application
3. computational: Calculation or arithmetic errors
4. reading: Misreading the question or data
5. careless: Simple oversight or typo

For each error:
- Use the pre-classified error category and evidence as your starting point
- Explain WHY the mistake happened based on the evidence
- Show the correct approach step by step
- Suggest specific practice to prevent recurrence
- Connect to relevant prerequisite knowledge if conceptual

IMPORTANT: When structured data (error_detail, diagnosis, difficulty_layer)
is provided, treat it as ground truth. Do not contradict it.
"""

_ASSESS_INSTRUCTIONS = """
## Learning Assessment
Evaluate student progress comprehensively:
1. Knowledge mastery across topics (using weighted decay scores)
2. Common error patterns — distinguish systemic vs area-specific weaknesses
3. Difficulty layer analysis (Layer 1=basic, Layer 2=application, Layer 3=traps)
4. Study effort and consistency metrics
5. Personalized improvement recommendations
6. Exam readiness estimation

IMPORTANT: All numbers in data sections are pre-computed from the database.
Do NOT re-count or modify them. Base your analysis on exact numbers.
"""

_CURRICULUM_INSTRUCTIONS = """
## Curriculum Analysis
Analyze course materials to provide insights about:
1. Knowledge graph: concepts and their prerequisite relationships
2. Topic hierarchy: chapters → sections → key concepts
3. Learning objectives per section
4. Difficulty progression mapping
Always base analysis on actual course content provided.
"""

_MOTIVATION_INSTRUCTIONS = """
## Student Support
The student seems frustrated or tired. Respond with:
- Genuine encouragement based on their actual progress (not generic platitudes)
- Acknowledge what they've already accomplished
- Practical suggestions: take a short break, switch topics, try easier problems
- Be warm and supportive but not condescending. Be brief.
- After encouragement, gently redirect to productive learning.
"""


class TutorAgent(ReActMixin, BaseAgent):
    """Unified learning agent handling teaching, quizzes, review, assessment, and more."""

    name = "tutor"
    profile = (
        "You are OpenTutor Zenus, a personalized learning assistant.\n"
        "Answer based on the course materials provided below.\n"
        "If the answer is not in the materials, use web_search to find current information. "
        "Always cite sources when using web results.\n"
        "Adapt your explanation style to the student's preferences.\n"
        "Cite specific sections when possible."
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
        # assessment tools
        "list_recent_tasks",
        # planning-adjacent tools
        "list_study_goals", "list_assignments", "create_study_plan",
        "export_calendar", "list_files",
        # code tools
        "run_code",
    ]

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Build a unified prompt with conditional sections based on message context."""
        base = super().build_system_prompt(ctx)
        msg = ctx.user_message
        fatigue_score = ctx.metadata.get("fatigue_score", 0.0)

        parts = [base]

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

        # ── Teaching strategy ──
        if fatigue_score > 0.7:
            parts.append(
                "\n## Teaching Mode: Supportive\n"
                "The student seems frustrated. Be more direct and encouraging. "
                "Offer step-by-step worked examples rather than questions.\n"
            )
        else:
            # Include all teaching strategy fragments as context for the LLM
            fragments = _load_strategy_fragments()
            if fragments:
                frag_text = "\n\n".join(f"### {k}\n{v}" for k, v in fragments.items())
                parts.append(f"\n## Teaching Strategies\n{frag_text}\n")
            parts.append(SOCRATIC_GUARDRAILS)

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

        # Scene tools
        scene_tools = get_all_tools(include_preference=False)
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

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate response using unified prompt with conditional sections."""
        msg = ctx.user_message

        # Pre-load assessment data if assessment keywords detected
        if _ASSESS_RE.search(msg):
            ctx.metadata["assessment_data"] = await self._build_assessment_data(ctx, db)

        # LaTeX-OCR extraction for math images
        if ctx.images:
            try:
                from services.vision.latex_ocr import try_extract_latex
                latex_results = try_extract_latex(ctx.images)
                if latex_results:
                    latex_block = "\n".join(f"$$${l}$$$" for l in latex_results)
                    ctx.user_message = f"{ctx.user_message}\n\n[Extracted math formulas from image]\n{latex_block}"
                    ctx.metadata["_latex_extracted"] = latex_results
            except Exception as e:
                logger.debug("LaTeX-OCR skipped: %s", e)

        # Code execution pre-processing
        if _CODE_RE.search(msg):
            await self._pre_execute_code(ctx)

        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)

        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Pre-load assessment data if needed, then delegate to ReActMixin.stream()."""
        msg = ctx.user_message

        if _ASSESS_RE.search(msg):
            ctx.metadata["assessment_data"] = await self._build_assessment_data(ctx, db)

        if ctx.images:
            try:
                from services.vision.latex_ocr import try_extract_latex
                latex_results = try_extract_latex(ctx.images)
                if latex_results:
                    latex_block = "\n".join(f"$$${l}$$$" for l in latex_results)
                    ctx.user_message = f"{ctx.user_message}\n\n[Extracted math formulas from image]\n{latex_block}"
                    ctx.metadata["_latex_extracted"] = latex_results
            except Exception as e:
                logger.debug("LaTeX-OCR skipped: %s", e)

        if _CODE_RE.search(msg):
            await self._pre_execute_code(ctx)

        async for chunk in ReActMixin.stream(self, ctx, db):
            yield chunk



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
        except Exception as e:
            logger.debug("Code pre-execution skipped: %s", e)

    async def _build_assessment_data(self, ctx: AgentContext, db: AsyncSession) -> str:
        """Collect learning data from multiple tables for assessment context."""
        from models.progress import LearningProgress
        from models.practice import PracticeProblem
        from models.ingestion import WrongAnswer, StudySession

        parts = []

        # 1. Learning progress
        try:
            progress_result = await db.execute(
                select(LearningProgress).where(
                    LearningProgress.user_id == ctx.user_id,
                    LearningProgress.course_id == ctx.course_id,
                )
            )
            progress = progress_result.scalars().all()
            if progress:
                mastered = sum(1 for p in progress if p.mastery_score >= 0.8)
                in_progress_count = sum(1 for p in progress if 0.2 <= p.mastery_score < 0.8)
                not_started = sum(1 for p in progress if p.mastery_score < 0.2)
                avg_mastery = sum(p.mastery_score for p in progress) / len(progress)
                total_time = sum(p.time_spent_minutes for p in progress)
                total_quizzes = sum(p.quiz_attempts for p in progress)
                total_correct = sum(p.quiz_correct for p in progress)

                parts.append(
                    f"## Progress Overview\n"
                    f"- Total topics: {len(progress)}\n"
                    f"- Mastered (>=80%): {mastered}\n"
                    f"- In progress (20-80%): {in_progress_count}\n"
                    f"- Not started (<20%): {not_started}\n"
                    f"- Average mastery: {avg_mastery:.1%}\n"
                    f"- Total study time: {total_time} minutes\n"
                    f"- Quiz attempts: {total_quizzes}, Correct: {total_correct}"
                )

                gap_counts: dict[str, int] = defaultdict(int)
                for p in progress:
                    if p.gap_type:
                        gap_counts[p.gap_type] += 1
                if gap_counts:
                    gap_str = ", ".join(f"{k}: {v}" for k, v in sorted(gap_counts.items(), key=lambda x: -x[1]))
                    parts.append(f"\n## Difficulty Layer Gap Analysis\n- Gap types: {gap_str}")
        except Exception as e:
            logger.debug("Assessment progress loading failed: %s", e)

        # 2. Error analysis
        try:
            wrong_result = await db.execute(
                select(WrongAnswer, PracticeProblem)
                .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
                .where(
                    WrongAnswer.user_id == ctx.user_id,
                    WrongAnswer.course_id == ctx.course_id,
                    WrongAnswer.error_category.isnot(None),
                )
                .order_by(WrongAnswer.created_at.desc())
                .limit(50)
            )
            wrong_rows = wrong_result.all()
            if wrong_rows:
                error_cats: dict[str, int] = {}
                for wa, _ in wrong_rows:
                    cat = wa.error_category or "unknown"
                    error_cats[cat] = error_cats.get(cat, 0) + 1
                cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(error_cats.items(), key=lambda x: -x[1]))
                unmastered = sum(1 for wa, _ in wrong_rows if not wa.mastered)
                parts.append(
                    f"\n## Error Analysis\n"
                    f"- Total wrong answers analyzed: {len(wrong_rows)}\n"
                    f"- Unmastered: {unmastered}\n"
                    f"- Error categories: {cat_str}"
                )
        except Exception as e:
            logger.debug("Assessment error loading failed: %s", e)

        # 3. Study sessions
        try:
            session_result = await db.execute(
                select(StudySession).where(
                    StudySession.user_id == ctx.user_id,
                    StudySession.course_id == ctx.course_id,
                ).order_by(StudySession.started_at.desc()).limit(30)
            )
            sessions = session_result.scalars().all()
            if sessions:
                total_sessions = len(sessions)
                total_duration = sum(s.duration_minutes or 0 for s in sessions)
                total_problems = sum(s.problems_attempted for s in sessions)
                total_correct_sess = sum(s.problems_correct for s in sessions)
                avg_duration = total_duration / total_sessions if total_sessions else 0
                parts.append(
                    f"\n## Study Sessions (last {total_sessions})\n"
                    f"- Total study time: {total_duration} minutes\n"
                    f"- Average session: {avg_duration:.0f} minutes\n"
                    f"- Problems attempted: {total_problems}\n"
                    f"- Problems correct: {total_correct_sess}"
                )
        except Exception as e:
            logger.debug("Assessment session loading failed: %s", e)

        return "\n".join(parts) if parts else "No assessment data available yet."
