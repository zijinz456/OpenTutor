import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.agent.tools.assessment_tools import update_workspace_layout
from services.agent.tools.workspace import update_workspace

LEGACY_ACTIONS = {"switch_tab", "set_layout", "set_layout_preset", "toggle_section"}


def _assert_no_legacy_actions(actions: list[dict]) -> None:
    assert all(action["action"] not in LEGACY_ACTIONS for action in actions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("commands", "expected_actions"),
    [
        (
            [{"command": "switch_tab", "section": "practice"}],
            [
                {
                    "action": "reorder_blocks",
                    "value": "quiz,flashcards,wrong_answers,review,notes,progress,plan,knowledge_graph,chapter_list,forecast,agent_insight",
                },
                {"action": "data_updated", "value": "practice"},
            ],
        ),
        (
            [{"command": "start_quiz"}],
            [
                {
                    "action": "reorder_blocks",
                    "value": "quiz,flashcards,wrong_answers,review,notes,progress,plan,chapter_list,knowledge_graph,forecast,agent_insight",
                },
                {"action": "data_updated", "value": "practice"},
            ],
        ),
    ],
)
async def test_update_workspace_emits_prd_actions_for_priority_commands(commands, expected_actions):
    ctx = SimpleNamespace(actions=[], course_id=uuid.uuid4())
    db = AsyncMock()

    result = await update_workspace.run(
        {"commands": commands},
        ctx,
        db,
    )

    assert result.success is True
    assert ctx.actions == expected_actions
    _assert_no_legacy_actions(ctx.actions)


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
    _assert_no_legacy_actions(ctx.actions)


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
    _assert_no_legacy_actions(ctx.actions)


@pytest.mark.asyncio
async def test_update_workspace_returns_error_for_empty_commands():
    ctx = SimpleNamespace(actions=[], course_id=uuid.uuid4())
    db = AsyncMock()

    result = await update_workspace.run({"commands": []}, ctx, db)

    assert result.success is False
    assert result.error == "commands must be a non-empty array."
    assert ctx.actions == []


@pytest.mark.asyncio
async def test_update_workspace_unknown_command_is_reported_without_emitting_actions():
    ctx = SimpleNamespace(actions=[], course_id=uuid.uuid4())
    db = AsyncMock()

    result = await update_workspace.run({"commands": [{"command": "legacy_toggle"}]}, ctx, db)

    assert result.success is False
    assert result.error == "Unknown command: 'legacy_toggle'"
    assert ctx.actions == []


@pytest.mark.asyncio
async def test_update_workspace_focus_topic_rejects_node_outside_course():
    course_id = uuid.uuid4()
    node_id = uuid.uuid4()
    ctx = SimpleNamespace(actions=[], course_id=course_id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(course_id=uuid.uuid4(), title="Wrong Course Node"))

    result = await update_workspace.run(
        {"commands": [{"command": "focus_topic", "node_id": str(node_id)}]},
        ctx,
        db,
    )

    assert result.success is False
    assert result.error == f"focus_topic failed: Node {node_id} not found in current course"
    assert ctx.actions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameters", "expected_action"),
    [
        ({"preset": "exam_prep"}, {"action": "apply_template", "value": "quick_reviewer"}),
        (
            {"toggle_section": "practice", "visible": False},
            {"action": "remove_block", "value": "quiz"},
        ),
        (
            {"toggle_section": "notes", "visible": True},
            {"action": "add_block", "value": "notes:large"},
        ),
    ],
)
async def test_update_workspace_layout_maps_legacy_inputs_to_block_actions(parameters, expected_action):
    ctx = SimpleNamespace(actions=[])

    result = await update_workspace_layout.run(parameters, ctx, AsyncMock())

    assert result.success is True
    assert ctx.actions == [expected_action]
    _assert_no_legacy_actions(ctx.actions)


@pytest.mark.asyncio
async def test_update_workspace_layout_requires_preset_or_toggle_section():
    ctx = SimpleNamespace(actions=[])

    result = await update_workspace_layout.run({}, ctx, AsyncMock())

    assert result.success is False
    assert result.error == "Provide either 'preset' or 'toggle_section' parameter."
    assert ctx.actions == []
