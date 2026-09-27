"""Pin the composite indexes added for frequently-queried columns (issue #31)."""

from database import Base
from models.knowledge_graph import KnowledgeNode  # noqa: F401 — force model registration
from models.memory import ConversationMemory  # noqa: F401
from models.practice import PracticeResult  # noqa: F401


def _index_columns(table_name: str) -> dict[str, list[str]]:
    table = Base.metadata.tables[table_name]
    return {idx.name: [c.name for c in idx.columns] for idx in table.indexes}


def test_conversation_memories_recency_index():
    indexes = _index_columns("conversation_memories")
    assert indexes.get("ix_mem_user_course_created") == ["user_id", "course_id", "created_at"]


def test_practice_results_user_problem_index():
    indexes = _index_columns("practice_results")
    assert indexes.get("ix_practice_result_user_problem") == ["user_id", "problem_id"]
