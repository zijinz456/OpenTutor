"""Pydantic schemas for content mutation endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    snapshot_type: str
    label: str | None = None
    has_blocks: bool = False
    has_content: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class MutationResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    agent_name: str | None = None
    mutation_type: str
    reason: str | None = None
    diff_summary: str | None = None
    snapshot_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SaveBlocksRequest(BaseModel):
    blocks: list[dict[str, Any]]
    snapshot_label: str | None = None


class ContentNodeResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str | None = None
    blocks_json: list[dict[str, Any]] | None = None
    level: int
    order_index: int
    source_type: str

    model_config = {"from_attributes": True}
