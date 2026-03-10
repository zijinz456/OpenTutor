"""ReflectionAgent — self-check mechanism for response quality.

Borrows from:
- HelloAgents reflection_agent.py: generate → critique → improve loop
- OpenAkita VERIFYING phase: verify response before delivery
- MetaGPT QAEngineer: quality assurance on generated content

The ReflectionAgent checks:
1. Factual accuracy against RAG context
2. Preference compliance (language, detail level, format)
3. Pedagogical quality (for educational responses)
4. Completeness of the answer
"""

import json
import logging

from services.agent.state import AgentContext
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """You are a quality reviewer for a learning assistant's responses.

Review the following response against these criteria:
1. ACCURACY: Does the response align with the provided course materials?
2. PREFERENCES: Does it match the student's preferences (language, detail level, format)?
3. PEDAGOGY: Is it educational and helpful for learning?
4. COMPLETENESS: Does it fully answer the student's question?

Student's question: {user_message}
Student's preferences: {preferences}
Response to review: {response}

Course materials used:
{context_summary}

Output JSON:
{{
  "score": <1-10>,
  "issues": ["<issue1>", "<issue2>"],
  "suggestion": "<brief improvement suggestion or empty string if good>"
}}

If score >= 7, the response is acceptable. Only suggest changes for serious issues."""

IMPROVEMENT_PROMPT = """Improve this learning assistant response based on the feedback.

Original response:
{original_response}

Issues found:
{issues}

Improvement suggestion:
{suggestion}

Student's question: {user_message}
Student's preferences: {preferences}

Output ONLY the improved response (no meta-commentary):"""


async def reflect_and_improve(ctx: AgentContext) -> AgentContext:
    """Run reflection on the generated response. Improve if score < 7.

    This is an optional VERIFYING phase (OpenAkita pattern).
    Only called when enabled — adds ~1 extra LLM call for quality.
    """
    if not ctx.response or len(ctx.response) < 20:
        return ctx

    client = get_llm_client()

    # Summarize context for review
    context_summary = ""
    if ctx.content_docs:
        context_summary = "\n".join(
            f"- {doc.get('title', '')}: {doc.get('content', '')[:200]}"
            for doc in ctx.content_docs[:3]
        )

    try:
        # Step 1: Critique
        review_prompt = REFLECTION_PROMPT.format(
            user_message=ctx.user_message[:300],
            preferences=json.dumps(ctx.preferences, ensure_ascii=False),
            response=ctx.response[:1500],
            context_summary=context_summary[:800],
        )
        review_result, _ = await client.extract(
            "You are a quality reviewer. Output valid JSON only.",
            review_prompt,
        )
        review_result = review_result.strip()

        if "```" in review_result:
            json_start = review_result.find("{")
            json_end = review_result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                review_result = review_result[json_start:json_end]

        review = json.loads(review_result)
        score = int(review.get("score", 8))
        issues = review.get("issues", [])
        suggestion = review.get("suggestion", "")

        logger.info(
            "Reflection score=%d issues=%d agent=%s",
            score, len(issues), ctx.delegated_agent,
        )

        # Step 2: Improve if needed
        if score < 7 and (issues or suggestion):
            improve_prompt = IMPROVEMENT_PROMPT.format(
                original_response=ctx.response[:2000],
                issues="\n".join(f"- {i}" for i in issues),
                suggestion=suggestion,
                user_message=ctx.user_message[:300],
                preferences=json.dumps(ctx.preferences, ensure_ascii=False),
            )
            improved, _ = await client.chat(
                "You are a learning assistant. Improve the response as instructed.",
                improve_prompt,
            )
            if improved and len(improved) > 20:
                ctx.response = improved
                ctx.metadata["reflection"] = {
                    "original_score": score,
                    "issues": issues,
                    "improved": True,
                }
                logger.info("Response improved by reflection (score %d → improved)", score)
        else:
            ctx.metadata["reflection"] = {
                "score": score,
                "issues": issues,
                "improved": False,
            }

    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        logger.exception("Reflection failed (non-critical): %s", e)
        ctx.metadata["reflection"] = {"error": str(e)}

    return ctx
