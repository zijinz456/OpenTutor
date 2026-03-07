import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.agent.tools.workspace import update_workspace

LEGACY_ACTIONS = {"switch_tab", "set_layout", "set_layout_preset", "toggle_section"}


@pytest.mark.asyncio
async def test_update_workspace_switch_tab_emits_prd_actions():
    ctx = SimpleNamespace(actions=[], course_id=uuid.uuid4())
    db = AsyncMock()

    result = await update_workspace.run(
        {"commands": [{"command": "switch_tab", "section": "practice"}]},
        ctx,
        db,
    )

    assert result.success is True
    assert ctx.actions == [
        {
            "action": "reorder_blocks",
            "value": "quiz,flashcards,wrong_answers,review,notes,progress,plan,knowledge_graph,chapter_list,forecast,agent_insight",
        },
        {"action": "data_updated", "value": "practice"},
    ]
    assert all(action["action"] not in LEGACY_ACTIONS for action in ctx.actions)


@pytest.mark.asyncio
async def test_update_workspace_focus_topic_emits_focus_and_refresh():
    course_id = uuid.uuid4()
    node_id = uuid.uuid4()
    ctx = SimpleNamespace(actions=[], course_id=course_id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(course_id=course_id, title="Binary Search"))

    result = await update_workspace.run(
        {"commands": [{"command": "focus_topic", "node_id": str(node_id), "section": "plan"}]},
        ctx,
        db,
    )

    assert result.success is True
    assert ctx.actions == [
        {"action": "focus_topic", "value": str(node_id)},
        {"action": "data_updated", "value": "plan"},
    ]
    assert all(action["action"] not in LEGACY_ACTIONS for action in ctx.actions)


@pytest.mark.asyncio
async def test_update_workspace_set_layout_emits_resize_and_reorder_actions():
    ctx = SimpleNamespace(actions=[], course_id=uuid.uuid4())
    db = AsyncMock()

    result = await update_workspace.run(
        {"commands": [{"command": "set_layout", "chat_height": 0.2, "tree_collapsed": True, "tree_width": 360}]},
        ctx,
        db,
    )

    assert result.success is True
    assert ctx.actions == [
        {"action": "resize_block", "value": "notes:large"},
        {
            "action": "reorder_blocks",
            "value": "notes,quiz,flashcards,progress,plan,chapter_list,knowledge_graph,review,wrong_answers,forecast,agent_insight",
        },
        {"action": "resize_block", "value": "chapter_list:full"},
        {"action": "data_updated", "value": "notes"},
    ]
    assert all(action["action"] not in LEGACY_ACTIONS for action in ctx.actions)


@pytest.mark.asyncio
async def test_update_workspace_start_quiz_emits_practice_refresh_actions():
    ctx = SimpleNamespace(actions=[], course_id=uuid.uuid4())
    db = AsyncMock()

    result = await update_workspace.run(
        {"commands": [{"command": "start_quiz"}]},
        ctx,
        db,
    )

    assert result.success is True
    assert ctx.actions == [
        {
            "action": "reorder_blocks",
            "value": "quiz,flashcards,wrong_answers,review,notes,progress,plan,chapter_list,knowledge_graph,forecast,agent_insight",
        },
        {"action": "data_updated", "value": "practice"},
    ]
    assert all(action["action"] not in LEGACY_ACTIONS for action in ctx.actions)
