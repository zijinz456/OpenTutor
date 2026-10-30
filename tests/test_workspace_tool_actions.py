from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.agent.tools.assessment_tools import update_workspace_layout

LEGACY_ACTIONS = {"switch_tab", "set_layout", "set_layout_preset", "toggle_section"}


def _assert_no_legacy_actions(actions: list[dict]) -> None:
    assert all(action["action"] not in LEGACY_ACTIONS for action in actions)


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
