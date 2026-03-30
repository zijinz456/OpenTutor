"""Auto-configuration of course layout and welcome message."""

import logging
import re
import uuid

import sqlalchemy as sa
from sqlalchemy import select

from models.course import Course
from models.ingestion import IngestionJob, Assignment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content-topic keyword groups for mode inference
# Each entry: (pattern, weight)
# ---------------------------------------------------------------------------

_EXAM_PREP_SIGNALS: list[tuple[str, float]] = [
    # Exam/assessment content
    (r"\bexam\b", 2.0),
    (r"\bmidterm\b", 2.0),
    (r"\bfinal exam\b", 2.5),
    (r"\bpast (paper|exam|question)\b", 2.5),
    (r"\bpractice (question|problem|test)\b", 2.0),
    (r"\bsample (question|exam)\b", 2.0),
    # Research/statistical methods (commonly tested)
    (r"\bstudy design\b", 1.5),
    (r"\bresearch design\b", 1.5),
    (r"\bexperimental design\b", 1.5),
    (r"\bobservational study\b", 1.5),
    (r"\brandomized controlled\b", 1.5),
    (r"\bcohort study\b", 1.5),
    (r"\bcase.control\b", 1.5),
    (r"\bhypothesis test\b", 1.5),
    (r"\bnull hypothesis\b", 1.5),
    (r"\bp.?value\b", 1.5),
    (r"\bstatistical significance\b", 1.5),
    (r"\bconfidence interval\b", 1.5),
    (r"\bconfounding\b", 1.2),
    (r"\bbias\b", 0.8),
    (r"\bsample size\b", 1.2),
    (r"\bpower (analysis|calculation)\b", 1.5),
    (r"\bt.test\b", 1.2),
    (r"\bchi.square\b", 1.2),
    (r"\banova\b", 1.2),
    (r"\bregression (analysis|model)\b", 1.2),
    # Assessment language
    (r"\blearning outcome\b", 1.0),
    (r"\bkey concept\b", 0.8),
    (r"\bdefinition\b", 0.5),
    (r"\bformula\b", 0.8),
]

# Signals that suggest deadlines/assignment mode (strong)
_ASSIGNMENT_SIGNALS: list[tuple[str, float]] = [
    (r"\bassignment\b", 1.5),
    (r"\bdue (date|by)\b", 2.0),
    (r"\bsubmit\b", 1.5),
    (r"\bdeadline\b", 2.0),
    (r"\bproject\b", 1.0),
    (r"\bword limit\b", 1.5),
    (r"\bmarking rubric\b", 2.0),
    (r"\bmarks?\b", 0.5),
]

_SCORE_THRESHOLD_SUGGEST = 5.0   # Add agent_insight suggesting exam_prep
_SCORE_THRESHOLD_SWITCH = 12.0   # Directly switch mode to exam_prep


def _score_content(text: str, signals: list[tuple[str, float]]) -> float:
    """Score text against a list of (pattern, weight) signals."""
    if not text:
        return 0.0
    text_lower = text.lower()
    total = 0.0
    for pattern, weight in signals:
        matches = re.findall(pattern, text_lower)
        total += len(matches) * weight
    return total


async def auto_configure_course(
    db_factory,
    course_id: uuid.UUID,
    prep_summary: dict,
) -> dict | None:
    """Analyze ingested course content and auto-configure layout + welcome message.

    Called after auto_prepare completes. Updates metadata["spaceLayout"] (the
    format the frontend actually reads) based on:
    - Content topic analysis: keyword scoring on extracted markdown
    - Assignment count & deadlines
    - Content categories (exam_schedule, assignment, etc.)

    For lecture slides, analyses the actual text to detect exam-prep signals
    (e.g. study design, hypothesis testing) and adds a mode suggestion block.
    """
    from datetime import datetime, timezone
    from models.content import CourseContentTree

    async with db_factory() as db:
        # 1. Count assignments with deadlines
        assign_result = await db.execute(
            select(Assignment).where(Assignment.course_id == course_id)
        )
        assignments = assign_result.scalars().all()
        deadline_count = sum(1 for a in assignments if a.due_date)

        # 2. Check ingestion job content categories + extracted text
        job_result = await db.execute(
            select(IngestionJob.content_category, IngestionJob.extracted_markdown).where(
                IngestionJob.course_id == course_id,
            )
        )
        job_rows = job_result.all()
        categories = [r[0] for r in job_rows if r[0]]
        all_content = "\n".join(r[1] or "" for r in job_rows)

        # 3. Count content nodes
        node_result = await db.execute(
            select(sa.func.count()).select_from(CourseContentTree).where(
                CourseContentTree.course_id == course_id
            )
        )
        node_count = node_result.scalar() or 0

        # 4. Get course info
        course_result = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        course = course_result.scalar_one_or_none()
        if not course:
            return None

        # --- Content-topic scoring ---
        exam_signal_score = _score_content(all_content, _EXAM_PREP_SIGNALS)
        assign_signal_score = _score_content(all_content, _ASSIGNMENT_SIGNALS)

        # Also score categories
        hard_exam_cats = {"exam_schedule", "exam"}
        hard_assign_cats = {"assignment"}
        exam_cat_count = sum(1 for c in categories if c in hard_exam_cats)
        assign_cat_count = sum(1 for c in categories if c in hard_assign_cats)

        # --- Determine mode intent ---
        # Priority: hard category signals > deadline count > content scoring
        # NOTE: exam_prep mode is never auto-switched — only suggested via agent_insight.
        # The user must manually enable exam_prep from the frontend.
        if assign_cat_count >= 1 or deadline_count >= 3:
            mode_intent = "assignment"        # switch to assignment/plan mode
        elif (
            exam_cat_count >= 1
            or (deadline_count >= 1 and exam_signal_score >= 3.0)
            or exam_signal_score >= _SCORE_THRESHOLD_SWITCH
            or exam_signal_score >= _SCORE_THRESHOLD_SUGGEST
        ):
            mode_intent = "exam_prep_suggest" # suggest via agent_insight (needs user approval)
        else:
            mode_intent = "no_change"         # keep cold-start layout as-is

        # --- Update spaceLayout (new format, actually read by frontend) ---
        now = datetime.now(timezone.utc)
        metadata = dict(course.metadata_ or {})
        space_layout = dict(metadata.get("spaceLayout") or {})

        if mode_intent == "assignment":
            space_layout["mode"] = "self_paced"  # assignment content uses self-paced with plan block
            # Ensure plan block is present
            blocks = list(space_layout.get("blocks", []))
            block_types = [b.get("type") for b in blocks]
            if "plan" not in block_types:
                blocks.append({"type": "plan", "size": "medium", "source": "template"})
            space_layout["blocks"] = blocks

        elif mode_intent == "exam_prep_suggest":
            # Add an agent_insight block suggesting exam_prep mode (needs user approval)
            blocks = list(space_layout.get("blocks", []))
            # Don't add duplicate suggestion insights
            existing_suggestions = [
                b for b in blocks
                if b.get("type") == "agent_insight"
                and b.get("config", {}).get("insightType") == "mode_suggestion"
            ]
            if not existing_suggestions:
                insight_id = f"blk-autoconf-{int(now.timestamp())}"
                blocks.insert(0, {
                    "id": insight_id,
                    "type": "agent_insight",
                    "position": 0,
                    "size": "full",
                    "config": {
                        "insightType": "mode_suggestion",
                        "suggestedMode": "exam_prep",
                        "reason": (
                            "This material covers exam-relevant concepts "
                            "(e.g. study design, hypothesis testing, statistical methods). "
                            "Switch to Exam Prep mode to focus on practice and weak areas."
                        ),
                    },
                    "visible": True,
                    "source": "agent",
                    "agentMeta": {
                        "reason": "Content analysis detected exam-prep relevant topics.",
                        "needsApproval": True,
                        "dismissible": True,
                        "approvalCta": "Switch to Exam Prep",
                    },
                })
                space_layout["blocks"] = blocks

        if space_layout:
            metadata["spaceLayout"] = space_layout

        # --- Build welcome message ---
        parts = [f"**{course.name}** is ready! Here's what I found:\n"]
        parts.append(f"- **{node_count}** content sections indexed")

        if prep_summary.get("notes", 0) > 0:
            parts.append(f"- **{prep_summary['notes']}** AI-generated note summaries")
        if prep_summary.get("flashcards", 0) > 0:
            parts.append(f"- **{prep_summary['flashcards']}** flashcards created")
        if prep_summary.get("quiz", 0) > 0:
            parts.append(f"- **{prep_summary['quiz']}** quiz questions generated")

        errors = prep_summary.get("errors", {})
        if errors:
            failed_steps = ", ".join(errors.keys())
            parts.append(f"- ⚠ Some auto-generation steps had issues ({failed_steps}). You can retry by asking me.")

        if deadline_count > 0:
            upcoming = [
                a for a in assignments
                if a.due_date and a.due_date > now
            ]
            upcoming.sort(key=lambda a: a.due_date)
            parts.append(f"- **{deadline_count}** deadlines detected")
            if upcoming:
                next_due = upcoming[0]
                days_left = (next_due.due_date - now).days
                parts.append(
                    f"- Next deadline: **{next_due.title}** in **{days_left} days**"
                )

        parts.append("")

        if mode_intent == "assignment":
            parts.append(
                "I've switched to **Self-Paced mode** and added a study plan block "
                "since I detected assignment deadlines. You can switch modes anytime by asking me."
            )
        elif mode_intent == "exam_prep_suggest":
            parts.append(
                "Your workspace is ready. I noticed this material covers exam-relevant topics "
                "(study design, statistical methods). I've added a suggestion to switch to "
                "**Exam Prep mode** — approve it above or ask me to switch anytime."
            )
        else:
            parts.append(
                "Your workspace is ready. "
                "Ask me anything about your materials — I'll explain, quiz you, or help you review."
            )

        welcome_message = "\n".join(parts)
        metadata["welcome_message"] = welcome_message
        metadata["auto_configured_at"] = now.isoformat()
        metadata["auto_config"] = {
            "mode_intent": mode_intent,
            "exam_signal_score": round(exam_signal_score, 1),
            "assign_signal_score": round(assign_signal_score, 1),
            "node_count": node_count,
            "deadline_count": deadline_count,
            "categories": categories[:20],
        }
        course.metadata_ = metadata
        await db.commit()

        logger.info(
            "Auto-configured course %s: mode_intent=%s, exam_score=%.1f, nodes=%d, deadlines=%d",
            course_id, mode_intent, exam_signal_score, node_count, deadline_count,
        )
        return {"mode_intent": mode_intent, "welcome_message": welcome_message}
