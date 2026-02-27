"""v3 scene system + new models + field extensions.

New tables: scenes, scene_snapshots, scene_switch_log, knowledge_points, chat_sessions, study_plans
Extended: courses (active_scene, template_id), user_preferences (scene_type),
          wrong_answers (error_category, knowledge_points),
          learning_templates (scene_id, tab_preset, workflow),
          practice_problems (knowledge_points, source)

Revision ID: 20260228_0003
Revises: 20260228_0002
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "20260228_0003"
down_revision = "20260228_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # ── New tables ──

    if "scenes" not in existing_tables:
        op.create_table(
            "scenes",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("scene_id", sa.String(50), unique=True, nullable=False),
            sa.Column("display_name", sa.String(100), nullable=False),
            sa.Column("icon", sa.String(10), nullable=True),
            sa.Column("is_preset", sa.Boolean, default=False),
            sa.Column("tab_preset", JSONB, nullable=False),
            sa.Column("workflow", sa.String(50), nullable=False),
            sa.Column("ai_behavior", JSONB, nullable=False),
            sa.Column("preferences", JSONB, nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "scene_snapshots" not in existing_tables:
        op.create_table(
            "scene_snapshots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("scene_id", sa.String(50), nullable=False),
            sa.Column("open_tabs", JSONB, nullable=False),
            sa.Column("layout_state", JSONB, nullable=False),
            sa.Column("scroll_positions", JSONB, nullable=True),
            sa.Column("last_active_tab", sa.String(50), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.UniqueConstraint("course_id", "scene_id", name="uq_snapshot_course_scene"),
        )

    if "scene_switch_log" not in existing_tables:
        op.create_table(
            "scene_switch_log",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("from_scene", sa.String(50), nullable=True),
            sa.Column("to_scene", sa.String(50), nullable=False),
            sa.Column("trigger_type", sa.String(20), nullable=False),
            sa.Column("trigger_context", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "knowledge_points" not in existing_tables:
        op.create_table(
            "knowledge_points",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("prerequisites", JSONB, nullable=True),
            sa.Column("mastery_level", sa.Float, default=0.0),
            sa.Column("source_content_node_id", UUID(as_uuid=True), sa.ForeignKey("course_content_tree.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_kp_course", "knowledge_points", ["course_id"])
        op.create_index("ix_kp_mastery", "knowledge_points", ["course_id", "mastery_level"])

    if "chat_sessions" not in existing_tables:
        op.create_table(
            "chat_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("scene_id", sa.String(50), nullable=True),
            sa.Column("title", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "study_plans" not in existing_tables:
        op.create_table(
            "study_plans",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("scene_id", sa.String(50), nullable=True),
            sa.Column("tasks", JSONB, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )

    # ── Column additions to existing tables ──

    # courses: active_scene, template_id
    if "courses" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("courses")]
        if "active_scene" not in cols:
            op.add_column("courses", sa.Column("active_scene", sa.String(50), nullable=True, server_default="study_session"))
        if "template_id" not in cols:
            op.add_column("courses", sa.Column("template_id", UUID(as_uuid=True), nullable=True))

    # user_preferences: scene_type
    if "user_preferences" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("user_preferences")]
        if "scene_type" not in cols:
            op.add_column("user_preferences", sa.Column("scene_type", sa.String(50), nullable=True))

    # wrong_answers: error_category, knowledge_points
    if "wrong_answers" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("wrong_answers")]
        if "error_category" not in cols:
            op.add_column("wrong_answers", sa.Column("error_category", sa.String(30), nullable=True))
        if "knowledge_points" not in cols:
            op.add_column("wrong_answers", sa.Column("knowledge_points", JSONB, nullable=True))

    # learning_templates: scene_id, tab_preset, workflow
    if "learning_templates" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("learning_templates")]
        if "scene_id" not in cols:
            op.add_column("learning_templates", sa.Column("scene_id", sa.String(50), nullable=True))
        if "tab_preset" not in cols:
            op.add_column("learning_templates", sa.Column("tab_preset", JSONB, nullable=True))
        if "workflow" not in cols:
            op.add_column("learning_templates", sa.Column("workflow", sa.String(50), nullable=True))

    # practice_problems: knowledge_points, source
    if "practice_problems" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("practice_problems")]
        if "knowledge_points" not in cols:
            op.add_column("practice_problems", sa.Column("knowledge_points", JSONB, nullable=True))
        if "source" not in cols:
            op.add_column("practice_problems", sa.Column("source", sa.String(20), nullable=True))

    # wrong_answers: performance indexes
    if "wrong_answers" in existing_tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("wrong_answers")}
        if "ix_wrong_answers_user_course" not in existing_indexes:
            op.create_index("ix_wrong_answers_user_course", "wrong_answers", ["user_id", "course_id"])
        if "ix_wrong_answers_course_mastered" not in existing_indexes:
            op.create_index("ix_wrong_answers_course_mastered", "wrong_answers", ["course_id", "mastered"])


def downgrade() -> None:
    # Drop new tables
    op.drop_table("study_plans")
    op.drop_table("chat_sessions")
    op.drop_index("ix_kp_mastery", table_name="knowledge_points")
    op.drop_index("ix_kp_course", table_name="knowledge_points")
    op.drop_table("knowledge_points")
    op.drop_table("scene_switch_log")
    op.drop_table("scene_snapshots")
    op.drop_table("scenes")

    # Drop wrong_answers indexes
    op.drop_index("ix_wrong_answers_course_mastered", table_name="wrong_answers")
    op.drop_index("ix_wrong_answers_user_course", table_name="wrong_answers")

    # Drop added columns
    op.drop_column("courses", "active_scene")
    op.drop_column("courses", "template_id")
    op.drop_column("user_preferences", "scene_type")
    op.drop_column("wrong_answers", "error_category")
    op.drop_column("wrong_answers", "knowledge_points")
    op.drop_column("learning_templates", "scene_id")
    op.drop_column("learning_templates", "tab_preset")
    op.drop_column("learning_templates", "workflow")
    op.drop_column("practice_problems", "knowledge_points")
    op.drop_column("practice_problems", "source")
