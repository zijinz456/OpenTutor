"""Pydantic schemas for notification settings and push subscription endpoints."""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

# Canonical notification categories — add new values here when introducing new
# notification types so the frontend can provide matching locale keys.
NotificationCategory = Literal[
    "scrape_alert",
    "scrape_auth_expired",
    "daily_brief",
    "weekly_report",
    "review_reminder",
    "weekly_prep",
    "task_completed",
    "task_failed",
    "system",
]

ALLOWED_NOTIFICATION_CHANNELS = {"sse"}


# ---------- Notification Item Response ----------


class NotificationResponse(BaseModel):
    """Single notification item returned by the list endpoint."""

    id: str
    title: str
    body: str
    category: str
    read: bool
    course_id: str | None = None
    action_url: str | None = None
    action_label: str | None = None
    data: dict | None = None
    created_at: str | None = None


class NotificationsListResponse(BaseModel):
    """Envelope for paginated notification list."""

    unread_count: int
    notifications: list[NotificationResponse]


# ---------- Notification Settings ----------


class NotificationSettingsResponse(BaseModel):
    """Full notification settings for a user."""

    id: uuid.UUID
    user_id: uuid.UUID
    channels_enabled: list[str]
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    timezone: str
    max_notifications_per_hour: int
    max_notifications_per_day: int
    preferred_study_time: str | None
    study_time_confidence: float
    escalation_enabled: bool
    escalation_delay_hours: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationSettingsUpdate(BaseModel):
    """Partial update for notification settings — all fields optional."""

    channels_enabled: list[str] | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None
    max_notifications_per_hour: int | None = Field(None, ge=1, le=100)
    max_notifications_per_day: int | None = Field(None, ge=1, le=500)
    escalation_enabled: bool | None = None
    escalation_delay_hours: int | None = Field(None, ge=1, le=48)
    _TIME_FIELDS: ClassVar[set[str]] = {"quiet_hours_start", "quiet_hours_end"}

    @field_validator("channels_enabled")
    @classmethod
    def validate_channels_enabled(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        normalized = [channel.strip() for channel in value if channel.strip()]
        invalid = sorted({channel for channel in normalized if channel not in ALLOWED_NOTIFICATION_CHANNELS})
        if invalid:
            raise ValueError(
                "Unsupported notification channels: "
                + ", ".join(invalid)
            )
        return normalized

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time_fields(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        datetime.strptime(value, "%H:%M")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        import zoneinfo

        zoneinfo.ZoneInfo(value)
        return value


# ---------- Push Subscription ----------


class PushSubscriptionCreate(BaseModel):
    """Register a Web Push subscription."""

    endpoint: str = Field(..., max_length=2048)
    p256dh_key: str = Field(..., max_length=512)
    auth_key: str = Field(..., max_length=512)
    user_agent: str | None = Field(default=None, max_length=512)


class PushSubscriptionDelete(BaseModel):
    """Remove a Web Push subscription by endpoint."""

    endpoint: str = Field(..., max_length=2048)
