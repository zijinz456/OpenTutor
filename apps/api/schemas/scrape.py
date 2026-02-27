"""Pydantic schemas for scrape source and auth session endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, AnyHttpUrl


class ScrapeSourceCreate(BaseModel):
    url: AnyHttpUrl
    course_id: uuid.UUID
    label: str | None = None
    source_type: Literal["generic", "canvas"] = "generic"
    requires_auth: bool = False
    auth_domain: str | None = None
    session_name: str | None = None
    interval_hours: int = Field(default=24, ge=1, le=168)


class ScrapeSourceUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=168)
    requires_auth: bool | None = None
    auth_domain: str | None = None
    session_name: str | None = None


class ScrapeSourceResponse(BaseModel):
    id: uuid.UUID
    url: str
    label: str | None
    course_id: uuid.UUID
    source_type: str
    requires_auth: bool
    auth_domain: str | None
    session_name: str | None
    enabled: bool
    interval_hours: int
    last_scraped_at: datetime | None
    last_status: str | None
    last_content_hash: str | None
    consecutive_failures: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthLoginRequest(BaseModel):
    domain: str
    login_url: AnyHttpUrl
    auth_type: str = "cookie"
    actions: list[dict] = Field(min_length=1)
    # Optional validation config
    check_url: AnyHttpUrl | None = None
    success_selector: str | None = None
    failure_selector: str | None = None


class AuthSessionResponse(BaseModel):
    id: uuid.UUID
    domain: str
    session_name: str
    auth_type: str
    is_valid: bool
    last_validated_at: datetime | None

    model_config = {"from_attributes": True}
