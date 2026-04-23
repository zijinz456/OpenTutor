"""Pydantic schemas for Phase 7 Guardrails strict-grounding mode.

Shapes the structured output an LLM must produce when
``settings.guardrails_strict`` (or a per-session override) is active, plus
the metadata blob persisted into ``chat_message_logs.metadata_json`` under
the ``guardrails`` key for later eval / UI rendering.

Citation indices are 1-based offsets into the numbered retrieval context
block (critic concern #3 — opaque chunk UUIDs would make the self-check
unfalsifiable).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GuardrailsOutput(BaseModel):
    """Structured LLM output under GUARDRAILS_STRICT mode."""

    answer: str
    confidence: int = Field(ge=1, le=5)
    citations: list[int] = Field(default_factory=list)
    # 1-based indices into ctx.content_docs (critic concern #3)


class GuardrailsMetadata(BaseModel):
    """Written into ``chat_message_logs.metadata_json['guardrails']``."""

    answer: str | None = None
    confidence: int | None = None
    citations: list[int] = Field(default_factory=list)
    citation_chunks: list[dict] = Field(default_factory=list)
    # denormalized {id, source_file, snippet}[] for UI rendering
    refusal_reason: str | None = None
    # "no_retrieval" | "parse_fallback" | null
    top_retrieval_score: float | None = None
    strict_mode: bool = False
