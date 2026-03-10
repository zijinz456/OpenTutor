"""Prompt building mixin for BaseAgent.

Extracted from base.py: system prompt construction with template rendering,
memory formatting, tutor notes, and fallback Python-based prompt assembly.
"""

import logging

from services.agent.state import AgentContext

logger = logging.getLogger(__name__)


class PromptBuildingMixin:
    """System prompt construction helpers for agents."""

    name: str  # provided by BaseAgent
    profile: str  # provided by BaseAgent

    def _build_memory_text(self, ctx: AgentContext) -> str:
        """Build a formatted memory section from ctx.memories for template use."""
        if not ctx.memories:
            return "No prior knowledge about this student yet."
        lines: list[str] = []
        profile_mems: list[str] = []
        preference_mems: list[str] = []
        history_mems: list[str] = []
        for mem in ctx.memories:
            mtype = mem.get("memory_type", "")
            summary = mem.get("summary", "")
            if not summary:
                continue
            if mtype == "profile":
                profile_mems.append(summary)
            elif mtype == "preference":
                preference_mems.append(summary)
            else:
                history_mems.append(summary)
        if profile_mems:
            lines.append("### Student Profile")
            for s in profile_mems:
                lines.append(f"- {s}")
        if history_mems:
            lines.append("### Learning History")
            for s in history_mems:
                lines.append(f"- {s}")
        if preference_mems:
            lines.append("### Known Preferences")
            for s in preference_mems:
                lines.append(f"- {s}")
        return "\n".join(lines) if lines else "No prior knowledge about this student yet."

    def _build_tutor_notes_text(self, ctx: AgentContext) -> str:
        """Build tutor notes section from ctx.metadata for template use."""
        tutor_notes = ctx.metadata.get("tutor_notes")
        if tutor_notes:
            return f"## Tutor Notes (Your Private Observations)\n{tutor_notes}"
        return ""

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Build agent-specific system prompt with context + scene behavior injection.

        Tries file-based prompt template first (from prompts/{name}.md),
        falling back to the original Python-based prompt construction.
        """
        from services.agent.prompt_loader import render_prompt

        # --- File-based template path (preferred) ---
        template_result = render_prompt(
            self.name,
            course_name=ctx.metadata.get("course_name", "Unknown"),
            scene=ctx.scene or "study_session",
            memory_section=self._build_memory_text(ctx),
            tutor_notes_section=self._build_tutor_notes_text(ctx),
        )
        if template_result is not None:
            return template_result

        # --- Fallback: original Python-based prompt construction ---
        return self._build_fallback_prompt(ctx)

    def _build_fallback_prompt(self, ctx: AgentContext) -> str:
        """Build system prompt via Python string assembly (legacy path)."""
        parts = [self.profile]
        parts.append(f"\n## User Goal\n{ctx.user_message}")

        # Preference injection
        if ctx.preferences:
            pref_lines = [f"- {k}: {v}" for k, v in ctx.preferences.items()]
            parts.append(f"\n## Preferences\n" + "\n".join(pref_lines))

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
            preference_mems: list[str] = []
            history_mems: list[str] = []
            for mem in ctx.memories:
                mtype = mem.get("memory_type", "")
                summary = mem.get("summary", "")
                if not summary:
                    continue
                if mtype == "profile":
                    profile_mems.append(summary)
                elif mtype == "preference":
                    preference_mems.append(summary)
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
            if preference_mems:
                parts.append("\n## Known Preferences")
                for s in preference_mems:
                    parts.append(f"- {s}")

        # Tutor notes (private evolving observations about the student)
        tutor_notes = ctx.metadata.get("tutor_notes")
        if tutor_notes:
            parts.append(f"\n## Tutor Notes (Your Private Observations)\n{tutor_notes}")

        # Auto-learned teaching strategies (Claudeception pattern)
        teaching_strategies = ctx.metadata.get("teaching_strategies")
        if teaching_strategies:
            strat_lines = ["## Personalized Teaching Strategies (auto-learned)"]
            for s in teaching_strategies[:5]:
                stype = s.get("type", "").replace("_", " ").title()
                desc = s.get("description", "")
                topic = s.get("topic", "")
                strat_lines.append(f"- [{stype}] {desc}" + (f" (Topic: {topic})" if topic else ""))
            parts.append("\n".join(strat_lines))

        # Pre-task clarification context (OpenClaw Inputs pattern)
        if ctx.clarify_inputs:
            clarify_lines = ["## Student's Preferences for This Task"]
            for k, v in ctx.clarify_inputs.items():
                clarify_lines.append(f"- {k.replace('_', ' ').title()}: {v}")
            parts.append("\n".join(clarify_lines))

        recent_task_context = ctx.metadata.get("recent_task_context") or ctx.metadata.get("plan_progress")
        if recent_task_context:
            parts.append(f"\n## Recent Task Context\n{recent_task_context}")

        # Match and inject teaching strategies
        try:
            from services.agent.skills import match_skills
            matched = match_skills(ctx.user_message, scene=ctx.scene, limit=2)
            if matched:
                skills_text = "\n\n".join(s.content for s in matched)
                parts.append(f"\n## Teaching Strategies\n{skills_text}")
        except (ImportError, FileNotFoundError, ValueError) as e:
            logger.exception("Skills matching skipped: %s", e)

        # Phase 4: Experiment strategy override -- inject variant-specific skill
        exp_config = ctx.metadata.get("experiment_config")
        if exp_config:
            fatigue_score = ctx.metadata.get("fatigue_score", 0.0)
            strategy_name = exp_config.get("config", {}).get("skill_name")
            # Socratic guardrail: suppress if student is frustrated
            if strategy_name == "socratic_questioning" and fatigue_score > 0.5:
                logger.info("Socratic guardrail: suppressing for frustrated student (fatigue=%.2f)", fatigue_score)
            elif strategy_name:
                try:
                    from services.agent.skills import load_skills
                    for s in load_skills():
                        if s.name == strategy_name:
                            parts.append(f"\n## Active Teaching Strategy\n{s.content}")
                            break
                except (ImportError, FileNotFoundError, ValueError) as e:
                    logger.exception("Experiment strategy skill injection skipped: %s", e)

        # Phase 4: Cross-course concept connections
        cross_patterns = ctx.metadata.get("cross_course_patterns")
        if cross_patterns:
            lines = ["## Cross-Course Connections (from your other courses)"]
            for p in cross_patterns[:3]:
                courses_str = ", ".join(c.get("course_name", "?") for c in p.get("courses", []))
                lines.append(f"- Topic '{p.get('topic', '?')}' appears in: {courses_str}")
            parts.append("\n".join(lines))

        return "\n".join(parts)
