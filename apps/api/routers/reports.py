"""Report endpoints — list, retrieve, and on-demand generate learning reports."""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.exceptions import NotFoundError, ValidationError
from models.report import Report
from models.user import User
from services.auth.dependency import get_current_user
from utils.serializers import serialize_model

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_REPORT_TYPES = {"daily_brief", "weekly_report"}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ReportOut(BaseModel):
    id: str
    user_id: str
    course_id: str | None = None
    report_type: str
    period_start: str
    period_end: str
    content: str
    data_snapshot: dict | None = None
    created_at: str


class GenerateRequest(BaseModel):
    report_type: str  # "daily_brief" | "weekly_report"
    course_id: str | None = None
    days: int | None = None


class GenerateResponse(BaseModel):
    id: str
    report_type: str
    content: str
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPORT_FIELDS = [
    "id", "user_id", "course_id", "report_type", "period_start",
    "period_end", "content", "data_snapshot", "created_at",
]


def _serialize_report(report: Report) -> dict:
    return serialize_model(report, REPORT_FIELDS)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/latest", response_model=ReportOut)
async def get_latest_report(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    report_type: str | None = Query(None),
):
    """Get the most recent report, optionally filtered by type."""
    query = select(Report).where(Report.user_id == user.id)
    if report_type is not None:
        if report_type not in VALID_REPORT_TYPES:
            raise ValidationError(f"Invalid report_type: {report_type}")
        query = query.where(Report.report_type == report_type)
    query = query.order_by(Report.created_at.desc()).limit(1)

    result = await db.execute(query)
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report")
    return ReportOut(**_serialize_report(report))


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single report by ID."""
    result = await db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.user_id == user.id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report", report_id)
    return ReportOut(**_serialize_report(report))


@router.get("/", response_model=list[ReportOut])
async def list_reports(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    report_type: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List reports with pagination, optionally filtered by report_type."""
    query = select(Report).where(Report.user_id == user.id)
    if report_type is not None:
        if report_type not in VALID_REPORT_TYPES:
            raise ValidationError(f"Invalid report_type: {report_type}")
        query = query.where(Report.report_type == report_type)
    query = query.order_by(Report.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()
    return [ReportOut(**_serialize_report(r)) for r in rows]


@router.post("/generate", response_model=GenerateResponse)
async def generate_report(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """On-demand report generation.

    Calls the generator which persists the report automatically, then
    returns the most recently created report row for this user+type.
    """
    if body.report_type not in VALID_REPORT_TYPES:
        raise ValidationError(f"Invalid report_type: {body.report_type}")

    from services.report.generator import generate_daily_brief, generate_weekly_report
    parsed_course_id = None
    if body.course_id:
        try:
            parsed_course_id = uuid.UUID(body.course_id)
        except ValueError as exc:
            raise ValidationError("Invalid course_id") from exc

    default_days = 1 if body.report_type == "daily_brief" else 7
    report_days = body.days or default_days
    if report_days <= 0:
        raise ValidationError("days must be greater than 0")

    if body.report_type == "daily_brief":
        content = await generate_daily_brief(
            user.id,
            db,
            course_id=parsed_course_id,
            days=report_days,
            raise_on_persist_failure=True,
        )
    else:
        content = await generate_weekly_report(
            user.id,
            db,
            course_id=parsed_course_id,
            days=report_days,
            raise_on_persist_failure=True,
        )

    # The generator already persists the report; fetch the latest row.
    query = select(Report).where(
        Report.user_id == user.id,
        Report.report_type == body.report_type,
    )
    if parsed_course_id:
        query = query.where(Report.course_id == parsed_course_id)
    else:
        query = query.where(Report.course_id.is_(None))
    result = await db.execute(query.order_by(Report.created_at.desc()).limit(1))
    report = result.scalar_one_or_none()

    if report:
        return GenerateResponse(
            id=str(report.id),
            report_type=report.report_type,
            content=report.content,
            created_at=report.created_at.isoformat(),
        )

    raise ValidationError("Report generation succeeded but persistence failed")
