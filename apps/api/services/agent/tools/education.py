"""Built-in education-domain tools for ReAct agent loop.

This module re-exports all education tools from their category-specific modules
and provides the get_builtin_tools() registry helper.

Tool modules:
- explanation_tools: lookup_progress, search_content, get_mastery_report,
                     get_course_outline, get_forgetting_forecast, run_code
- assessment_tools:  list_wrong_answers, list_study_goals, list_recent_tasks,
                     list_assignments, sync_deadlines_to_calendar_tool,
                     update_workspace_layout
- flashcard_tools:   generate_flashcards_tool, generate_notes_tool,
                     create_study_plan_tool
- quiz_tools:        generate_quiz_tool, derive_diagnostic_tool,
                     record_comprehension_tool
"""

from services.agent.tools.base import Tool

# ── Re-exports for backward compatibility ──

from services.agent.tools.explanation_tools import (  # noqa: F401
    get_course_outline,
    get_forgetting_forecast,
    get_mastery_report,
    lookup_progress,
    run_code,
    search_content,
)
from services.agent.tools.assessment_tools import (  # noqa: F401
    list_assignments,
    list_recent_tasks,
    list_study_goals,
    list_wrong_answers,
    sync_deadlines_to_calendar_tool,
    update_workspace_layout,
)
from services.agent.tools.flashcard_tools import (  # noqa: F401
    create_study_plan_tool,
    generate_flashcards_tool,
    generate_notes_tool,
)
from services.agent.tools.quiz_tools import (  # noqa: F401
    derive_diagnostic_tool,
    generate_quiz_tool,
    record_comprehension_tool,
)


# ── Registry Helper ──


def get_builtin_tools() -> list[Tool]:
    """Return all built-in education tools for registration."""
    return [
        # Read tools
        lookup_progress, search_content, list_wrong_answers,
        get_mastery_report, get_course_outline, list_study_goals,
        list_recent_tasks, list_assignments, run_code,
        get_forgetting_forecast,
        # Write tools
        generate_flashcards_tool, generate_quiz_tool, generate_notes_tool,
        create_study_plan_tool, derive_diagnostic_tool,
        sync_deadlines_to_calendar_tool, update_workspace_layout,
        # Comprehension probing
        record_comprehension_tool,
    ]
