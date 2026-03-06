"""Base agent class for the multi-agent architecture.

Borrows from:
- MetaGPT Role: profile / goal / constraints pattern
- HelloAgents ReActAgent: Thought → Action → Observation loop
- OpenClaw agent-scope: independent workspace, model config, memory config
"""

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, InputRequirement, TaskPhase

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all specialist agents.

    Each agent has:
    - name: unique identifier
    - profile: role description (MetaGPT pattern)
    - system_prompt_template: customizable per-agent prompt
    - model_preference: different agents can use different model sizes
    """

    name: str = "base"
    profile: str = "A generic learning assistant agent."
    model_preference: str | None = None  # None = use default, "small" / "large"

    def get_required_inputs(self) -> list[InputRequirement]:
        """Return input requirements for pre-task questioning. Override in subclasses."""
        return []

    def get_llm_client(self, ctx: AgentContext | None = None):
        """Get LLM client with 3-tier complexity routing when context is available.

        When ctx is provided, uses complexity scoring to select fast/standard/frontier.
        Falls back to legacy model_preference ("large"/"small") when ctx is None.
        """
        from services.llm.router import get_llm_client

        if ctx is not None:
            from services.llm.complexity import resolve_tier

            tier = resolve_tier(
                agent_name=self.name,
                message=ctx.user_message,
                intent=ctx.intent.value if ctx.intent else "general",
                scene=ctx.scene or "study_session",
                history_length=len(ctx.conversation_history),
                has_rag_context=bool(ctx.content_docs),
            )
            return get_llm_client(tier.value)

        # Legacy fallback
        return get_llm_client(self.model_preference)

    async def run(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Execute the agent's task. Template method pattern."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        try:
            ctx = await self.execute(ctx, db)
            return ctx
        except Exception as e:
            logger.error("Agent %s failed: %s", self.name, e, exc_info=True)
            ctx.mark_failed(str(e))
            return ctx

    @abstractmethod
    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Agent-specific execution logic. Subclasses must implement."""
        ...

    async def delegate(
        self,
        target_agent_name: str,
        sub_message: str,
        ctx: AgentContext,
        db: AsyncSession,
    ) -> str:
        """Delegate a sub-task to another specialist agent.

        Returns the sub-agent's response text. The delegation is tracked
        in ctx.metadata for observability.
        """
        from services.agent.registry import AGENT_REGISTRY

        target = AGENT_REGISTRY.get(target_agent_name)
        if not target:
            logger.warning("Delegation target '%s' not found", target_agent_name)
            return f"[delegation failed: unknown agent '{target_agent_name}']"

        # Capability escalation check
        from services.agent.capabilities import check_delegation_escalation

        allowed, reason = check_delegation_escalation(self.name, target_agent_name)
        if not allowed:
            logger.warning("Delegation blocked: %s → %s: %s", self.name, target_agent_name, reason)
            return f"[delegation blocked: {reason}]"

        # Create a sub-context preserving identity but with new message
        sub_ctx = AgentContext(
            user_id=ctx.user_id,
            course_id=ctx.course_id,
            user_message=sub_message,
            preferences=ctx.preferences,
            content_docs=ctx.content_docs,
            memories=ctx.memories,
            scene=ctx.scene,
        )

        logger.info("Agent '%s' delegating to '%s'", self.name, target_agent_name)
        sub_ctx = await target.run(sub_ctx, db)

        # Track delegation chain
        delegations = ctx.metadata.setdefault("delegations", [])
        delegations.append({
            "from": self.name,
            "to": target_agent_name,
            "message": sub_message[:200],
            "response_length": len(sub_ctx.response),
        })

        return sub_ctx.response

    async def delegate_parallel(
        self,
        delegations: list[dict],
        ctx: AgentContext,
        db_factory,
        timeout: float = 30.0,
    ) -> list[dict]:
        """Fan-out sub-tasks to multiple agents in parallel (swarm pattern).

        Each delegation dict: {"agent": str, "message": str, "timeout": float (optional)}

        Each branch gets an independent AsyncSession from db_factory() so there
        are no shared-connection conflicts.  Results (including per-branch errors)
        are collected via asyncio.gather(return_exceptions=True).

        Returns a list of result dicts and also stores them in
        ctx.parallel_branches and ctx.metadata["delegations"].
        """
        from services.agent.registry import AGENT_REGISTRY

        ctx.transition(TaskPhase.PARALLEL_DISPATCH)
        ctx.swarm_mode = True

        async def _run_branch(delegation: dict) -> dict:
            agent_name = delegation["agent"]
            message = delegation["message"]
            branch_timeout = delegation.get("timeout", timeout)
            start = time.monotonic()

            target = AGENT_REGISTRY.get(agent_name)
            if not target:
                return {
                    "agent": agent_name,
                    "response": f"[parallel delegation failed: unknown agent '{agent_name}']",
                    "success": False,
                    "error": f"unknown agent '{agent_name}'",
                    "tokens": 0,
                    "duration_ms": 0.0,
                    "tool_calls": [],
                }

            # Each branch gets its own context and DB session
            sub_ctx = AgentContext(
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                conversation_id=ctx.conversation_id,
                session_id=uuid.uuid4(),
                user_message=message,
                preferences=ctx.preferences.copy(),
                preference_sources=ctx.preference_sources.copy(),
                content_docs=list(ctx.content_docs),
                memories=list(ctx.memories),
                scene=ctx.scene,
                intent=ctx.intent,
                conversation_history=list(ctx.conversation_history),
                difficulty_guidance=ctx.difficulty_guidance,
            )

            try:
                async with db_factory() as branch_db:
                    sub_ctx = await asyncio.wait_for(
                        target.run(sub_ctx, branch_db),
                        timeout=branch_timeout,
                    )
                elapsed = (time.monotonic() - start) * 1000
                return {
                    "agent": agent_name,
                    "response": sub_ctx.response,
                    "success": sub_ctx.phase != TaskPhase.FAILED,
                    "error": sub_ctx.error,
                    "tokens": sub_ctx.total_tokens,
                    "duration_ms": round(elapsed, 1),
                    "tool_calls": sub_ctx.tool_calls,
                }
            except asyncio.TimeoutError:
                elapsed = (time.monotonic() - start) * 1000
                return {
                    "agent": agent_name,
                    "response": "",
                    "success": False,
                    "error": f"timeout after {branch_timeout}s",
                    "tokens": 0,
                    "duration_ms": round(elapsed, 1),
                    "tool_calls": [],
                }
            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                logger.error(
                    "Parallel branch '%s' failed: %s", agent_name, e, exc_info=True,
                )
                return {
                    "agent": agent_name,
                    "response": "",
                    "success": False,
                    "error": str(e),
                    "tokens": 0,
                    "duration_ms": round(elapsed, 1),
                    "tool_calls": [],
                }

        # Fan-out: launch all branches concurrently
        logger.info(
            "Agent '%s' dispatching %d parallel branches: %s",
            self.name,
            len(delegations),
            [d["agent"] for d in delegations],
        )

        tasks = [_run_branch(d) for d in delegations]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Normalize: gather with return_exceptions=True may return Exception objects
        results: list[dict] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                agent_name = delegations[i]["agent"]
                logger.error(
                    "Parallel branch '%s' raised unhandled exception: %s",
                    agent_name, result,
                )
                results.append({
                    "agent": agent_name,
                    "response": "",
                    "success": False,
                    "error": str(result),
                    "tokens": 0,
                    "duration_ms": 0.0,
                    "tool_calls": [],
                })
            else:
                results.append(result)

        # Track results in parent context
        ctx.parallel_branches = results
        delegations_log = ctx.metadata.setdefault("delegations", [])
        for r in results:
            delegations_log.append({
                "from": self.name,
                "to": r["agent"],
                "success": r["success"],
                "error": r.get("error"),
                "tokens": r["tokens"],
                "duration_ms": r["duration_ms"],
                "response_length": len(r.get("response", "")),
            })

        # Aggregate token usage from branches
        ctx.total_tokens += sum(r["tokens"] for r in results)

        successful = sum(1 for r in results if r["success"])
        logger.info(
            "Parallel dispatch complete: %d/%d branches succeeded (%.0fms total)",
            successful,
            len(results),
            sum(r["duration_ms"] for r in results),
        )

        return results

    async def spawn_background_task(
        self,
        ctx: AgentContext,
        db: AsyncSession,
        task_type: str,
        title: str,
        payload: dict | None = None,
    ) -> uuid.UUID | None:
        """Spawn a background task via the activity engine.

        Creates an AgentTask record that the activity engine will pick up
        and execute asynchronously. Returns the task ID or None on failure.
        """
        try:
            from services.activity.engine import submit_task

            task = await submit_task(
                db=db,
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                task_type=task_type,
                title=title,
                input_json=payload or {},
                source="agent",
            )
            spawned = ctx.metadata.setdefault("spawned_tasks", [])
            spawned.append({"task_id": str(task.id), "type": task_type, "title": title})
            logger.info("Agent '%s' spawned background task: %s (%s)", self.name, title, task.id)
            return task.id
        except Exception as e:
            logger.warning("Failed to spawn background task '%s': %s", title, e)
            return None

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream response chunks for SSE. Default: run then yield full response."""
        ctx = await self.run(ctx, db)
        if ctx.response:
            yield ctx.response

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
        parts = [self.profile]
        parts.append(f"\n## User Goal\n{ctx.user_message}")

        # Preference injection
        if ctx.preferences:
            pref_lines = [f"- {k}: {v}" for k, v in ctx.preferences.items()]
            parts.append(f"\n## Preferences\n" + "\n".join(pref_lines))

        # RAG context
        if ctx.content_docs:
            parts.append("\n## Course Materials\n")
            parts.append("These sections were auto-retrieved. Use search_content only if you need different material.\n")
            for doc in ctx.content_docs:
                parts.append(f"### {doc.get('title', '')}\n{doc.get('content', '')[:1500]}\n")

        # Memory context — organized by type for clarity
        if ctx.memories:
            # Group memories by type
            profile_mems = []
            preference_mems = []
            history_mems = []  # episode, knowledge, skill, error, fact, conversation
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
        except Exception as e:
            logger.debug("Skills matching skipped: %s", e)

        # Phase 4: Experiment strategy override — inject variant-specific skill
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
                except Exception as e:
                    logger.debug("Experiment strategy skill injection skipped: %s", e)

        # Phase 4: Cross-course concept connections
        cross_patterns = ctx.metadata.get("cross_course_patterns")
        if cross_patterns:
            lines = ["## Cross-Course Connections (from your other courses)"]
            for p in cross_patterns[:3]:
                courses_str = ", ".join(c.get("course_name", "?") for c in p.get("courses", []))
                lines.append(f"- Topic '{p.get('topic', '?')}' appears in: {courses_str}")
            parts.append("\n".join(lines))

        return "\n".join(parts)
