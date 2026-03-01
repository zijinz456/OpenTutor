"""Policy-based scene selection and switch recommendation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask
from models.content import CourseContentTree
from models.course import Course
from models.ingestion import Assignment, WrongAnswer
from models.progress import LearningProgress
from models.study_goal import StudyGoal
from services.activity.tasks import APPROVAL_REQUIRED_STATUS
from services.agent.state import SceneName
from services.spaced_repetition.forgetting_forecast import predict_forgetting

SCENES = tuple(s.value for s in SceneName)

SCENE_CUE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "exam_prep": [
        re.compile(r"(exam|final|midterm|quiz prep|prepare\s+for|cram|last[-\s]?minute|review\s+for)", re.IGNORECASE),
    ],
    "assignment": [
        re.compile(r"(assignment|homework|problem set|exercise|workbook|question)", re.IGNORECASE),
    ],
    "review_drill": [
        re.compile(r"(wrong answer|mistake|error analysis|correct\s+error|weak area|weak point)", re.IGNORECASE),
    ],
    "note_organize": [
        re.compile(r"(organize\s+\w*\s*notes|summary|outline|mind map|summarize|compile\s+notes|notes\s+organiz)", re.IGNORECASE),
    ],
    "study_session": [
        re.compile(r"(explain|teach|what is|how does|study|understand|concept|definition)", re.IGNORECASE),
    ],
}


@dataclass
class ScenePolicyDecision:
    scene_id: str
    scores: dict[str, float]
    confidence: float
    reason: str
    features: dict
    switch_recommended: bool
    expected_benefit: str
    reversible_action: str
    layout_policy: str
    reasoning_policy: str
    workflow_policy: str


async def resolve_scene_policy(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    current_scene: str = "study_session",
    active_tab: str = "",
) -> ScenePolicyDecision:
    features = await _collect_scene_features(
        db,
        user_id=user_id,
        course_id=course_id,
        message=message,
        active_tab=active_tab,
    )
    return decide_scene_policy_from_features(features=features, current_scene=current_scene)


def decide_scene_policy_from_features(*, features: dict, current_scene: str = "study_session") -> ScenePolicyDecision:
    scores = _score_scenes(features=features, current_scene=current_scene)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_scene, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = max(0.0, min(1.0, best_score / 6.0))
    margin = best_score - second_score
    switch_recommended = best_scene != current_scene and best_score >= 1.6 and margin >= 0.6
    reasons = _build_scene_reasons(best_scene, features)
    policy_bundle = _scene_policy_bundle(best_scene)

    return ScenePolicyDecision(
        scene_id=best_scene,
        scores=scores,
        confidence=confidence,
        reason=f"Selected {best_scene} because " + ", ".join(reasons) + ".",
        features=features,
        switch_recommended=switch_recommended,
        expected_benefit=policy_bundle["expected_benefit"],
        reversible_action=policy_bundle["reversible_action"],
        layout_policy=policy_bundle["layout_policy"],
        reasoning_policy=policy_bundle["reasoning_policy"],
        workflow_policy=policy_bundle["workflow_policy"],
    )


def _build_scene_reasons(scene_id: str, features: dict) -> list[str]:
    reasons = []
    urgent_forgetting_count = int(features.get("urgent_forgetting_count") or 0)
    recent_failed_tasks = int(features.get("recent_failed_tasks") or 0)
    if features["matched_cues"].get(scene_id):
        reasons.append(
            f"message cues matched {', '.join(repr(cue) for cue in features['matched_cues'][scene_id][:3])}"
        )
    if features.get("active_goal_title"):
        reasons.append(f"active goal '{features['active_goal_title']}' is in focus")
    if scene_id == "assignment" and features.get("nearest_deadline_days") is not None:
        reasons.append(f"the nearest assignment is due in {features['nearest_deadline_days']} day(s)")
    if scene_id == "review_drill" and features["unmastered_wrong_answers"] > 0:
        reasons.append(f"{features['unmastered_wrong_answers']} unmastered wrong answers need attention")
    if scene_id == "exam_prep" and features["low_mastery_count"] > 0:
        reasons.append(f"{features['low_mastery_count']} low-mastery concepts remain")
    if scene_id == "exam_prep" and urgent_forgetting_count > 0:
        reasons.append(f"{urgent_forgetting_count} concepts are near forgetting threshold")
    if recent_failed_tasks > 0:
        reasons.append(f"{recent_failed_tasks} recent task failures suggest a more guided mode")
    if scene_id == "note_organize" and features["content_nodes"] > 10:
        reasons.append(f"{features['content_nodes']} course content nodes are available for synthesis")
    if not reasons:
        reasons.append("defaulted to the highest-scoring study policy")
    return reasons


def _scene_policy_bundle(scene_id: str) -> dict[str, str]:
    bundles = {
        "study_session": {
            "layout_policy": "balanced_exploration",
            "reasoning_policy": "broad_then_deep",
            "workflow_policy": "interactive_tutoring",
            "expected_benefit": "Keeps notes, practice, and chat open for open-ended concept building.",
            "reversible_action": "Switch back anytime if you need a more task-specific mode.",
        },
        "exam_prep": {
            "layout_policy": "deadline_focus",
            "reasoning_policy": "prioritize_weaknesses",
            "workflow_policy": "time_boxed_execution",
            "expected_benefit": "Surfaces weak points, review queues, and short-horizon planning ahead of the exam.",
            "reversible_action": "Revert to daily study if you want broader explanations instead of exam triage.",
        },
        "assignment": {
            "layout_policy": "guided_execution",
            "reasoning_policy": "hint_first",
            "workflow_policy": "requirement_tracking",
            "expected_benefit": "Reduces distraction and keeps the assistant focused on requirements and next steps.",
            "reversible_action": "Switch back after the assignment block if you want broader review or synthesis.",
        },
        "review_drill": {
            "layout_policy": "error_repetition_loop",
            "reasoning_policy": "diagnose_then_rebuild",
            "workflow_policy": "mistake_recovery",
            "expected_benefit": "Pushes wrong answers and weak areas to the front so you can repair gaps quickly.",
            "reversible_action": "Switch back once the review queue is under control.",
        },
        "note_organize": {
            "layout_policy": "synthesis_first",
            "reasoning_policy": "compress_and_structure",
            "workflow_policy": "knowledge_consolidation",
            "expected_benefit": "Optimizes for structured summaries, outline cleanup, and cross-chapter integration.",
            "reversible_action": "Go back to study or review mode once the note set is clean.",
        },
    }
    return bundles.get(scene_id, bundles["study_session"])


async def _collect_scene_features(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    active_tab: str,
) -> dict:
    message = message or ""
    now = datetime.now(timezone.utc)
    deadline_cutoff = now + timedelta(days=14)

    assignment_result = await db.execute(
        select(func.count(Assignment.id))
        .where(Assignment.course_id == course_id, Assignment.status == "active")
    )
    nearest_assignment_result = await db.execute(
        select(Assignment)
        .where(
            Assignment.course_id == course_id,
            Assignment.status == "active",
            Assignment.due_date.is_not(None),
            Assignment.due_date <= deadline_cutoff,
        )
        .order_by(Assignment.due_date.asc())
        .limit(1)
    )
    wrong_answer_result = await db.execute(
        select(func.count(WrongAnswer.id))
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user_id,
            WrongAnswer.mastered.is_(False),
        )
    )
    low_mastery_result = await db.execute(
        select(func.count(LearningProgress.id))
        .where(
            LearningProgress.course_id == course_id,
            LearningProgress.user_id == user_id,
            LearningProgress.mastery_score < 0.55,
        )
    )
    content_result = await db.execute(
        select(func.count(CourseContentTree.id)).where(CourseContentTree.course_id == course_id)
    )
    course_result = await db.execute(select(Course).where(Course.id == course_id, Course.user_id == user_id))
    course = course_result.scalar_one_or_none()
    active_goal_result = await db.execute(
        select(StudyGoal)
        .where(
            StudyGoal.user_id == user_id,
            StudyGoal.course_id == course_id,
            StudyGoal.status == "active",
        )
        .order_by(StudyGoal.updated_at.desc(), StudyGoal.created_at.desc())
        .limit(1)
    )
    recent_failed_task_result = await db.execute(
        select(func.count(AgentTask.id))
        .where(
            AgentTask.user_id == user_id,
            AgentTask.course_id == course_id,
            AgentTask.status.in_(("failed", "cancelled", "rejected")),
        )
    )
    pending_approval_result = await db.execute(
        select(func.count(AgentTask.id))
        .where(
            AgentTask.user_id == user_id,
            AgentTask.course_id == course_id,
            AgentTask.status == APPROVAL_REQUIRED_STATUS,
        )
    )
    running_task_result = await db.execute(
        select(func.count(AgentTask.id))
        .where(
            AgentTask.user_id == user_id,
            AgentTask.course_id == course_id,
            AgentTask.status.in_(("queued", "running", "resuming", "cancel_requested")),
        )
    )
    active_goal = active_goal_result.scalar_one_or_none()
    nearest_assignment = nearest_assignment_result.scalar_one_or_none()
    nearest_deadline_days = None
    if nearest_assignment and nearest_assignment.due_date:
        due_date = nearest_assignment.due_date
        due_date = due_date if due_date.tzinfo else due_date.replace(tzinfo=timezone.utc)
        nearest_deadline_days = max(int((due_date - now).total_seconds() // 86400), 0)

    urgent_forgetting_count = 0
    warning_forgetting_count = 0
    try:
        forecast = await predict_forgetting(db, user_id, course_id)
        urgent_forgetting_count = int(forecast.get("urgent_count") or 0)
        warning_forgetting_count = int(forecast.get("warning_count") or 0)
    except Exception:
        urgent_forgetting_count = 0
        warning_forgetting_count = 0

    matched_cues = {
        scene: [
            match.group(0)
            for pattern in patterns
            for match in [pattern.search(message)]
            if match
        ]
        for scene, patterns in SCENE_CUE_PATTERNS.items()
    }

    active_goal_target_days = None
    if active_goal and active_goal.target_date:
        goal_due = active_goal.target_date
        goal_due = goal_due if goal_due.tzinfo else goal_due.replace(tzinfo=timezone.utc)
        active_goal_target_days = max(int((goal_due - now).total_seconds() // 86400), 0)

    return {
        "matched_cues": matched_cues,
        "upcoming_assignments": int(assignment_result.scalar() or 0),
        "unmastered_wrong_answers": int(wrong_answer_result.scalar() or 0),
        "low_mastery_count": int(low_mastery_result.scalar() or 0),
        "content_nodes": int(content_result.scalar() or 0),
        "active_tab": active_tab,
        "course_active_scene": course.active_scene if course else "study_session",
        "active_goal_title": active_goal.title if active_goal else None,
        "active_goal_next_action": active_goal.next_action if active_goal else None,
        "active_goal_target_days": active_goal_target_days,
        "nearest_deadline_days": nearest_deadline_days,
        "recent_failed_tasks": int(recent_failed_task_result.scalar() or 0),
        "pending_approval_count": int(pending_approval_result.scalar() or 0),
        "running_task_count": int(running_task_result.scalar() or 0),
        "urgent_forgetting_count": urgent_forgetting_count,
        "warning_forgetting_count": warning_forgetting_count,
    }


def _score_scenes(*, features: dict, current_scene: str) -> dict[str, float]:
    scores = {scene: 0.2 for scene in SCENES}
    urgent_forgetting_count = int(features.get("urgent_forgetting_count") or 0)
    warning_forgetting_count = int(features.get("warning_forgetting_count") or 0)
    recent_failed_tasks = int(features.get("recent_failed_tasks") or 0)
    pending_approval_count = int(features.get("pending_approval_count") or 0)
    running_task_count = int(features.get("running_task_count") or 0)

    for scene, cues in features["matched_cues"].items():
        scores[scene] += min(len(cues), 2) * 1.4

    if features["upcoming_assignments"] > 0:
        scores["assignment"] += 0.7
        scores["exam_prep"] += 0.4
    if features.get("nearest_deadline_days") is not None:
        if features["nearest_deadline_days"] <= 3:
            scores["assignment"] += 1.1
            scores["exam_prep"] += 0.8
        elif features["nearest_deadline_days"] <= 7:
            scores["assignment"] += 0.7
            scores["exam_prep"] += 0.6
    if features["unmastered_wrong_answers"] > 0:
        scores["review_drill"] += min(features["unmastered_wrong_answers"], 5) * 0.25
    if features["low_mastery_count"] > 0:
        scores["exam_prep"] += min(features["low_mastery_count"], 5) * 0.2
        scores["review_drill"] += min(features["low_mastery_count"], 5) * 0.1
    if urgent_forgetting_count > 0:
        scores["review_drill"] += min(urgent_forgetting_count, 5) * 0.25
        scores["exam_prep"] += min(urgent_forgetting_count, 5) * 0.15
    if warning_forgetting_count > 0:
        scores["study_session"] += min(warning_forgetting_count, 5) * 0.08
    if features["content_nodes"] >= 8:
        scores["note_organize"] += 0.5
        scores["study_session"] += 0.3
    if features.get("active_goal_title"):
        scores["study_session"] += 0.15
        if features.get("active_goal_target_days") is not None and features["active_goal_target_days"] <= 7:
            scores["exam_prep"] += 0.9
        if features.get("active_goal_next_action"):
            next_action = str(features["active_goal_next_action"]).lower()
            if any(keyword in next_action for keyword in ("review", "wrong answer", "mistake", "error")):
                scores["review_drill"] += 0.5
            if any(keyword in next_action for keyword in ("outline", "notes", "summary", "organize", "compile")):
                scores["note_organize"] += 0.5
            if any(keyword in next_action for keyword in ("assignment", "homework", "exercise")):
                scores["assignment"] += 0.5
    if recent_failed_tasks > 0:
        scores["assignment"] += 0.2
        scores["review_drill"] += 0.25
    if pending_approval_count > 0 or running_task_count > 0:
        scores[current_scene] += 0.2

    if features["active_tab"] == "review":
        scores["review_drill"] += 0.4
    elif features["active_tab"] == "notes":
        scores["note_organize"] += 0.3
    elif features["active_tab"] == "plan":
        scores["exam_prep"] += 0.3
    elif features["active_tab"] == "activity":
        scores[current_scene] += 0.15

    scores[current_scene] += 0.25
    return scores
