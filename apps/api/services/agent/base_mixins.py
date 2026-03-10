"""Mixin classes extracted from BaseAgent for delegation and background tasks.

These mixins are composed into BaseAgent via multiple inheritance.
Prompt building is in prompt_builder.py.
"""

import asyncio
import logging
import time
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class DelegationMixin:
    """Parallel delegation (swarm pattern) for multi-agent fan-out."""

    name: str  # provided by BaseAgent

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
                logger.exception(
                    "Parallel branch '%s' failed: %s", agent_name, e,
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


class BackgroundTaskMixin:
    """Background task spawning via the activity engine."""

    name: str  # provided by BaseAgent

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
        except (SQLAlchemyError, ValueError, KeyError, TypeError, ConnectionError, TimeoutError, RuntimeError) as e:
            logger.exception("Failed to spawn background task '%s': %s", title, e)
            return None
