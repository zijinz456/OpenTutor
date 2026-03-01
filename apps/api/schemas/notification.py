"""Pydantic schemas for notification settings and push subscription endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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


# ---------- Push Subscription ----------


class PushSubscriptionCreate(BaseModel):
    """Register a Web Push subscription."""

    endpoint: str
    p256dh_key: str
    auth_key: str
    user_agent: str | None = None


class PushSubscriptionDelete(BaseModel):
    """Remove a Web Push subscription by endpoint."""

    endpoint: str
