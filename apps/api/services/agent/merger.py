"""Merge strategies for parallel agent (swarm) results.

After multiple agents run in parallel, their outputs need to be combined
into a single coherent response for the user.  Three strategies are
supported:

- concatenate:     Simple section-based join with role headers and dividers.
- llm_synthesize:  Uses a lightweight LLM call to weave outputs together
                   into one natural, coherent response.
- structured:      Attempts JSON parse of each result and merges into a
                   unified dict; falls back to concatenation for non-JSON.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Role Headers ──
# Maps agent names to Markdown section headers for the concatenate strategy.

ROLE_HEADERS: dict[str, str] = {
    "teaching": "## Explanation",
    "exercise": "## Practice",
    "planning": "## Study Plan",
    "review": "## Review & Analysis",
    "assessment": "## Assessment",
    "curriculum": "## Curriculum Overview",
    "motivation": "## Encouragement",
    "code_execution": "## Code",
    "preference": "## Preferences",
    "scene": "## Scene",
}

_SYNTHESIZE_SYSTEM_PROMPT = (
    "You are an expert educational content editor. Your job is to merge "
    "multiple specialist agent outputs into ONE coherent, well-structured "
    "response for a student. Requirements:\n"
    "- Maintain a natural, conversational tone appropriate for tutoring.\n"
    "- Preserve ALL substantive content from each agent.\n"
    "- Use clear section headers (##) to organize different aspects.\n"
    "- Ensure smooth transitions between sections.\n"
    "- Remove redundancy but keep unique insights from each agent.\n"
    "- If agents provide conflicting information, include both perspectives "
    "with a note.\n"
    "- The final output should read as if written by a single knowledgeable "
    "tutor, not as separate disconnected blocks.\n"
    "- Respond in the same language as the student's original message."
)


async def merge_results(
    results: list[dict],
    user_message: str,
    strategy: str = "llm_synthesize",
    primary_agent: str | None = None,
) -> str:
    """Merge multiple agent results into a single response.

    Args:
        results: List of result dicts from delegate_parallel().
                 Each has: agent, response, success, error, tokens, etc.
        user_message: The original user message (for LLM context).
        strategy: One of "concatenate", "llm_synthesize", "structured".
        primary_agent: Agent whose output should appear first.

    Returns:
        Merged response string.
    """
    # Filter to successful results with non-empty responses
    successful = [
        r for r in results
        if r.get("success") and r.get("response", "").strip()
    ]

    if not successful:
        logger.warning("No successful results to merge")
        return "[All parallel agents failed to produce a response.]"

    if len(successful) == 1:
        return successful[0]["response"]

    # Sort: primary agent first, then preserve original order
    if primary_agent:
        successful.sort(
            key=lambda r: (0 if r["agent"] == primary_agent else 1),
        )

    if strategy == "concatenate":
        return _merge_concatenate(successful)
    elif strategy == "llm_synthesize":
        return await _merge_llm_synthesize(successful, user_message)
    elif strategy == "structured":
        return _merge_structured(successful)
    else:
        logger.warning("Unknown merge strategy '%s', falling back to concatenate", strategy)
        return _merge_concatenate(successful)


def _merge_concatenate(results: list[dict]) -> str:
    """Simple section-based merge with role headers and dividers."""
    sections: list[str] = []

    for r in results:
        agent_name = r["agent"]
        response = r["response"].strip()
        header = ROLE_HEADERS.get(agent_name, f"## {agent_name.replace('_', ' ').title()}")
        sections.append(f"{header}\n\n{response}")

    return "\n\n---\n\n".join(sections)


async def _merge_llm_synthesize(results: list[dict], user_message: str) -> str:
    """Use a lightweight LLM call to weave outputs into one coherent response."""
    # Build the prompt with all agent outputs
    agent_sections: list[str] = []
    for r in results:
        agent_name = r["agent"]
        label = ROLE_HEADERS.get(agent_name, agent_name.title())
        agent_sections.append(
            f"### Agent: {agent_name} ({label})\n{r['response']}"
        )

    user_prompt = (
        f"Student's original question:\n\"{user_message}\"\n\n"
        f"Below are outputs from {len(results)} specialist agents. "
        f"Merge them into ONE coherent, well-structured response.\n\n"
        + "\n\n---\n\n".join(agent_sections)
    )

    try:
        from services.llm.router import get_llm_client

        client = get_llm_client("small")
        merged_response, usage = await client.extract(
            _SYNTHESIZE_SYSTEM_PROMPT,
            user_prompt,
        )
        merged_response = merged_response.strip()

        if merged_response and len(merged_response) > 20:
            logger.info(
                "LLM synthesis merge complete: %d agents -> %d chars (tokens: %s)",
                len(results),
                len(merged_response),
                usage,
            )
            return merged_response
        else:
            logger.warning("LLM synthesis returned empty/short result, falling back to concatenate")
            return _merge_concatenate(results)

    except Exception as e:
        logger.warning(
            "LLM synthesis merge failed, falling back to concatenate: %s", e,
        )
        return _merge_concatenate(results)


def _merge_structured(results: list[dict]) -> str:
    """Attempt JSON-based structured merge; fall back to concatenation.

    Tries to parse each agent response as JSON and merges into a single
    dict keyed by agent name.  If any response is not valid JSON, falls
    back to concatenation for the entire result.
    """
    merged: dict[str, Any] = {}
    all_json = True

    for r in results:
        agent_name = r["agent"]
        response = r["response"].strip()

        try:
            parsed = json.loads(response)
            merged[agent_name] = parsed
        except (json.JSONDecodeError, TypeError):
            all_json = False
            break

    if all_json and merged:
        try:
            return json.dumps(merged, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            pass

    # Fallback: not all responses are JSON
    return _merge_concatenate(results)
