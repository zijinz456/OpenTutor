"""Pydantic schemas for the Coursera ZIP ingest adapter (Phase 14)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LecturePair(BaseModel):
    """One lecture worth of Coursera assets (VTT transcript and/or PDF slides)."""

    week_index: int = Field(..., ge=1, description="1-based week ordinal")
    lecture_index: int = Field(
        ..., ge=1, description="1-based lecture ordinal within week"
    )
    title: str = Field(..., min_length=1)
    vtt_path: str | None = None
    pdf_path: str | None = None
    vtt_bytes: bytes | None = None
    pdf_bytes: bytes | None = None


class CourseraUploadResponse(BaseModel):
    """Response body for ``POST /upload/coursera``."""

    course_id: str
    lectures_total: int = Field(..., ge=0)
    lectures_paired: int = Field(..., ge=0)
    lectures_vtt_only: int = Field(..., ge=0)
    lectures_pdf_only: int = Field(..., ge=0)
    job_ids: list[str] = Field(
        default_factory=list,
        description="IngestionJob UUIDs — empty on already_imported",
    )
    status: Literal["created", "already_imported"]
