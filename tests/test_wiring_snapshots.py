"""Snapshot-style regression tests for runtime wiring.

Protects against "code exists but never called" regressions by checking:
- tool registration
- router mounts
- scheduler job registration
"""

from pathlib import Path

from services.experiments.status_matrix import get_integration_status_matrix

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_tool_registry_snapshot():
    source = _read("apps/api/services/agent/tools/registry.py")
    assert "registry.register(ExportAnkiTool())" in source
    assert "registry.register(ExportCalendarTool())" in source
    assert "if settings.enable_experimental_notion_export" in source
    assert "Experimental Notion export tool is dormant" in source


def test_router_mount_snapshot():
    source = _read("apps/api/services/router_registry.py")
    assert '"/api/chat"' in source
    assert '"/api/courses"' in source
    assert '"/api/flashcards"' in source
    assert '"/api/workflows"' in source


def test_scheduler_job_snapshot():
    source = _read("apps/api/services/scheduler/engine.py")
    for job_id in (
        "agenda_tick",
        "daily_brief",
        "weekly_report",
        "smart_review_trigger",
        "bkt_training",
        "cross_course_linking",
        "heartbeat_review",
    ):
        assert f'"{job_id}"' in source


def test_experimental_status_matrix_snapshot():
    matrix = get_integration_status_matrix()
    assert {"loom", "lector", "notion_export", "cat_pretest", "browser", "vision"} <= set(matrix.keys())
    assert matrix["notion_export"].status in {"active", "dormant"}
