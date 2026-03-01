"""Policy-based scene selection and switch recommendation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.course import Course
from models.ingestion import Assignment, WrongAnswer
from models.progress import LearningProgress
from services.agent.state import SceneName

SCENES = tuple(s.value for s in SceneName)

SCENE_CUE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "exam_prep": [
        re.compile(r"(exam|final|midterm|quiz prep|考试|期末|期中|考前|冲刺|复习)", re.IGNORECASE),
    ],
    "assignment": [
        re.compile(r"(assignment|homework|problem set|作业|练习册|题目)", re.IGNORECASE),
    ],
    "review_drill": [
        re.compile(r"(wrong answer|mistake|error analysis|错题|纠错|薄弱点|weak area)", re.IGNORECASE),
    ],
    "note_organize": [
        re.compile(r"(organize notes|summary|outline|mind map|整理笔记|总结|归纳|笔记)", re.IGNORECASE),
    ],
    "study_session": [
        re.compile(r"(explain|teach|what is|how does|学习|理解|概念|解释)", re.IGNORECASE),
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

    reasons = []
    if features["matched_cues"].get(best_scene):
        reasons.append(
            f"message cues matched {', '.join(repr(cue) for cue in features['matched_cues'][best_scene][:3])}"
        )
    if best_scene == "review_drill" and features["unmastered_wrong_answers"] > 0:
        reasons.append(f"{features['unmastered_wrong_answers']} unmastered wrong answers")
    if best_scene == "assignment" and features["upcoming_assignments"] > 0:
        reasons.append(f"{features['upcoming_assignments']} active assignments")
    if best_scene == "exam_prep" and features["low_mastery_count"] > 0:
        reasons.append(f"{features['low_mastery_count']} low-mastery concepts")
    if best_scene == "note_organize" and features["content_nodes"] > 10:
        reasons.append(f"{features['content_nodes']} course content nodes available for synthesis")
    if not reasons:
        reasons.append("defaulted to the highest-scoring study policy")

    return ScenePolicyDecision(
        scene_id=best_scene,
        scores=scores,
        confidence=confidence,
        reason=f"Selected {best_scene} because " + ", ".join(reasons) + ".",
        features=features,
        switch_recommended=switch_recommended,
    )


async def _collect_scene_features(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    active_tab: str,
) -> dict:
    message = message or ""

    assignment_result = await db.execute(
        select(func.count(Assignment.id))
        .where(Assignment.course_id == course_id, Assignment.status == "active")
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

    matched_cues = {
        scene: [
            match.group(0)
            for pattern in patterns
            for match in [pattern.search(message)]
            if match
        ]
        for scene, patterns in SCENE_CUE_PATTERNS.items()
    }

    return {
        "matched_cues": matched_cues,
        "upcoming_assignments": int(assignment_result.scalar() or 0),
        "unmastered_wrong_answers": int(wrong_answer_result.scalar() or 0),
        "low_mastery_count": int(low_mastery_result.scalar() or 0),
        "content_nodes": int(content_result.scalar() or 0),
        "active_tab": active_tab,
        "course_active_scene": course.active_scene if course else "study_session",
    }


def _score_scenes(*, features: dict, current_scene: str) -> dict[str, float]:
    scores = {scene: 0.2 for scene in SCENES}

    for scene, cues in features["matched_cues"].items():
        scores[scene] += min(len(cues), 2) * 1.4

    if features["upcoming_assignments"] > 0:
        scores["assignment"] += 0.7
        scores["exam_prep"] += 0.4
    if features["unmastered_wrong_answers"] > 0:
        scores["review_drill"] += min(features["unmastered_wrong_answers"], 5) * 0.25
    if features["low_mastery_count"] > 0:
        scores["exam_prep"] += min(features["low_mastery_count"], 5) * 0.2
        scores["review_drill"] += min(features["low_mastery_count"], 5) * 0.1
    if features["content_nodes"] >= 8:
        scores["note_organize"] += 0.5
        scores["study_session"] += 0.3

    if features["active_tab"] == "review":
        scores["review_drill"] += 0.4
    elif features["active_tab"] == "notes":
        scores["note_organize"] += 0.3
    elif features["active_tab"] == "plan":
        scores["exam_prep"] += 0.3

    scores[current_scene] += 0.25
    return scores
