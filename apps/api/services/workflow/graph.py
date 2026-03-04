"""LangGraph-based workflow engine.

Converts all 6 workflows to LangGraph StateGraph with proper node/edge definitions.
Each workflow is a compiled StateGraph that can be invoked with `.ainvoke(state)`.

UPGRADED: WF-4 now uses multi-agent orchestrator for intent-aware routing
and MemCell-based memory encoding.

All graphs are compiled with optional PostgreSQL checkpoint persistence
(via ``langgraph-checkpoint-postgres``).  When available, each graph invocation
can be given a ``thread_id`` config for crash-safe state recovery.

Reference from spec:
- Phase 0: "LangGraph workflows: WF-2 Weekly Prep + WF-4 Study Session"
- Phase 1: "Complete set of 6 workflows"
"""

import uuid
import logging
from typing import TypedDict, Annotated, Any
from operator import add

from langgraph.graph import StateGraph, END

from services.workflow.checkpoint import get_checkpointer, make_thread_id

logger = logging.getLogger(__name__)


def _get_db(config: dict) -> Any:
    """Extract the AsyncSession from LangGraph config.

    db is NOT stored in State (it's not serializable) — it's passed
    via ``config["configurable"]["db"]`` so the checkpointer never
    tries to persist it.
    """
    return config["configurable"]["db"]


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


async def node_classify_intent(state: StudyState, config: dict) -> dict:
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


async def node_load_context(state: StudyState, config: dict) -> dict:
    from services.agent.registry import build_agent_context
    from services.agent.context_builder import load_context
    from services.agent.state import IntentType

    db = _get_db(config)
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
    ctx = await load_context(ctx, db)
    return {
        "preferences": ctx.preferences,
        "memories": ctx.memories,
        "content_docs": ctx.content_docs,
    }


async def node_search_content(state: StudyState, config: dict) -> dict:
    return {}


async def node_generate_response(state: StudyState, config: dict) -> dict:
    """Route to appropriate specialist agent based on intent."""
    from services.agent.state import AgentContext, IntentType
    from services.agent.orchestrator import apply_reflection
    from services.agent.registry import get_agent

    db = _get_db(config)
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
    ctx = await agent.run(ctx, db)
    ctx = await apply_reflection(ctx)
    return {"response": ctx.response, "system_prompt": ""}


async def node_extract_signals(state: StudyState, config: dict) -> dict:
    # WF-4 now delegates post-processing to the shared orchestrator path.
    return {"signal": None}


async def node_encode_memory(state: StudyState, config: dict) -> dict:
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

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ WF-2: Weekly Prep Graph ═══════

class WeeklyPrepState(TypedDict):
    user_id: uuid.UUID
    deadlines: list[dict]
    stats: dict
    plan: str


async def node_load_deadlines(state: WeeklyPrepState, config: dict) -> dict:
    from services.workflow.weekly_prep import load_upcoming_deadlines
    db = _get_db(config)
    deadlines = await load_upcoming_deadlines(db, state["user_id"])
    return {"deadlines": deadlines}


async def node_load_stats(state: WeeklyPrepState, config: dict) -> dict:
    from services.workflow.weekly_prep import get_recent_study_stats
    db = _get_db(config)
    stats = await get_recent_study_stats(db, state["user_id"])
    return {"stats": stats}


async def node_generate_plan(state: WeeklyPrepState, config: dict) -> dict:
    from services.llm.router import get_llm_client
    from sqlalchemy import select
    from models.course import Course

    db = _get_db(config)
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

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ WF-1: Semester Init Graph ═══════

class SemesterInitState(TypedDict):
    user_id: uuid.UUID
    semester_name: str
    course_list: list[dict]
    courses: list           # Created Course objects
    plan: str


async def node_create_courses(state: SemesterInitState, config: dict) -> dict:
    """Create courses from user input (delegates to semester_init module)."""
    from services.workflow.semester_init import create_courses
    db = _get_db(config)
    courses = await create_courses(db, state["user_id"], state["course_list"])
    return {"courses": courses}


async def node_setup_prefs(state: SemesterInitState, config: dict) -> dict:
    """Set up course-level preference defaults per course type."""
    from services.workflow.semester_init import setup_course_preferences
    db = _get_db(config)
    for i, course in enumerate(state["courses"]):
        course_type = state["course_list"][i].get("type", "stem") if i < len(state["course_list"]) else "stem"
        await setup_course_preferences(db, state["user_id"], course, course_type)
    return {}


async def node_generate_semester_plan(state: SemesterInitState, config: dict) -> dict:
    """Generate initial semester study plan via LLM."""
    from services.workflow.semester_init import generate_semester_plan
    db = _get_db(config)
    plan = await generate_semester_plan(db, state["user_id"], state["courses"])
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

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ WF-3: Assignment Analysis Graph ═══════

class AssignmentAnalysisState(TypedDict):
    user_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_text: str
    relevant_docs: list[dict]
    analysis: str


async def node_load_assignment(state: AssignmentAnalysisState, config: dict) -> dict:
    """Load assignment from DB."""
    from services.workflow.assignment_analysis import load_assignment_content
    db = _get_db(config)
    assignment = await load_assignment_content(db, state["assignment_id"])
    if assignment:
        return {"assignment_text": f"{assignment.title}\n{assignment.description or ''}"}
    return {"assignment_text": ""}


async def node_find_relevant_content(state: AssignmentAnalysisState, config: dict) -> dict:
    """Find relevant course content via hybrid search."""
    from services.workflow.assignment_analysis import load_assignment_content, find_relevant_content
    db = _get_db(config)
    if not state.get("assignment_text"):
        return {"relevant_docs": []}
    assignment = await load_assignment_content(db, state["assignment_id"])
    if not assignment:
        return {"relevant_docs": []}
    docs = await find_relevant_content(db, assignment.course_id, state["assignment_text"])
    return {"relevant_docs": docs}


async def node_generate_analysis(state: AssignmentAnalysisState, config: dict) -> dict:
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

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ WF-5: Wrong Answer Review Graph ═══════

class WrongAnswerReviewState(TypedDict):
    user_id: uuid.UUID
    course_id: uuid.UUID | None
    wrong_answers: list
    review: str
    wrong_answer_ids: list[str]


async def node_load_wrong_answers(state: WrongAnswerReviewState, config: dict) -> dict:
    """Load unmastered wrong answers."""
    from services.workflow.wrong_answer_review import get_unmastered_wrong_answers
    db = _get_db(config)
    wrong_answers = await get_unmastered_wrong_answers(
        db, state["user_id"], state.get("course_id"),
    )
    return {
        "wrong_answers": wrong_answers,
        "wrong_answer_ids": [str(wa.id) for wa in wrong_answers],
    }


async def node_generate_review(state: WrongAnswerReviewState, config: dict) -> dict:
    """Generate targeted review material from wrong answers."""
    from services.workflow.wrong_answer_review import generate_review_material
    db = _get_db(config)
    wrong_answers = state.get("wrong_answers", [])
    if not wrong_answers:
        return {"review": "All questions mastered! No wrong answers to review."}

    course_id = state.get("course_id") or (wrong_answers[0].course_id if wrong_answers else None)
    if not course_id:
        return {"review": "No course context available."}

    review = await generate_review_material(db, wrong_answers, course_id)
    return {"review": review}


def build_wrong_answer_review_graph() -> StateGraph:
    """Build the WF-5 Wrong Answer Review StateGraph."""
    graph = StateGraph(WrongAnswerReviewState)
    graph.add_node("load_wrong_answers", node_load_wrong_answers)
    graph.add_node("generate_review", node_generate_review)

    graph.set_entry_point("load_wrong_answers")
    graph.add_edge("load_wrong_answers", "generate_review")
    graph.add_edge("generate_review", END)

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ WF-6: Exam Prep Graph ═══════

class ExamPrepState(TypedDict):
    user_id: uuid.UUID
    course_id: uuid.UUID
    exam_topic: str | None
    days_until_exam: int
    topics: list[dict]
    readiness: dict
    plan: str


async def node_get_topics(state: ExamPrepState, config: dict) -> dict:
    """Load course topics from content tree."""
    from services.workflow.exam_prep import get_course_topics
    db = _get_db(config)
    topics = await get_course_topics(db, state["course_id"])
    return {"topics": topics}


async def node_assess_readiness(state: ExamPrepState, config: dict) -> dict:
    """Assess exam readiness based on study history."""
    from services.workflow.exam_prep import assess_readiness
    db = _get_db(config)
    readiness = await assess_readiness(db, state["user_id"], state["course_id"])
    return {"readiness": readiness}


async def node_generate_exam_plan(state: ExamPrepState, config: dict) -> dict:
    """Generate targeted exam prep plan via LLM."""
    from services.llm.router import get_llm_client
    from sqlalchemy import select
    from models.course import Course

    db = _get_db(config)
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

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ WF-7: Goal Pursuit Graph (Plan-Execute-Replan) ═══════


class GoalPursuitState(TypedDict):
    """State for the Plan-Execute-Replan goal pursuit loop.

    Inspired by LangGraph Plan-and-Execute pattern + OpenClaw Heartbeat.
    """
    user_id: uuid.UUID
    course_id: uuid.UUID | None
    goal_id: uuid.UUID
    goal_title: str
    goal_objective: str
    plan: list[dict]           # LLM-generated steps [{title, description, tool, done}]
    current_step: int
    observations: Annotated[list[dict], add]  # execution results appended per step
    done: bool
    max_steps: int


async def node_plan(state: GoalPursuitState, config: dict) -> dict:
    """Planner node: LLM generates a step-by-step plan for the goal."""
    from services.llm.router import get_llm_client

    client = get_llm_client()
    prompt = (
        f"You are a study planning assistant. Create a concrete, actionable plan.\n\n"
        f"## Goal\n{state['goal_title']}\n\n"
        f"## Objective\n{state['goal_objective']}\n\n"
    )

    if state.get("observations"):
        obs_text = "\n".join(
            f"- Step {o.get('step', '?')}: {o.get('result', 'no result')}"
            for o in state["observations"]
        )
        prompt += f"## Previous observations\n{obs_text}\n\n"

    prompt += (
        "Create 3-5 concrete steps. Output as JSON array: "
        '[{"title": "...", "description": "...", "tool": "generate_quiz|create_flashcard|review_material|search_content|notify", "done": false}]'
    )

    try:
        response, _ = await client.extract(
            system_prompt="You output valid JSON arrays only. No markdown fences.",
            user_message=prompt,
        )
        import json
        plan = json.loads(response)
        if not isinstance(plan, list):
            plan = [{"title": "Study goal", "description": state["goal_objective"], "tool": "review_material", "done": False}]
    except Exception as e:
        logger.warning("Goal planner LLM failed: %s", e)
        plan = [{"title": "Study goal", "description": state["goal_objective"], "tool": "review_material", "done": False}]

    return {"plan": plan, "current_step": 0}


async def node_execute(state: GoalPursuitState, config: dict) -> dict:
    """Executor node: execute the current plan step."""
    from services.activity.engine import submit_task

    db = _get_db(config)
    plan = state.get("plan", [])
    step_idx = state.get("current_step", 0)

    if step_idx >= len(plan):
        return {"done": True, "observations": [{"step": step_idx, "result": "All steps complete"}]}

    step = plan[step_idx]
    tool = step.get("tool", "review_material")
    result = f"Executed: {step.get('title', 'unnamed step')}"

    try:
        if tool == "notify":
            from services.notification.dispatcher import dispatch as dispatch_notification
            await dispatch_notification(
                user_id=state["user_id"],
                title=step.get("title", "Study reminder"),
                body=step.get("description", ""),
                category="goal_pursuit",
                course_id=state.get("course_id"),
                priority="normal",
                db=db,
            )
            result = f"Sent notification: {step.get('title')}"
        else:
            # Map tool → task_type; build input_json
            course_id_str = str(state.get("course_id")) if state.get("course_id") else None
            desc = step.get("description", "")
            title = step.get("title", tool.replace("_", " ").title())
            input_json: dict = {"description": desc}
            task_type = tool if tool in ("generate_quiz", "create_flashcard") else "multi_step"
            if tool == "generate_quiz":
                input_json.update(course_id=course_id_str, topic=desc, count=3, title=title)
            elif tool == "create_flashcard":
                input_json.update(course_id=course_id_str, count=5, title=title)
            task = await submit_task(
                user_id=state["user_id"],
                course_id=state.get("course_id"),
                goal_id=state["goal_id"],
                task_type=task_type,
                title=title,
                summary=desc,
                source="goal_pursuit",
                input_json=input_json,
                max_attempts=2,
            )
            result = f"Queued {task_type} task: {task.id}"

    except Exception as e:
        result = f"Failed: {e}"
        logger.warning("Goal pursuit executor failed on step %d: %s", step_idx, e)

    return {
        "current_step": step_idx + 1,
        "observations": [{"step": step_idx, "tool": tool, "result": result}],
    }


async def node_replan(state: GoalPursuitState, config: dict) -> dict:
    """Replanner node: decide whether to continue, replan, or stop.

    Fault-tolerant: a single step failure skips to the next step instead of
    aborting the entire plan.  Only stops after 2 consecutive failures.
    """
    plan = state.get("plan", [])
    step_idx = state.get("current_step", 0)
    max_steps = state.get("max_steps", 5)

    if step_idx >= len(plan) or step_idx >= max_steps:
        return {"done": True}

    # Check consecutive failures — abort only after 2 consecutive failures
    observations = state.get("observations", [])
    consecutive_failures = 0
    for obs in reversed(observations):
        if "Failed" in obs.get("result", ""):
            consecutive_failures += 1
        else:
            break

    if consecutive_failures >= 2:
        logger.info(
            "Goal pursuit: %d consecutive failures, stopping at step %d",
            consecutive_failures, step_idx,
        )
        return {"done": True}

    if consecutive_failures == 1:
        logger.info(
            "Goal pursuit: step %d failed, skipping to next step",
            step_idx - 1,
        )

    return {"done": False}


def _should_continue(state: GoalPursuitState) -> str:
    """Conditional edge: continue executing or finish."""
    if state.get("done", False):
        return END
    return "execute"


def build_goal_pursuit_graph() -> StateGraph:
    """Build the WF-7 Goal Pursuit StateGraph (Plan-Execute-Replan loop)."""
    graph = StateGraph(GoalPursuitState)
    graph.add_node("plan", node_plan)
    graph.add_node("execute", node_execute)
    graph.add_node("replan", node_replan)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "replan")
    graph.add_conditional_edges("replan", _should_continue)

    return graph.compile(checkpointer=get_checkpointer())


# ═══════ Graph registry ═══════

_GRAPH_BUILDERS = {
    "study_session": build_study_session_graph,
    "weekly_prep": build_weekly_prep_graph,
    "semester_init": build_semester_init_graph,
    "assignment_analysis": build_assignment_analysis_graph,
    "wrong_answer_review": build_wrong_answer_review_graph,
    "exam_prep": build_exam_prep_graph,
    "goal_pursuit": build_goal_pursuit_graph,
}
_graph_cache: dict[str, Any] = {}


def _get_graph(name: str):
    if name not in _graph_cache:
        _graph_cache[name] = _GRAPH_BUILDERS[name]()
    return _graph_cache[name]


def invalidate_graph_singletons():
    """Reset all cached graph singletons so they are re-compiled on next use."""
    _graph_cache.clear()
    logger.info("Graph singletons invalidated — will re-compile with checkpointer on next use")


async def run_study_session_graph(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    user_message: str,
) -> dict:
    """Run WF-4 via LangGraph using the shared orchestrator path."""
    from services.workflow.study_session import run_study_session

    return await run_study_session(db, user_id, course_id, user_message)


async def run_weekly_prep_graph(db, user_id: uuid.UUID) -> dict:
    """Run WF-2 via LangGraph."""
    graph = _get_graph("weekly_prep")
    initial_state: WeeklyPrepState = {
        "user_id": user_id,
        "deadlines": [],
        "stats": {},
        "plan": "",
    }
    config = {"configurable": {"thread_id": make_thread_id(user_id, workflow="weekly_prep"), "db": db}}
    result = await graph.ainvoke(initial_state, config)
    return {
        "deadlines": result.get("deadlines", []),
        "stats": result.get("stats", {}),
        "plan": result.get("plan", ""),
    }


async def run_semester_init_graph(
    db,
    user_id: uuid.UUID,
    semester_name: str,
    course_list: list[dict],
) -> dict:
    """Run WF-1 via LangGraph."""
    graph = _get_graph("semester_init")
    initial_state: SemesterInitState = {
        "user_id": user_id,
        "semester_name": semester_name,
        "course_list": course_list,
        "courses": [],
        "plan": "",
    }
    config = {"configurable": {"thread_id": make_thread_id(user_id, workflow="semester_init"), "db": db}}
    result = await graph.ainvoke(initial_state, config)
    return {
        "semester": semester_name,
        "courses_created": len(result.get("courses", [])),
        "course_ids": [str(c.id) for c in result.get("courses", [])],
        "plan": result.get("plan", ""),
    }


async def run_assignment_analysis_graph(
    db,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> dict:
    """Run WF-3 via LangGraph."""
    graph = _get_graph("assignment_analysis")
    initial_state: AssignmentAnalysisState = {
        "user_id": user_id,
        "assignment_id": assignment_id,
        "assignment_text": "",
        "relevant_docs": [],
        "analysis": "",
    }
    config = {"configurable": {"thread_id": make_thread_id(user_id, workflow="assignment_analysis"), "db": db}}
    result = await graph.ainvoke(initial_state, config)
    return {
        "assignment_id": str(assignment_id),
        "analysis": result.get("analysis", ""),
        "relevant_content_count": len(result.get("relevant_docs", [])),
    }


async def run_wrong_answer_review_graph(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Run WF-5 via LangGraph."""
    graph = _get_graph("wrong_answer_review")
    initial_state: WrongAnswerReviewState = {
        "user_id": user_id,
        "course_id": course_id,
        "wrong_answers": [],
        "review": "",
        "wrong_answer_ids": [],
    }
    config = {"configurable": {"thread_id": make_thread_id(user_id, course_id, "wrong_answer_review"), "db": db}}
    result = await graph.ainvoke(initial_state, config)
    return {
        "review": result.get("review", ""),
        "wrong_answer_count": len(result.get("wrong_answers", [])),
        "wrong_answer_ids": result.get("wrong_answer_ids", []),
    }


async def run_exam_prep_graph(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    exam_topic: str | None = None,
    days_until_exam: int = 7,
) -> dict:
    """Run WF-6 via LangGraph."""
    graph = _get_graph("exam_prep")
    initial_state: ExamPrepState = {
        "user_id": user_id,
        "course_id": course_id,
        "exam_topic": exam_topic,
        "days_until_exam": days_until_exam,
        "topics": [],
        "readiness": {},
        "plan": "",
    }
    config = {"configurable": {"thread_id": make_thread_id(user_id, course_id, "exam_prep"), "db": db}}
    result = await graph.ainvoke(initial_state, config)

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


async def run_goal_pursuit_graph(
    db,
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    goal_title: str,
    goal_objective: str,
    course_id: uuid.UUID | None = None,
    max_steps: int = 5,
) -> dict:
    """Run WF-7 Goal Pursuit (Plan-Execute-Replan) via LangGraph."""
    graph = _get_graph("goal_pursuit")
    initial_state: GoalPursuitState = {
        "user_id": user_id,
        "course_id": course_id,
        "goal_id": goal_id,
        "goal_title": goal_title,
        "goal_objective": goal_objective,
        "plan": [],
        "current_step": 0,
        "observations": [],
        "done": False,
        "max_steps": max_steps,
    }
    config = {"configurable": {"thread_id": make_thread_id(user_id, course_id, "goal_pursuit"), "db": db}}
    result = await graph.ainvoke(initial_state, config)
    return {
        "goal_id": str(goal_id),
        "plan": result.get("plan", []),
        "observations": result.get("observations", []),
        "steps_executed": result.get("current_step", 0),
        "done": result.get("done", False),
    }
