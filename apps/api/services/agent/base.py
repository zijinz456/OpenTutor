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

from services.agent.state import AgentContext, TaskPhase

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

    def get_llm_client(self):
        """Get LLM client respecting model_preference.

        Maps model_preference to provider selection:
        - "large": use primary provider (best model)
        - "small": try lightweight/cheaper provider first
        - None: use default
        """
        from services.llm.router import get_llm_client
        # model_preference is a hint; the registry decides the actual provider
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

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream response chunks for SSE. Default: run then yield full response."""
        ctx = await self.run(ctx, db)
        if ctx.response:
            yield ctx.response

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Build agent-specific system prompt with context + scene behavior injection."""
        from services.agent.scene_behavior import get_scene_with_tab_context

        parts = [self.profile]
        parts.append(f"\n## User Goal\n{ctx.user_message}")

        # v3: Scene-aware behavior rules
        scene_section = get_scene_with_tab_context(ctx.scene, ctx.active_tab, ctx.tab_context)
        parts.append(f"\n## Scene Policy\n{scene_section}")

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

        # Memory context
        if ctx.memories:
            parts.append("\n## Memory\n")
            for mem in ctx.memories:
                parts.append(f"- {mem.get('summary', '')}")

        recent_task_context = ctx.metadata.get("recent_task_context") or ctx.metadata.get("plan_progress")
        if recent_task_context:
            parts.append(f"\n## Recent Task Context\n{recent_task_context}")

        return "\n".join(parts)
