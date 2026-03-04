"""Scrape source and auth session models for periodic authenticated web scraping.

ScrapeSource: tracks URLs that should be periodically re-scraped with change detection.
AuthSession: tracks domain-level authentication sessions using Playwright storageState.

Multiple ScrapeSource records can share one AuthSession (same domain).
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Boolean, Integer, func, CheckConstraint
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ScrapeSource(Base):
    """A URL that should be periodically re-scraped."""

    __tablename__ = "scrape_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('generic', 'canvas')",
            name="ck_scrape_sources_source_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id"))

    # URL to scrape
    url: Mapped[str] = mapped_column(Text)
    label: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    # Source type label for analytics/routing metadata (runtime scraping stays generic)
    source_type: Mapped[str] = mapped_column(String(30), default="generic")

    # Authentication
    requires_auth: Mapped[bool] = mapped_column(Boolean, default=False)
    auth_domain: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    session_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Schedule
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)

    # Scrape status tracking
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Status: success | failed | auth_expired
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    # Link to most recent ingestion
    last_ingestion_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("ingestion_jobs.id"), nullable=True
    )

    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthSession(Base):
    """Tracks persistent authentication sessions for domains.

    Stores Playwright storageState reference (session_name → file on disk)
    and login_actions for automatic re-authentication.

    Credential values in login_actions use {ENV:VAR_NAME} placeholders
    that are resolved from os.environ at runtime.
    """

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))

    # Domain this session is for
    domain: Mapped[str] = mapped_column(String(200), index=True)
    session_name: Mapped[str] = mapped_column(String(100), unique=True)

    # Auth provider type
    auth_type: Mapped[str] = mapped_column(String(30), default="cookie")
    # Types: cookie | custom

    # Health
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Login flow config — same action format as automation.py (click/fill/wait/submit)
    # Sensitive values use {ENV:VAR_NAME} placeholders resolved at runtime
    login_actions: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True)
    login_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Validation config
    check_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success_selector: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    failure_selector: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
