"""Prompt building mixin for BaseAgent.

Extracted from base.py: Python-based system prompt assembly with context
injection (preferences, course materials, memories, teaching strategies).
"""

import logging

from services.agent.state import AgentContext

logger = logging.getLogger(__name__)


class PromptBuildingMixin:
    """System prompt construction helpers for agents."""

    name: str  # provided by BaseAgent
    profile: str  # provided by BaseAgent

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Build agent-specific system prompt with context + scene behavior injection."""
        parts = [self.profile]
        parts.append(f"\n## User Goal\n{ctx.user_message}")

        # Known preferences: the resolved user_preferences store — the same
        # store the save_user_preference tool and the implicit extractor write.
        if ctx.preferences:
            pref_lines = [f"- {k}: {v}" for k, v in ctx.preferences.items()]
            parts.append("\n## Known Preferences\n" + "\n".join(pref_lines))

        # RAG context with source metadata for citations
        if ctx.content_docs:
            parts.append("\n## Course Materials\n")
            parts.append(
                "These sections were auto-retrieved. Use search_content only if you need different material.\n"
                "IMPORTANT: When using information from these materials, cite the source using the format "
                "[Source: <source_file>] or [Source: <title>]. Include citations inline in your response.\n"
            )
            for i, doc in enumerate(ctx.content_docs, 1):
                source = doc.get("source_file") or "course material"
                title = doc.get("title", "")
                parts.append(f"### [{i}] {title}")
                parts.append(f"**Source:** {source}")
                parts.append(f"{doc.get('content', '')[:1500]}\n")

        # Memory context -- organized by type for clarity
        if ctx.memories:
            profile_mems: list[str] = []
            history_mems: list[str] = []
            for mem in ctx.memories:
                mtype = mem.get("memory_type", "")
                summary = mem.get("summary", "")
                if not summary:
                    continue
                if mtype == "profile":
                    profile_mems.append(summary)
                else:
                    history_mems.append(summary)

            if profile_mems:
                parts.append("\n## Student Profile")
                for s in profile_mems:
                    parts.append(f"- {s}")
            if history_mems:
                parts.append("\n## Learning History")
                for s in history_mems:
                    parts.append(f"- {s}")

        # Tutor notes (private evolving observations about the student)
        tutor_notes = ctx.metadata.get("tutor_notes")
        if tutor_notes:
            parts.append(f"\n## Tutor Notes (Your Private Observations)\n{tutor_notes}")

        # Pre-task clarification context (OpenClaw Inputs pattern)
        if ctx.clarify_inputs:
            clarify_lines = ["## Student's Preferences for This Task"]
            for k, v in ctx.clarify_inputs.items():
                clarify_lines.append(f"- {k.replace('_', ' ').title()}: {v}")
            parts.append("\n".join(clarify_lines))

        recent_task_context = ctx.metadata.get("recent_task_context") or ctx.metadata.get("plan_progress")
        if recent_task_context:
            parts.append(f"\n## Recent Task Context\n{recent_task_context}")

        # Teaching strategies: ONE section — skills/*.md selected by the
        # message/scene, then strategies auto-learned for this student (DB).
        strategy_blocks: list[str] = []
        try:
            from services.agent.skills import match_skills
            matched = match_skills(ctx.user_message, scene=ctx.scene, limit=2)
            if matched:
                strategy_blocks.append("\n\n".join(s.content for s in matched))
        except (ImportError, FileNotFoundError, ValueError) as e:
            logger.exception("Skills matching skipped: %s", e)
        teaching_strategies = ctx.metadata.get("teaching_strategies")
        if teaching_strategies:
            strat_lines = ["### Learned for this student"]
            for s in teaching_strategies[:5]:
                stype = s.get("type", "").replace("_", " ").title()
                desc = s.get("description", "")
                topic = s.get("topic", "")
                strat_lines.append(f"- [{stype}] {desc}" + (f" (Topic: {topic})" if topic else ""))
            strategy_blocks.append("\n".join(strat_lines))
        if strategy_blocks:
            parts.append("\n## Teaching Strategies\n" + "\n\n".join(strategy_blocks))

        # Phase 4: Cross-course concept connections
        cross_patterns = ctx.metadata.get("cross_course_patterns")
        if cross_patterns:
            lines = ["## Cross-Course Connections (from your other courses)"]
            for p in cross_patterns[:3]:
                courses_str = ", ".join(c.get("course_name", "?") for c in p.get("courses", []))
                lines.append(f"- Topic '{p.get('topic', '?')}' appears in: {courses_str}")
            parts.append("\n".join(lines))

        return "\n".join(parts)
