"""WF-6: Exam Preparation Workflow.

Flow: load_exam_info → identify_topics → assess_readiness → generate_plan

Reference from spec:
- WF-6 helps students prepare for exams
- Identifies key topics from course content
- Assesses readiness based on quiz/study history
- Generates targeted review plan + practice problems
"""

import uuid
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.content import CourseContentTree
from models.ingestion import WrongAnswer, StudySession
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


async def get_course_topics(
    db: AsyncSession,
    course_id: uuid.UUID,
) -> list[dict]:
    """Extract main topics from the course content tree."""
    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.level <= 2,
        )
        .order_by(CourseContentTree.order_index)
    )
    nodes = result.scalars().all()

    topics = []
    current_chapter = None
    for node in nodes:
        if node.level <= 1:
            current_chapter = {
                "title": node.title,
                "subtopics": [],
                "content_preview": (node.content or "")[:200],
            }
            topics.append(current_chapter)
        elif node.level == 2 and current_chapter:
            current_chapter["subtopics"].append(node.title)

    return topics


async def assess_readiness(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Assess exam readiness based on study and quiz history."""
    # Get wrong answer stats
    wrong_result = await db.execute(
        select(func.count(WrongAnswer.id))
        .where(
            WrongAnswer.user_id == user_id,
            WrongAnswer.course_id == course_id,
            WrongAnswer.mastered == False,
        )
    )
    unmastered_count = wrong_result.scalar() or 0

    mastered_result = await db.execute(
        select(func.count(WrongAnswer.id))
        .where(
            WrongAnswer.user_id == user_id,
            WrongAnswer.course_id == course_id,
            WrongAnswer.mastered == True,
        )
    )
    mastered_count = mastered_result.scalar() or 0

    # Get study session stats
    session_result = await db.execute(
        select(StudySession)
        .where(
            StudySession.user_id == user_id,
            StudySession.course_id == course_id,
        )
    )
    sessions = session_result.scalars().all()

    total_time = sum(s.duration_minutes or 0 for s in sessions)
    total_problems = sum(s.problems_attempted or 0 for s in sessions)
    correct_problems = sum(s.problems_correct or 0 for s in sessions)

    return {
        "total_study_time_minutes": total_time,
        "problems_attempted": total_problems,
        "problems_correct": correct_problems,
        "accuracy": correct_problems / max(total_problems, 1),
        "unmastered_wrong_answers": unmastered_count,
        "mastered_wrong_answers": mastered_count,
        "session_count": len(sessions),
    }


async def run_exam_prep(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    exam_topic: str | None = None,
    days_until_exam: int = 7,
) -> dict:
    """Execute WF-6: Exam preparation workflow.

    Steps:
    1. Load course topics
    2. Assess readiness
    3. Generate targeted exam prep plan
    """
    # Get course info
    course_result = await db.execute(
        select(Course).where(Course.id == course_id)
    )
    course = course_result.scalar_one_or_none()
    course_name = course.name if course else "Unknown Course"

    # Step 1: Get topics
    topics = await get_course_topics(db, course_id)

    # Step 2: Assess readiness
    readiness = await assess_readiness(db, user_id, course_id)

    # Step 2b: Score prediction (Phase 4 — Learning Digital Twin)
    prediction = None
    try:
        from services.prediction.score_predictor import predict_score

        prediction = await predict_score(db, user_id, course_id, days_until_exam)
        logger.info(
            "Score prediction for exam prep: predicted=%.1f, boosted=%.1f (model=%s)",
            prediction["predicted_score"],
            prediction["with_extra_30min_daily"],
            prediction["model"],
        )
    except Exception as e:
        logger.debug("Score prediction unavailable for exam prep: %s", e)

    # Step 3: Generate prep plan
    topics_text = "\n".join(
        f"- {t['title']}: {', '.join(t['subtopics'][:5])}"
        for t in topics
    ) or "No course topics available."

    readiness_text = (
        f"Study time: {readiness['total_study_time_minutes']} minutes total\n"
        f"Problems: {readiness['problems_attempted']} attempted, "
        f"{readiness['accuracy']:.0%} accuracy\n"
        f"Weak areas: {readiness['unmastered_wrong_answers']} unmastered wrong answers\n"
        f"Sessions: {readiness['session_count']} study sessions"
    )

    # Inject score prediction into the LLM prompt when available
    prediction_text = ""
    if prediction:
        prediction_text = (
            f"\n## Score Prediction (AI Model: {prediction['model']})\n"
            f"- Current predicted exam score: **{prediction['predicted_score']:.0f}/100**\n"
            f"- If student studies 30 extra minutes per day: **{prediction['with_extra_30min_daily']:.0f}/100** "
            f"(+{prediction['improvement_potential']:.0f} points)\n"
            f"- Prediction confidence: {prediction['confidence']}\n"
            f"\nIncorporate this prediction into your plan — tell the student their "
            f"projected score and how extra effort can improve it."
        )

    client = get_llm_client()
    plan, _ = await client.chat(
        "You are an exam preparation expert. Create focused, effective study plans.",
        f"""Create an exam preparation plan for {course_name}.
{f'Exam focus: {exam_topic}' if exam_topic else ''}
Days until exam: {days_until_exam}

## Course Topics
{topics_text}

## Student Readiness
{readiness_text}
{prediction_text}

Create a plan that includes:
1. **Score Outlook**: Current predicted score and improvement potential
2. **Priority Topics**: Which topics to focus on (based on weak areas)
3. **Day-by-Day Schedule**: Specific study activities for each remaining day
4. **Review Strategy**: How to review previously learned material
5. **Practice Problems**: Suggest types of practice for each topic
6. **Exam Day Tips**: Last-minute preparation advice

Be realistic about the available time. Focus on high-impact areas.
Output in markdown format.""",
    )

    return {
        "course": course_name,
        "topics_count": len(topics),
        "readiness": readiness,
        "prediction": prediction,
        "days_until_exam": days_until_exam,
        "plan": plan,
    }
