"""Evaluation API endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.evaluation.benchmark_runner import run_regression_benchmark

router = APIRouter(tags=["internal"])


class RetrievalQueryPayload(BaseModel):
    query: str
    keywords: list[str] = Field(default_factory=list)


class RegressionBenchmarkRequest(BaseModel):
    course_id: uuid.UUID | None = None
    retrieval_queries: list[RetrievalQueryPayload] | None = None
    response_cases: list[dict] | None = None
    strict: bool = False


@router.post("/regression")
async def regression_benchmark(
    body: RegressionBenchmarkRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run bundled routing/retrieval/response/recovery regression suites."""
    if body.course_id:
        await get_course_or_404(db, body.course_id, user_id=user.id)

    retrieval_queries = (
        [item.model_dump() for item in body.retrieval_queries]
        if body.retrieval_queries
        else None
    )
    return await run_regression_benchmark(
        db=db,
        course_id=body.course_id,
        retrieval_queries=retrieval_queries,
        response_cases=body.response_cases,
        strict=body.strict,
    )
