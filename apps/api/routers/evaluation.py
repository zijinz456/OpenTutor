"""Evaluation endpoints: run eval suites for routing, retrieval, and response quality."""

import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class EvalResponseRequest(BaseModel):
    cases: list[dict]  # [{"question": str, "response": str, "context": str}]


class EvalRetrievalRequest(BaseModel):
    course_id: uuid.UUID
    queries_with_keywords: list[dict]  # [{"query": str, "keywords": ["a","b"]}]
    k: int = 5


class RegressionBenchmarkRequest(BaseModel):
    course_id: uuid.UUID | None = None
    retrieval_queries: list[dict] | None = None
    response_cases: list[dict] | None = None


@router.post("/routing")
async def run_routing_eval(
    user: User = Depends(get_current_user),
):
    """Run intent routing evaluation against golden test set."""
    from services.evaluation.eval_routing import eval_routing
    result = await eval_routing()
    return {
        "accuracy": result.accuracy,
        "total": result.total,
        "correct": result.correct,
        "mismatches": result.mismatches,
    }


@router.post("/response")
async def run_response_eval(
    body: EvalResponseRequest,
    user: User = Depends(get_current_user),
):
    """Run LLM-as-judge response quality evaluation."""
    from services.evaluation.eval_response import (
        ResponseEvalCase, eval_responses_batch,
    )

    cases = [
        ResponseEvalCase(
            question=c.get("question", ""),
            response=c.get("response", ""),
            context=c.get("context", ""),
        )
        for c in body.cases
        if c.get("question") and c.get("response")
    ]
    if not cases:
        return {"error": "No valid cases provided"}

    result = await eval_responses_batch(cases)
    return {
        "total": result.total,
        "avg_correctness": round(result.avg_correctness, 2),
        "avg_relevance": round(result.avg_relevance, 2),
        "avg_helpfulness": round(result.avg_helpfulness, 2),
        "scores": [
            {
                "correctness": s.correctness,
                "relevance": s.relevance,
                "helpfulness": s.helpfulness,
                "rationale": s.rationale,
            }
            for s in result.scores
        ],
    }


@router.post("/retrieval")
async def run_retrieval_eval(
    body: EvalRetrievalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run RAG retrieval quality evaluation."""
    from services.evaluation.eval_retrieval import eval_retrieval_from_course

    result = await eval_retrieval_from_course(
        db, body.course_id, body.queries_with_keywords, k=body.k,
    )
    return {
        "total": result.total,
        "avg_recall": round(result.avg_recall, 3),
        "avg_precision": round(result.avg_precision, 3),
        "mrr": round(result.mrr, 3),
        "avg_ndcg": round(result.avg_ndcg, 3),
        "per_query": [
            {
                "query": s.query,
                "recall": round(s.recall_at_k, 3),
                "precision": round(s.precision_at_k, 3),
                "rr": round(s.reciprocal_rank, 3),
                "ndcg": round(s.ndcg_at_k, 3),
                "relevant_found": s.relevant_found,
                "retrieved": s.retrieved_ids,
            }
            for s in result.per_query
        ],
    }


@router.post("/regression")
async def run_regression_eval(
    body: RegressionBenchmarkRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the bundled regression benchmark suite."""
    _ = user
    from services.evaluation.benchmark_runner import run_regression_benchmark

    return await run_regression_benchmark(
        db=db if body.course_id and body.retrieval_queries else None,
        course_id=body.course_id,
        retrieval_queries=body.retrieval_queries,
        response_cases=body.response_cases,
    )
