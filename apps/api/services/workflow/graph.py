"""LangGraph-based workflow engine.

Converts all 6 workflows to LangGraph StateGraph with proper node/edge definitions.
Each workflow is a compiled StateGraph that can be invoked with `.ainvoke(state)`.

UPGRADED: WF-4 now uses multi-agent orchestrator for intent-aware routing
and MemCell-based memory encoding.

Reference from spec:
- Phase 0: "LangGraph工作流: WF-2每周准备 + WF-4学习Session"
- Phase 1: "完整6个工作流"
"""

import uuid
import logging
from typing import TypedDict, Annotated
from operator import add

from langgraph.graph import StateGraph, END

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ═══════ WF-4: Study Session Graph (Multi-Agent Upgraded) ═══════

class StudyState(TypedDict):
    user_id: uuid.UUID
    course_id: uuid.UUID
    user_message: str
    intent: str
    preferences: dict
    content_docs: list[dict]
    memories: list[dict]
    system_prompt: str
    response: str
    signal: dict | None
    db: AsyncSession


async def node_classify_intent(state: StudyState) -> dict:
    """Classify user intent using the two-stage router (rule + LLM)."""
    from services.agent.state import AgentContext
    from services.agent.router import classify_intent

    ctx = AgentContext(
        user_id=state["user_id"],
        course_id=state["course_id"],
        user_message=state["user_message"],
    )
    ctx = await classify_intent(ctx)
    return {"intent": ctx.intent.value}


async def node_load_context(state: StudyState) -> dict:
    from services.agent.orchestrator import build_agent_context, load_context

    ctx = build_agent_context(
        user_id=state["user_id"],
        course_id=state["course_id"],
        message=state["user_message"],
        scene="study_session",
    )
    intent = state.get("intent", "general")
    try:
        ctx.intent = IntentType(intent)
    except ValueError:
        ctx.intent = IntentType.GENERAL
    ctx = await load_context(ctx, state["db"])
    return {
        "preferences": ctx.preferences,
        "memories": ctx.memories,
        "content_docs": ctx.content_docs,
    }


async def node_search_content(state: StudyState) -> dict:
    return {}


async def node_generate_response(state: StudyState) -> dict:
    """Route to appropriate specialist agent based on intent."""
    from services.agent.state import AgentContext, IntentType
    from services.agent.orchestrator import apply_reflection, get_agent

    ctx = AgentContext(
        user_id=state["user_id"],
        course_id=state["course_id"],
        user_message=state["user_message"],
        preferences=state.get("preferences", {}),
        content_docs=state.get("content_docs", []),
        memories=state.get("memories", []),
    )
    try:
        intent = IntentType(state.get("intent", "general"))
    except ValueError:
        intent = IntentType.GENERAL
    ctx.intent = intent

    agent = get_agent(intent)
    ctx = await agent.run(ctx, state["db"])
    ctx = await apply_reflection(ctx)
    return {"response": ctx.response, "system_prompt": ""}


async def node_extract_signals(state: StudyState) -> dict:
    # WF-4 now delegates post-processing to the shared orchestrator path.
    return {"signal": None}


async def node_encode_memory(state: StudyState) -> dict:
    """No-op: memory encoding now lives in orchestrator post-processing."""
    return {}


def build_study_session_graph() -> StateGraph:
    """Build the WF-4 Study Session StateGraph (multi-agent upgraded)."""
    graph = StateGraph(StudyState)
    graph.add_node("classify_intent", node_classify_intent)
    graph.add_node("load_context", node_load_context)
    graph.add_node("search_content", node_search_content)
    graph.add_node("generate_response", node_generate_response)
    graph.add_node("extract_signals", node_extract_signals)
    graph.add_node("encode_memory", node_encode_memory)

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "load_context")
    graph.add_edge("load_context", "search_content")
    graph.add_edge("search_content", "generate_response")
    graph.add_edge("generate_response", "extract_signals")
    graph.add_edge("extract_signals", "encode_memory")
    graph.add_edge("encode_memory", END)

    return graph.compile()


# ═══════ WF-2: Weekly Prep Graph ═══════

class WeeklyPrepState(TypedDict):
    user_id: uuid.UUID
    deadlines: list[dict]
    stats: dict
    plan: str
    db: AsyncSession


async def node_load_deadlines(state: WeeklyPrepState) -> dict:
    from services.workflow.weekly_prep import load_upcoming_deadlines
    deadlines = await load_upcoming_deadlines(state["db"], state["user_id"])
    return {"deadlines": deadlines}


async def node_load_stats(state: WeeklyPrepState) -> dict:
    from services.workflow.weekly_prep import get_recent_study_stats
    stats = await get_recent_study_stats(state["db"], state["user_id"])
    return {"stats": stats}


async def node_generate_plan(state: WeeklyPrepState) -> dict:
    from services.llm.router import get_llm_client
    from sqlalchemy import select
    from models.course import Course

    db = state["db"]
    courses_result = await db.execute(select(Course).where(Course.user_id == state["user_id"]))
    courses = courses_result.scalars().all()

    deadline_text = "\n".join(
        f"- [{d['type']}] {d['course']}: {d['title']} (due in {d['days_until_due']} days)"
        for d in state["deadlines"]
    ) or "No upcoming deadlines."

    stats = state["stats"]
    stats_text = (
        f"Last 7 days: {stats['sessions_count']} sessions, "
        f"{stats['total_minutes']} minutes studied, "
        f"{stats['problems_attempted']} problems ({stats['accuracy']:.0%} accuracy)"
    )

    client = get_llm_client()
    plan, _ = await client.chat(
        "You are a study planning assistant. Create actionable weekly plans.",
        f"## Upcoming Deadlines\n{deadline_text}\n\n## Performance\n{stats_text}\n\n"
        f"## Courses\n{chr(10).join(f'- {c.name}' for c in courses)}\n\n"
        "Create a day-by-day plan (Mon-Sun). Output in markdown.",
    )
    return {"plan": plan}


def build_weekly_prep_graph() -> StateGraph:
    """Build the WF-2 Weekly Prep StateGraph."""
    graph = StateGraph(WeeklyPrepState)
    graph.add_node("load_deadlines", node_load_deadlines)
    graph.add_node("load_stats", node_load_stats)
    graph.add_node("generate_plan", node_generate_plan)

    graph.set_entry_point("load_deadlines")
    graph.add_edge("load_deadlines", "load_stats")
    graph.add_edge("load_stats", "generate_plan")
    graph.add_edge("generate_plan", END)

    return graph.compile()


# ═══════ WF-1: Semester Init Graph ═══════

class SemesterInitState(TypedDict):
    user_id: uuid.UUID
    semester_name: str
    course_list: list[dict]
    courses: list           # Created Course objects
    plan: str
    db: AsyncSession


async def node_create_courses(state: SemesterInitState) -> dict:
    """Create courses from user input (delegates to semester_init module)."""
    from services.workflow.semester_init import create_courses
    courses = await create_courses(state["db"], state["user_id"], state["course_list"])
    return {"courses": courses}


async def node_setup_prefs(state: SemesterInitState) -> dict:
    """Set up course-level preference defaults per course type."""
    from services.workflow.semester_init import setup_course_preferences
    for i, course in enumerate(state["courses"]):
        course_type = state["course_list"][i].get("type", "stem") if i < len(state["course_list"]) else "stem"
        await setup_course_preferences(state["db"], state["user_id"], course, course_type)
    return {}


async def node_generate_semester_plan(state: SemesterInitState) -> dict:
    """Generate initial semester study plan via LLM."""
    from services.workflow.semester_init import generate_semester_plan
    plan = await generate_semester_plan(state["db"], state["user_id"], state["courses"])
    return {"plan": plan}


def build_semester_init_graph() -> StateGraph:
    """Build the WF-1 Semester Init StateGraph."""
    graph = StateGraph(SemesterInitState)
    graph.add_node("create_courses", node_create_courses)
    graph.add_node("setup_prefs", node_setup_prefs)
    graph.add_node("generate_plan", node_generate_semester_plan)

    graph.set_entry_point("create_courses")
    graph.add_edge("create_courses", "setup_prefs")
    graph.add_edge("setup_prefs", "generate_plan")
    graph.add_edge("generate_plan", END)

    return graph.compile()


# ═══════ WF-3: Assignment Analysis Graph ═══════

class AssignmentAnalysisState(TypedDict):
    user_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_text: str
    relevant_docs: list[dict]
    analysis: str
    db: AsyncSession


async def node_load_assignment(state: AssignmentAnalysisState) -> dict:
    """Load assignment from DB."""
    from services.workflow.assignment_analysis import load_assignment_content
    assignment = await load_assignment_content(state["db"], state["assignment_id"])
    if assignment:
        return {"assignment_text": f"{assignment.title}\n{assignment.description or ''}"}
    return {"assignment_text": ""}


async def node_find_relevant_content(state: AssignmentAnalysisState) -> dict:
    """Find relevant course content via hybrid search."""
    from services.workflow.assignment_analysis import load_assignment_content, find_relevant_content
    if not state.get("assignment_text"):
        return {"relevant_docs": []}
    assignment = await load_assignment_content(state["db"], state["assignment_id"])
    if not assignment:
        return {"relevant_docs": []}
    docs = await find_relevant_content(state["db"], assignment.course_id, state["assignment_text"])
    return {"relevant_docs": docs}


async def node_generate_analysis(state: AssignmentAnalysisState) -> dict:
    """Generate assignment analysis using LLM."""
    from services.workflow.assignment_analysis import ANALYSIS_PROMPT
    from services.llm.router import get_llm_client

    context = "\n\n".join(
        f"### {doc['title']}\n{doc['content']}"
        for doc in state.get("relevant_docs", [])
    ) or "No relevant course materials found."

    client = get_llm_client()
    analysis, _ = await client.chat(
        "You are a teaching assistant helping students understand assignments.",
        ANALYSIS_PROMPT.format(
            assignment_text=state.get("assignment_text", ""),
            context=context,
        ),
    )
    return {"analysis": analysis}


def build_assignment_analysis_graph() -> StateGraph:
    """Build the WF-3 Assignment Analysis StateGraph."""
    graph = StateGraph(AssignmentAnalysisState)
    graph.add_node("load_assignment", node_load_assignment)
    graph.add_node("find_content", node_find_relevant_content)
    graph.add_node("generate_analysis", node_generate_analysis)

    graph.set_entry_point("load_assignment")
    graph.add_edge("load_assignment", "find_content")
    graph.add_edge("find_content", "generate_analysis")
    graph.add_edge("generate_analysis", END)

    return graph.compile()


# ═══════ WF-5: Wrong Answer Review Graph ═══════

class WrongAnswerReviewState(TypedDict):
    user_id: uuid.UUID
    course_id: uuid.UUID | None
    wrong_answers: list
    review: str
    wrong_answer_ids: list[str]
    db: AsyncSession


async def node_load_wrong_answers(state: WrongAnswerReviewState) -> dict:
    """Load unmastered wrong answers."""
    from services.workflow.wrong_answer_review import get_unmastered_wrong_answers
    wrong_answers = await get_unmastered_wrong_answers(
        state["db"], state["user_id"], state.get("course_id"),
    )
    return {
        "wrong_answers": wrong_answers,
        "wrong_answer_ids": [str(wa.id) for wa in wrong_answers],
    }


async def node_generate_review(state: WrongAnswerReviewState) -> dict:
    """Generate targeted review material from wrong answers."""
    from services.workflow.wrong_answer_review import generate_review_material
    wrong_answers = state.get("wrong_answers", [])
    if not wrong_answers:
        return {"review": "All questions mastered! No wrong answers to review."}

    course_id = state.get("course_id") or (wrong_answers[0].course_id if wrong_answers else None)
    if not course_id:
        return {"review": "No course context available."}

    review = await generate_review_material(state["db"], wrong_answers, course_id)
    return {"review": review}


def build_wrong_answer_review_graph() -> StateGraph:
    """Build the WF-5 Wrong Answer Review StateGraph."""
    graph = StateGraph(WrongAnswerReviewState)
    graph.add_node("load_wrong_answers", node_load_wrong_answers)
    graph.add_node("generate_review", node_generate_review)

    graph.set_entry_point("load_wrong_answers")
    graph.add_edge("load_wrong_answers", "generate_review")
    graph.add_edge("generate_review", END)

    return graph.compile()


# ═══════ WF-6: Exam Prep Graph ═══════

class ExamPrepState(TypedDict):
    user_id: uuid.UUID
    course_id: uuid.UUID
    exam_topic: str | None
    days_until_exam: int
    topics: list[dict]
    readiness: dict
    plan: str
    db: AsyncSession


async def node_get_topics(state: ExamPrepState) -> dict:
    """Load course topics from content tree."""
    from services.workflow.exam_prep import get_course_topics
    topics = await get_course_topics(state["db"], state["course_id"])
    return {"topics": topics}


async def node_assess_readiness(state: ExamPrepState) -> dict:
    """Assess exam readiness based on study history."""
    from services.workflow.exam_prep import assess_readiness
    readiness = await assess_readiness(state["db"], state["user_id"], state["course_id"])
    return {"readiness": readiness}


async def node_generate_exam_plan(state: ExamPrepState) -> dict:
    """Generate targeted exam prep plan via LLM."""
    from services.llm.router import get_llm_client
    from sqlalchemy import select
    from models.course import Course

    db = state["db"]
    course_result = await db.execute(
        select(Course).where(Course.id == state["course_id"])
    )
    course = course_result.scalar_one_or_none()
    course_name = course.name if course else "Unknown Course"

    topics_text = "\n".join(
        f"- {t['title']}: {', '.join(t['subtopics'][:5])}"
        for t in state.get("topics", [])
    ) or "No course topics available."

    readiness = state.get("readiness", {})
    readiness_text = (
        f"Study time: {readiness.get('total_study_time_minutes', 0)} minutes total\n"
        f"Problems: {readiness.get('problems_attempted', 0)} attempted, "
        f"{readiness.get('accuracy', 0):.0%} accuracy\n"
        f"Weak areas: {readiness.get('unmastered_wrong_answers', 0)} unmastered wrong answers\n"
        f"Sessions: {readiness.get('session_count', 0)} study sessions"
    )

    client = get_llm_client()
    plan, _ = await client.chat(
        "You are an exam preparation expert. Create focused, effective study plans.",
        f"""Create an exam preparation plan for {course_name}.
{f'Exam focus: {state.get("exam_topic")}' if state.get("exam_topic") else ''}
Days until exam: {state.get("days_until_exam", 7)}

## Course Topics
{topics_text}

## Student Readiness
{readiness_text}

Create a plan with: Priority Topics, Day-by-Day Schedule, Review Strategy, Practice Problems, Exam Day Tips.
Be realistic about the available time. Focus on high-impact areas. Output in markdown.""",
    )
    return {"plan": plan}


def build_exam_prep_graph() -> StateGraph:
    """Build the WF-6 Exam Prep StateGraph."""
    graph = StateGraph(ExamPrepState)
    graph.add_node("get_topics", node_get_topics)
    graph.add_node("assess_readiness", node_assess_readiness)
    graph.add_node("generate_plan", node_generate_exam_plan)

    graph.set_entry_point("get_topics")
    graph.add_edge("get_topics", "assess_readiness")
    graph.add_edge("assess_readiness", "generate_plan")
    graph.add_edge("generate_plan", END)

    return graph.compile()


# ═══════ Convenience runners ═══════

_study_graph = None
_weekly_graph = None
_semester_init_graph = None
_assignment_analysis_graph = None
_wrong_answer_review_graph = None
_exam_prep_graph = None


def get_study_session_graph():
    global _study_graph
    if _study_graph is None:
        _study_graph = build_study_session_graph()
    return _study_graph


def get_weekly_prep_graph():
    global _weekly_graph
    if _weekly_graph is None:
        _weekly_graph = build_weekly_prep_graph()
    return _weekly_graph


def get_semester_init_graph():
    global _semester_init_graph
    if _semester_init_graph is None:
        _semester_init_graph = build_semester_init_graph()
    return _semester_init_graph


def get_assignment_analysis_graph():
    global _assignment_analysis_graph
    if _assignment_analysis_graph is None:
        _assignment_analysis_graph = build_assignment_analysis_graph()
    return _assignment_analysis_graph


def get_wrong_answer_review_graph():
    global _wrong_answer_review_graph
    if _wrong_answer_review_graph is None:
        _wrong_answer_review_graph = build_wrong_answer_review_graph()
    return _wrong_answer_review_graph


def get_exam_prep_graph():
    global _exam_prep_graph
    if _exam_prep_graph is None:
        _exam_prep_graph = build_exam_prep_graph()
    return _exam_prep_graph


async def run_study_session_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    user_message: str,
) -> dict:
    """Run WF-4 via LangGraph using the shared orchestrator path."""
    from services.workflow.study_session import run_study_session

    return await run_study_session(db, user_id, course_id, user_message)


async def run_weekly_prep_graph(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Run WF-2 via LangGraph."""
    graph = get_weekly_prep_graph()
    initial_state: WeeklyPrepState = {
        "user_id": user_id,
        "deadlines": [],
        "stats": {},
        "plan": "",
        "db": db,
    }
    result = await graph.ainvoke(initial_state)
    return {
        "deadlines": result.get("deadlines", []),
        "stats": result.get("stats", {}),
        "plan": result.get("plan", ""),
    }


async def run_semester_init_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    semester_name: str,
    course_list: list[dict],
) -> dict:
    """Run WF-1 via LangGraph."""
    graph = get_semester_init_graph()
    initial_state: SemesterInitState = {
        "user_id": user_id,
        "semester_name": semester_name,
        "course_list": course_list,
        "courses": [],
        "plan": "",
        "db": db,
    }
    result = await graph.ainvoke(initial_state)
    return {
        "semester": semester_name,
        "courses_created": len(result.get("courses", [])),
        "course_ids": [str(c.id) for c in result.get("courses", [])],
        "plan": result.get("plan", ""),
    }


async def run_assignment_analysis_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> dict:
    """Run WF-3 via LangGraph."""
    graph = get_assignment_analysis_graph()
    initial_state: AssignmentAnalysisState = {
        "user_id": user_id,
        "assignment_id": assignment_id,
        "assignment_text": "",
        "relevant_docs": [],
        "analysis": "",
        "db": db,
    }
    result = await graph.ainvoke(initial_state)
    return {
        "assignment_id": str(assignment_id),
        "analysis": result.get("analysis", ""),
        "relevant_content_count": len(result.get("relevant_docs", [])),
    }


async def run_wrong_answer_review_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Run WF-5 via LangGraph."""
    graph = get_wrong_answer_review_graph()
    initial_state: WrongAnswerReviewState = {
        "user_id": user_id,
        "course_id": course_id,
        "wrong_answers": [],
        "review": "",
        "wrong_answer_ids": [],
        "db": db,
    }
    result = await graph.ainvoke(initial_state)
    return {
        "review": result.get("review", ""),
        "wrong_answer_count": len(result.get("wrong_answers", [])),
        "wrong_answer_ids": result.get("wrong_answer_ids", []),
    }


async def run_exam_prep_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    exam_topic: str | None = None,
    days_until_exam: int = 7,
) -> dict:
    """Run WF-6 via LangGraph."""
    graph = get_exam_prep_graph()
    initial_state: ExamPrepState = {
        "user_id": user_id,
        "course_id": course_id,
        "exam_topic": exam_topic,
        "days_until_exam": days_until_exam,
        "topics": [],
        "readiness": {},
        "plan": "",
        "db": db,
    }
    result = await graph.ainvoke(initial_state)

    from sqlalchemy import select
    from models.course import Course
    course_result = await db.execute(select(Course).where(Course.id == course_id))
    course = course_result.scalar_one_or_none()

    return {
        "course": course.name if course else "Unknown",
        "topics_count": len(result.get("topics", [])),
        "readiness": result.get("readiness", {}),
        "days_until_exam": days_until_exam,
        "plan": result.get("plan", ""),
    }
