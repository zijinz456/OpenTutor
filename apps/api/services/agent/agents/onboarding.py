"""OnboardingAgent — conducts a brief learning habit interview.

Extracts a LearnerProfile via [PROFILE:{...}] markers in the response
(same pattern as LayoutAgent's [ACTION:...] markers), then maps it to
a recommended block layout.

Architecture patterns:
- Marker-based extraction (LayoutAgent pattern, compatible with local LLMs)
- Pre-action clarification loop (PAHF pattern)
- Progressive profile accumulation (Mem0 reconciliation, simplified)
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.learner_profile import LearnerProfile
from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)

_PROFILE_MARKER_RE = re.compile(r"\[PROFILE:(.*?)\]", re.DOTALL)

_ONBOARDING_SYSTEM = """\
You are a learning style analyst. Conduct a brief, friendly onboarding interview
(2-3 questions) to understand the user's study habits, then extract a structured
learner profile.

## Interview strategy
1. Ask ONE open-ended question about how they usually study.
2. Based on the answer, ask 1-2 targeted follow-ups (e.g. time per session,
   visual vs text preference, whether they do practice problems).
3. Once you have enough signal, emit a [PROFILE:{{...}}] JSON block AND present
   the recommendation in a friendly message.

## Extraction mapping
Map user descriptions to profile fields:
- "笔记/notes/summarize/write down" -> prefers_note_taking=true
- "思维导图/mind map/diagram/visual/图表" -> prefers_visual_aids=true
- "做题/quiz/practice/exercise/test/刷题" -> prefers_active_recall=true
- "复习/review/spaced repetition/revisit/温习" -> prefers_spaced_review=true
- "错题/mistakes/wrong answers/error analysis" -> prefers_mistake_analysis=true
- "计划/plan/schedule/organize/制定" -> prefers_planning=true
- "短时间/quick/15-30 min/<30分钟" -> session_duration="short"
- "1小时/hour/long session/>60分钟" -> session_duration="long"
- "考试/exam/test/deadline/期末" -> study_pattern="exam_driven"
- "自由/explore/curious/interest/兴趣" -> study_pattern="exploratory"
- "复习为主/consolidate/maintain" -> study_pattern="review_focused"
- "按计划/step by step/structured/有条理" -> study_pattern="structured"
- "图/visual/看图" -> learning_style="visual"
- "读/read/text/看书" -> learning_style="reading"
- "动手/hands-on/做/practice-first" -> learning_style="kinesthetic"

## [PROFILE:{{...}}] format
When you have enough information, emit EXACTLY ONE marker containing a JSON object
with these fields (all optional, omit fields you have no signal for):

[PROFILE:{{"preferences":{{"prefers_visual_aids":true,"prefers_note_taking":true,...}},\
"behavior":{{"session_duration":"medium","study_pattern":"structured","learning_style":"visual"}},\
"raw_description":"user's own words summarized","confidence":0.8,\
"learning_goal":"pass final exam","background_level":"intermediate"}}]

## Rules
- Detect and respond in the user's language.
- Keep questions casual and concise (1-2 sentences max).
- Only emit [PROFILE:...] when you have enough signal (at least 2 exchanges).
- For an empty initial message, ask the first question immediately.
- After emitting [PROFILE:...], describe the recommended blocks in a friendly way.
- Do NOT emit [PROFILE:...] more than once per conversation.
- Set confidence: 0.9 for direct statements, 0.7 for implied, 0.5 for weak signal.
"""


class OnboardingAgent(BaseAgent):
    """Conducts a brief learning habit interview and recommends a block layout."""

    name = "onboarding"
    profile = "A learning style analyst that interviews users about study habits."
    model_preference = "small"

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Run one turn of the interview."""
        client = self.get_llm_client(ctx)
        partial_profile = ctx.metadata.get("learner_profile", {})

        # Build conversation for the LLM
        system = _ONBOARDING_SYSTEM
        if partial_profile:
            system += (
                "\n\n## Previously extracted (update, don't overwrite unless "
                f"contradicted):\n{json.dumps(partial_profile, ensure_ascii=False)}"
            )

        # Flatten conversation history + current message into user content
        user_content = _build_user_content(ctx.conversation_history, ctx.user_message)

        response_text, _ = await client.chat(system, user_content)

        # Extract [PROFILE:{...}] if present
        profile_match = _PROFILE_MARKER_RE.search(response_text)
        if profile_match:
            try:
                profile_data = json.loads(profile_match.group(1))
                # Merge with existing partial profile
                merged = _deep_merge(partial_profile, profile_data)
                profile = LearnerProfile(**merged)

                from services.block_decision.profile_mapper import profile_to_layout

                layout = profile_to_layout(profile)

                ctx.metadata["learner_profile"] = profile.model_dump(mode="json")
                ctx.metadata["recommended_layout"] = layout
                ctx.metadata["onboarding_complete"] = True

                ctx.actions.append({
                    "type": "recommend_layout",
                    "layout": layout,
                    "profile_summary": {
                        "style": profile.behavior.learning_style,
                        "pattern": profile.behavior.study_pattern,
                        "duration": profile.behavior.session_duration,
                    },
                })
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to parse [PROFILE:...] marker: %s", exc)

            # Strip the marker from visible response
            response_text = _PROFILE_MARKER_RE.sub("", response_text).strip()

        ctx.response = response_text
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Streaming variant — collects full response, extracts profile, then yields."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        client = self.get_llm_client(ctx)
        partial_profile = ctx.metadata.get("learner_profile", {})

        system = _ONBOARDING_SYSTEM
        if partial_profile:
            system += (
                "\n\n## Previously extracted:\n"
                f"{json.dumps(partial_profile, ensure_ascii=False)}"
            )

        user_content = _build_user_content(ctx.conversation_history, ctx.user_message)

        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system, user_content):
            full_response += chunk
            # Don't yield marker text — buffer until we can strip it
            # We yield the cleaned response after streaming completes

        # Extract profile marker
        profile_match = _PROFILE_MARKER_RE.search(full_response)
        if profile_match:
            try:
                profile_data = json.loads(profile_match.group(1))
                merged = _deep_merge(partial_profile, profile_data)
                profile = LearnerProfile(**merged)

                from services.block_decision.profile_mapper import profile_to_layout

                layout = profile_to_layout(profile)

                ctx.metadata["learner_profile"] = profile.model_dump(mode="json")
                ctx.metadata["recommended_layout"] = layout
                ctx.metadata["onboarding_complete"] = True

                ctx.actions.append({
                    "type": "recommend_layout",
                    "layout": layout,
                    "profile_summary": {
                        "style": profile.behavior.learning_style,
                        "pattern": profile.behavior.study_pattern,
                        "duration": profile.behavior.session_duration,
                    },
                })
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to parse [PROFILE:...] marker: %s", exc)

            full_response = _PROFILE_MARKER_RE.sub("", full_response).strip()

        ctx.response = full_response
        yield full_response


def _build_user_content(history: list[dict], current_message: str) -> str:
    """Flatten conversation history into a single user prompt."""
    parts: list[str] = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            parts.append(f"Student: {content}")
        else:
            parts.append(f"You: {content}")
    if current_message:
        parts.append(f"Student: {current_message}")
    else:
        parts.append("Student: (new conversation — ask your first question)")
    return "\n".join(parts)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, preferring override values."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
