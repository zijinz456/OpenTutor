"""Integrations router — manage OAuth2 connections to external services.

Provides endpoints to connect, disconnect, and check status of external
service integrations like Google Calendar.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.integration_credential import IntegrationCredential
from services.auth.dependency import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])


# ── Response Schemas ──


class IntegrationInfo(BaseModel):
    """Summary of a connected integration."""
    integration_name: str
    connected: bool
    connected_at: datetime | None = None
    scopes: list[str] | None = None


@router.get("", response_model=list[IntegrationInfo])
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List all connected integrations for the current user."""
    result = await db.execute(
        select(IntegrationCredential).where(IntegrationCredential.user_id == user.id)
    )
    credentials = result.scalars().all()

    return [
        IntegrationInfo(
            integration_name=cred.integration_name,
            connected=True,
            connected_at=cred.created_at,
            scopes=cred.scopes,
        )
        for cred in credentials
    ]
