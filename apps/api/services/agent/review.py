"""ReviewAgent — handles REVIEW intent for error analysis and answer feedback.

Borrows from:
- HelloAgents ReviewerAgent: structured review workflow
- Spec Section 5: WF-5 Wrong Answer Review workflow
- Spec Section 4.4: ErrorAnalyzer 5-category classification

v4: VCE-inspired grounded review with structured annotations.
Uses pre-computed error classifications and diagnostic pair results as
immutable context (not re-inferred). Injects difficulty layer info and
contrastive diagnosis matrix for diagnostic pair reviews.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext

logger = logging.getLogger(__name__)

# Diagnostic pair context template (injected when reviewing diagnostic pairs)
_DIAGNOSTIC_PAIR_CONTEXT = """
## Diagnostic Pair Results (structured facts — do not modify or contradict)
Original question (Layer {original_layer}): {original_status}
Simplified version (Layer 1, simplifications: {simplifications}): {clean_status}

## Contrastive Diagnosis Matrix (reference for your analysis)
- Both wrong → fundamental_gap: Core concept not understood
- Clean right, original wrong → trap_vulnerability: Concept OK but falls for traps
- Clean wrong, original right → carelessness: Overthinking the simpler version
- Both right → mastered: Concept understood

Diagnosis result: **{diagnosis}**

Please provide specific, actionable feedback based on this diagnosis.
If fundamental_gap: explain the concept from scratch, link prerequisites.
If trap_vulnerability: identify the specific trap, teach awareness strategies.
If carelessness: suggest checking strategies, highlight the simplification gap.
"""


class ReviewAgent(ReActMixin, BaseAgent):
    """Analyzes errors, provides feedback on wrong answers, and identifies knowledge gaps."""

    name = "review"
    react_tools = ["list_wrong_answers", "search_content", "lookup_progress"]
    profile = (
        "You are OpenTutor Zenus's Review Specialist.\n"
        "Analyze student errors using structured data and diagnostic results.\n\n"
        "Error categories (from pre-classification, do not reclassify):\n"
        "1. conceptual: Misunderstanding of core concepts\n"
        "2. procedural: Wrong steps or method application\n"
        "3. computational: Calculation or arithmetic errors\n"
        "4. reading: Misreading the question or data\n"
        "5. careless: Simple oversight or typo\n\n"
        "For each error:\n"
        "- Use the pre-classified error category and evidence as your starting point\n"
        "- Explain WHY the mistake happened based on the evidence\n"
        "- Show the correct approach step by step\n"
        "- If a diagnostic pair result is provided, base your analysis on it\n"
        "- Suggest specific practice to prevent recurrence\n"
        "- Connect to relevant prerequisite knowledge if the error is conceptual\n\n"
        "IMPORTANT: When structured data (error_detail, diagnosis, difficulty_layer)\n"
        "is provided, treat it as ground truth. Do not contradict it.\n"
        "Be encouraging but precise. Focus on understanding, not just correction."
    )
    model_preference = "large"

    def build_system_prompt(self, ctx: AgentContext) -> str:
        base = super().build_system_prompt(ctx)

        # Inject grounding context from structured annotations if available
        extra_context = self._build_grounding_context(ctx)
        if extra_context:
            return base + "\n\n" + extra_context

        return base

    def _build_grounding_context(self, ctx: AgentContext) -> str:
        """Build grounding context from structured annotations in ctx.metadata.

        This data comes from DB-stored annotations (error_detail, problem_metadata,
        diagnosis) and is injected as immutable facts for the agent to reason over.
        """
        parts = []
        metadata = getattr(ctx, "metadata", None) or {}

        # Error classification grounding
        error_detail = metadata.get("error_detail")
        if error_detail and isinstance(error_detail, dict):
            parts.append(
                f"## Error Classification (pre-analyzed — do not reclassify)\n"
                f"- Category: {error_detail.get('category', 'unknown')}\n"
                f"- Confidence: {error_detail.get('confidence', 'N/A')}\n"
                f"- Evidence: {error_detail.get('evidence', 'N/A')}\n"
                f"- Related concept: {error_detail.get('related_concept', 'N/A')}"
            )

        # Diagnostic pair grounding
        diagnosis = metadata.get("diagnosis")
        if diagnosis:
            parts.append(
                _DIAGNOSTIC_PAIR_CONTEXT.format(
                    original_layer=metadata.get("original_layer", "?"),
                    original_status=metadata.get("original_status", "wrong"),
                    simplifications=metadata.get("simplifications", "N/A"),
                    clean_status=metadata.get("clean_status", "unknown"),
                    diagnosis=diagnosis,
                )
            )

        # Problem metadata grounding
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
                parts.append(
                    "## Question Metadata (verified facts)\n" + "\n".join(meta_parts)
                )

        return "\n\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx
