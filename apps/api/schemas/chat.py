"""Pydantic schemas for chat endpoints."""

import uuid

from pydantic import BaseModel


class ChatRequest(BaseModel):
    course_id: uuid.UUID
    message: str
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    """Non-streaming response (for testing)."""
    response: str
    sources: list[dict] = []
