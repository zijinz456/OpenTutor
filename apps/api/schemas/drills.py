"""Pydantic schemas for the drills domain (Phase 16c practice-first pivot)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DrillOut(BaseModel):
    """Single drill payload — excludes ``hidden_tests`` (server-only)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    why_it_matters: str
    starter_code: str
    hints: list[str]
    skill_tags: list[str]
    source_citation: str
    time_budget_min: int
    difficulty_layer: int
    order_index: int


class DrillModuleOut(BaseModel):
    """Module metadata without embedded drills."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    order_index: int
    outcome: str | None = None
    drill_count: int


class DrillModuleTOC(DrillModuleOut):
    """Module with fully embedded drill list for TOC rendering."""

    drills: list[DrillOut]


class DrillCourseOut(BaseModel):
    """Course metadata without embedded modules."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    source: str
    version: str
    description: str | None = None
    estimated_hours: int | None = None
    module_count: int


class DrillCourseTOC(DrillCourseOut):
    """Course with fully embedded module+drill tree for TOC rendering."""

    modules: list[DrillModuleTOC]


class DrillSubmitRequest(BaseModel):
    """Submission payload — capped so a hostile client can't OOM the runner."""

    submitted_code: str = Field(max_length=20000)


class DrillSubmitResult(BaseModel):
    """Runner verdict returned after evaluating the hidden pytest suite."""

    passed: bool
    runner_output: str
    feedback: str | None = None
    duration_ms: int
    next_drill_id: str | None = None


class DrillAttemptOut(BaseModel):
    """History row for a learner's past attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    drill_id: uuid.UUID
    passed: bool
    duration_ms: int | None = None
    attempted_at: datetime
