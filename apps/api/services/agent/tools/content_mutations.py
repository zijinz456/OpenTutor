"""Content mutation tools — let agents proactively modify learning content.

These tools enable the agent system to:
- Rewrite AI-generated notes based on student performance
- Add targeted practice problems for weak areas
- Annotate content sections with warnings/tips
- Lock/unlock content to prevent/allow AI modifications

Write tools follow the same patterns as education.py:
- Use db.flush() (not commit) — orchestrator commits atomically after streaming.
- Support idempotency via ToolCategory.WRITE base-class dedup.
- Emit ctx.emit_progress() events for frontend progress display.
- Emit ctx.actions for frontend section refresh after successful flush.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)


@tool(
    name="update_section_notes",
    description=(
        "Rewrite the AI-generated portions of a content section's notes. "
        "User-edited and locked blocks are preserved unchanged. "
        "Creates a snapshot before changes for rollback. "
        "Use when a student is struggling with a topic and the current notes are insufficient."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("node_id", "string", "UUID of the content node to rewrite."),
        param("reason", "string", "Why the rewrite is needed (e.g., 'student struggling with this topic')."),
    ],
)
async def update_section_notes(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        from models.content import CourseContentTree
        from services.content.mutations import save_snapshot, record_mutation, update_node_blocks
        from services.content.block_utils import (
            separate_blocks_by_owner, merge_rewritten_blocks,
            markdown_to_blocks, ensure_block_metadata,
        )

        node_id = parameters.get("node_id", "").strip()
        reason = parameters.get("reason", "").strip()
        if not node_id:
            return ToolResult(success=False, output="", error="node_id is required.")

        import uuid
        node = await db.get(CourseContentTree, uuid.UUID(node_id))
        if not node:
            return ToolResult(success=False, output="", error=f"Content node {node_id} not found.")
        if node.course_id != ctx.course_id:
            return ToolResult(success=False, output="", error="Node does not belong to current course.")

        ctx.emit_progress("update_section_notes", "Saving snapshot...", step=1, total=4)

        # Save snapshot before mutation
        snapshot = await save_snapshot(db, node.id, snapshot_type="before_agent_update")

        ctx.emit_progress("update_section_notes", "Analyzing content...", step=2, total=4)

        # Get current blocks (or convert from markdown for legacy nodes)
        current_blocks = node.blocks_json or markdown_to_blocks(node.content or "")
        if not current_blocks:
            return ToolResult(success=True, output="Node has no content to rewrite.")

        # Separate AI-owned blocks from user/locked blocks
        replaceable, preserved = separate_blocks_by_owner(current_blocks)
        if not replaceable:
            return ToolResult(success=True, output="All content is user-edited or locked. No AI blocks to rewrite.")

        ctx.emit_progress("update_section_notes", "Rewriting notes...", step=3, total=4)

        # Extract text from replaceable blocks for rewriting
        ai_text = "\n".join(
            item.get("text", "")
            for block in replaceable
            for item in (block.get("content") or [])
            if isinstance(item, dict)
        )

        # Use LLM to rewrite the AI content
        from services.agent.base import BaseAgent
        agent = BaseAgent()
        client = agent.get_llm_client(ctx)
        rewrite_prompt = (
            f"Rewrite the following study notes to be clearer, more detailed, and easier to understand.\n"
            f"Reason for rewrite: {reason}\n"
            f"Section title: {node.title}\n\n"
            f"Original notes:\n{ai_text}\n\n"
            f"Provide improved notes in markdown format. Keep the same topic coverage but improve clarity."
        )
        rewritten_md, _ = await client.chat(
            "You are a study notes editor. Rewrite notes to be clearer and more helpful.",
            rewrite_prompt,
        )

        # Convert rewritten markdown to blocks
        rewritten_blocks = markdown_to_blocks(rewritten_md)
        for block in rewritten_blocks:
            ensure_block_metadata(block)

        # Merge back with preserved blocks
        merged = merge_rewritten_blocks(current_blocks, rewritten_blocks, preserved)

        # Update the node
        await update_node_blocks(db, node, merged)

        # Record mutation
        await record_mutation(
            db, node.id,
            mutation_type="rewrite_notes",
            reason=reason,
            diff_summary=f"Rewrote {len(replaceable)} AI blocks, preserved {len(preserved)} user blocks",
            snapshot_id=snapshot.id,
            agent_name=ctx.delegated_agent or "tutor",
        )

        ctx.emit_progress("update_section_notes", "Done", step=4, total=4)
        ctx.actions.append({"action": "content_mutated", "value": node_id})

        return ToolResult(
            success=True,
            output=f"Rewrote notes for '{node.title}': {len(replaceable)} blocks updated, {len(preserved)} preserved.",
        )
    except Exception as e:
        await db.rollback()
        logger.error("update_section_notes failed: %s", e, exc_info=True)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="add_targeted_practice",
    description=(
        "Generate practice problems targeted at the student's weak points for a specific section. "
        "Analyzes wrong answer patterns to create focused exercises. "
        "Use when a student has repeated errors or low mastery on a topic."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("node_id", "string", "UUID of the content node to generate practice for."),
        param("count", "integer", "Number of problems to generate (1-5).", required=False, default=3),
        param("difficulty", "integer", "Difficulty layer 1-3 (1=recall, 2=application, 3=trap).", required=False, default=2),
        param("reason", "string", "Why these problems are needed.", required=False),
    ],
)
async def add_targeted_practice(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        from models.content import CourseContentTree
        from models.practice import PracticeProblem
        from services.content.mutations import record_mutation

        import uuid
        node_id = parameters.get("node_id", "").strip()
        count = min(max(int(parameters.get("count", 3)), 1), 5)
        difficulty = min(max(int(parameters.get("difficulty", 2)), 1), 3)
        reason = parameters.get("reason", "")

        if not node_id:
            return ToolResult(success=False, output="", error="node_id is required.")

        node = await db.get(CourseContentTree, uuid.UUID(node_id))
        if not node:
            return ToolResult(success=False, output="", error=f"Content node {node_id} not found.")
        if node.course_id != ctx.course_id:
            return ToolResult(success=False, output="", error="Node does not belong to current course.")

        ctx.emit_progress("add_targeted_practice", f"Generating {count} problems...", step=1, total=3)

        # Get content for problem generation
        content = node.content or ""
        if not content:
            return ToolResult(success=True, output="Node has no content to generate problems from.")

        # Use LLM to generate problems
        from services.agent.base import BaseAgent
        agent = BaseAgent()
        client = agent.get_llm_client(ctx)

        difficulty_label = {1: "basic recall", 2: "application", 3: "trap/edge case"}
        prompt = (
            f"Generate {count} multiple-choice practice problems from the following content.\n"
            f"Difficulty: {difficulty_label.get(difficulty, 'standard')}\n"
            f"Topic: {node.title}\n\n"
            f"Content:\n{content[:4000]}\n\n"
            f"For each problem, provide:\n"
            f"1. question: The question text\n"
            f"2. options: A, B, C, D choices\n"
            f"3. correct_answer: The letter of the correct answer\n"
            f"4. explanation: Why the answer is correct\n\n"
            f"Format as JSON array of objects."
        )
        raw_response, _ = await client.chat(
            "You are a quiz generator. Output valid JSON arrays of practice problems.",
            prompt,
        )

        ctx.emit_progress("add_targeted_practice", "Saving problems...", step=2, total=3)

        # Parse and save problems
        import json
        try:
            # Try to extract JSON from response
            json_start = raw_response.find("[")
            json_end = raw_response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                problems_data = json.loads(raw_response[json_start:json_end])
            else:
                problems_data = []
        except json.JSONDecodeError:
            problems_data = []

        created = 0
        for p in problems_data[:count]:
            if not p.get("question"):
                continue
            options = p.get("options", {})
            if isinstance(options, list):
                options = {chr(65 + i): opt for i, opt in enumerate(options)}

            problem = PracticeProblem(
                course_id=ctx.course_id,
                content_node_id=node.id,
                question_type="mc",
                question=p["question"],
                options=options,
                correct_answer=p.get("correct_answer", "A"),
                explanation=p.get("explanation", ""),
                difficulty_layer=difficulty,
                source="ai_generated",
                source_owner="ai",
                locked=False,
                problem_metadata={"reason": reason, "targeted": True},
            )
            db.add(problem)
            created += 1

        if created:
            await db.flush()
            await record_mutation(
                db, node.id,
                mutation_type="add_practice",
                reason=reason or f"Added {created} targeted practice problems",
                diff_summary=f"Added {created} problems (difficulty={difficulty})",
                agent_name=ctx.delegated_agent or "tutor",
            )

        ctx.emit_progress("add_targeted_practice", "Done", step=3, total=3)
        ctx.actions.append({"action": "content_mutated", "value": node_id})

        return ToolResult(
            success=True,
            output=f"Added {created} targeted practice problems for '{node.title}' (difficulty={difficulty}).",
        )
    except Exception as e:
        await db.rollback()
        logger.error("add_targeted_practice failed: %s", e, exc_info=True)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="annotate_section",
    description=(
        "Add an inline annotation (warning, tip, or correction) to a content section. "
        "The annotation appears as a callout block within the section notes. "
        "Use to highlight common mistakes, exam tips, or important corrections."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("node_id", "string", "UUID of the content node to annotate."),
        param("annotation_text", "string", "The annotation content."),
        param("annotation_type", "string", "Type of annotation.",
              enum=["warning", "tip", "correction"]),
    ],
)
async def annotate_section(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        from models.content import CourseContentTree
        from services.content.mutations import save_snapshot, record_mutation, update_node_blocks
        from services.content.block_utils import create_annotation_block, markdown_to_blocks

        import uuid
        node_id = parameters.get("node_id", "").strip()
        text = parameters.get("annotation_text", "").strip()
        ann_type = parameters.get("annotation_type", "tip")

        if not node_id or not text:
            return ToolResult(success=False, output="", error="node_id and annotation_text are required.")

        node = await db.get(CourseContentTree, uuid.UUID(node_id))
        if not node:
            return ToolResult(success=False, output="", error=f"Content node {node_id} not found.")
        if node.course_id != ctx.course_id:
            return ToolResult(success=False, output="", error="Node does not belong to current course.")

        # Save snapshot
        snapshot = await save_snapshot(db, node.id, snapshot_type="before_agent_update")

        # Get current blocks
        current_blocks = node.blocks_json or markdown_to_blocks(node.content or "")

        # Create and append annotation block
        annotation = create_annotation_block(text, ann_type)
        current_blocks.append(annotation)

        # Update node
        await update_node_blocks(db, node, current_blocks)

        # Record mutation
        await record_mutation(
            db, node.id,
            mutation_type="annotate",
            reason=f"{ann_type}: {text[:100]}",
            diff_summary=f"Added {ann_type} annotation",
            snapshot_id=snapshot.id,
            agent_name=ctx.delegated_agent or "tutor",
        )

        ctx.actions.append({"action": "content_mutated", "value": node_id})

        return ToolResult(
            success=True,
            output=f"Added {ann_type} annotation to '{node.title}': {text[:100]}",
        )
    except Exception as e:
        await db.rollback()
        logger.error("annotate_section failed: %s", e, exc_info=True)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="lock_content",
    description=(
        "Lock a content node to prevent AI from modifying it. "
        "All blocks and associated practice problems become read-only for the AI. "
        "User can still edit manually."
    ),
    category=ToolCategory.WRITE,
    params=[param("node_id", "string", "UUID of the content node to lock.")],
)
async def lock_content(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    return await _toggle_lock(parameters, ctx, db, locked=True)


@tool(
    name="unlock_content",
    description=(
        "Unlock a content node to allow AI modifications again. "
        "Re-enables AI rewriting, annotation, and practice generation for this node."
    ),
    category=ToolCategory.WRITE,
    params=[param("node_id", "string", "UUID of the content node to unlock.")],
)
async def unlock_content(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    return await _toggle_lock(parameters, ctx, db, locked=False)


async def _toggle_lock(parameters: dict[str, Any], ctx: Any, db: AsyncSession, locked: bool) -> ToolResult:
    try:
        from models.content import CourseContentTree
        from models.practice import PracticeProblem
        from services.content.mutations import record_mutation
        from services.content.block_utils import set_all_blocks_locked

        import uuid
        node_id = parameters.get("node_id", "").strip()
        if not node_id:
            return ToolResult(success=False, output="", error="node_id is required.")

        node = await db.get(CourseContentTree, uuid.UUID(node_id))
        if not node:
            return ToolResult(success=False, output="", error=f"Content node {node_id} not found.")

        action = "lock" if locked else "unlock"

        # Lock/unlock blocks
        if node.blocks_json:
            node.blocks_json = set_all_blocks_locked(node.blocks_json, locked)

        # Lock/unlock associated practice problems
        from sqlalchemy import update
        await db.execute(
            update(PracticeProblem)
            .where(PracticeProblem.content_node_id == node.id)
            .values(locked=locked)
        )

        await db.flush()

        await record_mutation(
            db, node.id,
            mutation_type=action,
            reason=f"User {action}ed this section",
            user_id=ctx.user_id,
        )

        ctx.actions.append({"action": "content_mutated", "value": node_id})

        return ToolResult(
            success=True,
            output=f"{'Locked' if locked else 'Unlocked'} section '{node.title}' and associated practice problems.",
        )
    except Exception as e:
        await db.rollback()
        logger.error("_toggle_lock failed: %s", e, exc_info=True)
        return ToolResult(success=False, output="", error=str(e))


def get_mutation_tools() -> list:
    """Return all content mutation tools for registry."""
    return [
        update_section_notes,
        add_targeted_practice,
        annotate_section,
        lock_content,
        unlock_content,
    ]
