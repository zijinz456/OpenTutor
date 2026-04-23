"""Practice problem and result models."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import Index, String, DateTime, ForeignKey, Text, Integer, Boolean, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# §34.5 Phase 11 — code-exercise question_type value.
# Stored in PracticeProblem.question_type as a plain string (no schema change);
# problem_metadata JSONB carries the code-runner-specific fields
# (starter_code, expected_output, hints, stdout_normalizer).
CODE_EXERCISE_TYPE = "code_exercise"

# §34.6 Phase 12 — hacking-lab question_type value.
# Stored in PracticeProblem.question_type as a plain string (no schema change);
# problem_metadata JSONB carries lab-specific fields (target_url, lab_type,
# expected_artifact_type, etc.). User submissions are graded by an LLM rubric
# (services.practice.lab_grader.grade_lab_proof) rather than exact match.
LAB_EXERCISE_TYPE = "lab_exercise"

# §16.2 + §26 Phase 3 — Python Depth 4 explicit drill styles.
# Four pedagogical card types the Python Depth track demands alongside the
# generic MC / flashcard / fill_blank toolkit. Stored as plain strings (no
# migration — the practice_problems.question_type column is String(20) with
# no CHECK constraint). Grading strategy per type:
#   * trace   — exact match after .strip().lower() (same as fill_blank).
#   * apply   — LLM-graded (judge is asked whether the rewrite satisfies the
#               target_feature and is semantically equivalent).
#   * compare — LLM-graded (judge accepts either preferred option when the
#               justification is sound).
#   * rebuild — exact match after whitespace normalization so trailing
#               newlines / incidental indentation don't fail a correct fill.
QUESTION_TYPE_TRACE = "trace"
QUESTION_TYPE_APPLY = "apply"
QUESTION_TYPE_COMPARE = "compare"
QUESTION_TYPE_REBUILD = "rebuild"

# Canonical set of the 4 drill styles — imported by grader / router dispatch.
DRILL_STYLE_TYPES = frozenset(
    {
        QUESTION_TYPE_TRACE,
        QUESTION_TYPE_APPLY,
        QUESTION_TYPE_COMPARE,
        QUESTION_TYPE_REBUILD,
    }
)


class PracticeProblem(Base):
    """Practice problems extracted from course content."""

    __tablename__ = "practice_problems"
    __table_args__ = (
        Index("ix_practice_problem_course", "course_id"),
        # Phase 16a — hot query: "all tasks in this room ordered by task_order".
        Index("ix_practice_problem_path_room", "path_room_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id"))
    content_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id"), nullable=True
    )

    # Problem data
    question_type: Mapped[str] = mapped_column(
        String(20)
    )  # mc, tf, short_answer, fill_blank, matching, select_all, free_response
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[Optional[dict]] = mapped_column(
        CompatJSONB, nullable=True
    )  # For MC/matching
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # v3: Knowledge point tagging + source tracking
    knowledge_points: Mapped[Optional[list]] = mapped_column(
        CompatJSONB, nullable=True, default=list
    )
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Sources: extracted | ai_generated | derived

    # v4: VCE-inspired diagnostic fields
    difficulty_layer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 1=basic concept recall, 2=standard application, 3=trap/edge case
    problem_metadata: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    # AI-generated structured annotation: {potential_traps, core_concept, bloom_level, ...}
    parent_problem_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("practice_problems.id"), nullable=True
    )

    # Phase 16a — room membership for the TryHackMe-style path UI.
    # Nullable because most existing cards (and free-roam-only cards) do
    # not belong to any room. ``SET NULL`` on room delete so deleting a
    # room via admin never cascades away a problem — the card simply
    # falls back to "not in any path".
    path_room_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID,
        ForeignKey("path_rooms.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 0-based task order within the room. Null for orphan cards (no
    # room) — the seed script populates this for room-mapped cards only.
    task_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_diagnostic: Mapped[bool] = mapped_column(Boolean, default=False)
    # True for simplified "clean" versions generated for diagnostic pairs
    source_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, nullable=True
    )
    source_version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # Content ownership tracking (for agent vs user content)
    source_owner: Mapped[str] = mapped_column(String(20), default="ai")
    # Values: "ai" | "user" | "ai+user_edited"
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    course = relationship("Course", back_populates="practice_problems")
    results = relationship(
        "PracticeResult", back_populates="problem", cascade="all, delete-orphan"
    )


class PracticeResult(Base):
    """User answers to practice problems."""

    __tablename__ = "practice_results"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("practice_problems.id")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))

    user_answer: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    ai_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # v4: Error tracking for cross-type triangulation
    error_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # conceptual | procedural | computational | reading | careless
    difficulty_layer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    answer_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    problem = relationship("PracticeProblem", back_populates="results")
