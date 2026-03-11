"""Pydantic schemas for chat endpoints."""

import json
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Canonical learning modes — keep in sync with frontend lib/block-system/types.ts
LearningMode = Literal["course_following", "self_paced", "exam_prep", "maintenance"]


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
    message: str = Field(..., max_length=10000)
    conversation_id: uuid.UUID | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=100)  # Recent conversation history for multi-turn context
    # v3: Tab context and scene awareness
    active_tab: str | None = None       # "notes" / "quiz" / "plan" / "review" / ...
    tab_context: dict | None = Field(default=None, max_length=50)  # Current tab content summary (max 50 keys to prevent DoS)
    scene: str | None = None            # Frontend-provided current scene (from course.active_scene)
    session_id: uuid.UUID | None = None # Chat session ID for conversation grouping
    # v3.2: Multimodal — image attachments for vision-based questions
    images: list[ImageAttachment] = Field(default_factory=list, max_length=10)
    # v3.2: User interrupt/steering — indicates the user interrupted a previous streaming response
    interrupt: bool = False
    # v3.3: Learning mode from frontend
    learning_mode: LearningMode | None = None
    # v4: Block system context — current blocks and recently dismissed types
    block_types: list[str] = Field(default_factory=list)
    dismissed_block_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_tab_context_size(self):
        """Prevent DoS via oversized tab_context payloads (max 50 KB serialized)."""
        if self.tab_context is not None:
            serialized = json.dumps(self.tab_context, default=str)
            if len(serialized) > 51_200:  # 50 KB
                raise ValueError("tab_context exceeds maximum allowed size (50 KB)")
        return self


class ChatResponse(BaseModel):
    """Non-streaming response (for testing)."""
    response: str
    sources: list[dict] = []
