from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.agent.tools.education import update_workspace_layout


@pytest.mark.asyncio
async def test_update_workspace_layout_preset_emits_apply_template_action():
    ctx = SimpleNamespace(actions=[])

    result = await update_workspace_layout.run({"preset": "exam_prep"}, ctx, AsyncMock())

    assert result.success is True
    assert ctx.actions == [{"action": "apply_template", "value": "quick_reviewer"}]


@pytest.mark.asyncio
async def test_update_workspace_layout_hide_section_emits_remove_block_action():
    ctx = SimpleNamespace(actions=[])

    result = await update_workspace_layout.run(
        {"toggle_section": "practice", "visible": False},
        ctx,
        AsyncMock(),
    )

    assert result.success is True
    assert ctx.actions == [{"action": "remove_block", "value": "quiz"}]


@pytest.mark.asyncio
async def test_update_workspace_layout_show_section_emits_add_block_action():
    ctx = SimpleNamespace(actions=[])

    result = await update_workspace_layout.run(
        {"toggle_section": "notes", "visible": True},
        ctx,
        AsyncMock(),
    )

    assert result.success is True
    assert ctx.actions == [{"action": "add_block", "value": "notes:large"}]
