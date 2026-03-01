"""Pydantic schemas for channel binding API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChannelBindingCreate(BaseModel):
    """Request body for binding a messaging channel to a user account."""

    channel_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Channel platform identifier (e.g. 'whatsapp', 'imessage').",
        examples=["whatsapp", "imessage"],
    )
    channel_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="User's identifier on the channel (phone number, handle, etc.).",
        examples=["+15551234567"],
    )


class ChannelBindingResponse(BaseModel):
    """Response schema for a single channel binding."""

    id: uuid.UUID
    user_id: uuid.UUID
    channel_type: str
    channel_id: str
    display_name: str | None = None
    is_verified: bool = False
    active_course_id: uuid.UUID | None = None
    created_at: datetime
    last_message_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChannelBindingList(BaseModel):
    """Response schema for listing a user's channel bindings."""

    bindings: list[ChannelBindingResponse]
