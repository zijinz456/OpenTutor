"""Pydantic schemas for chat endpoints."""

import uuid

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single message in conversation history."""
    role: str  # "user" or "assistant"
    content: str


class ImageAttachment(BaseModel):
    """An image attached to a chat message (base64-encoded)."""
    data: str  # base64-encoded image data
    media_type: str = "image/png"  # MIME type (image/png, image/jpeg, image/webp)
    filename: str | None = None


class ChatRequest(BaseModel):
    course_id: uuid.UUID
    message: str
    conversation_id: uuid.UUID | None = None
    history: list[ChatMessage] = Field(default_factory=list)  # Recent conversation history for multi-turn context
    # v3: Tab context and scene awareness
    active_tab: str | None = None       # "notes" / "quiz" / "plan" / "review" / ...
    tab_context: dict | None = None     # Current tab content summary for context-aware responses
    scene: str | None = None            # Frontend-provided current scene (from course.active_scene)
    session_id: uuid.UUID | None = None # Chat session ID for conversation grouping
    # v3.2: Multimodal — image attachments for vision-based questions
    images: list[ImageAttachment] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Non-streaming response (for testing)."""
    response: str
    sources: list[dict] = []
