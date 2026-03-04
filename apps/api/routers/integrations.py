"""Integrations router — manage OAuth2 connections to external services.

Provides endpoints to connect, disconnect, and check status of external
service integrations like Google Calendar.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
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


class OAuthURLResponse(BaseModel):
    """Response containing the OAuth authorization URL."""
    url: str


class ConnectionStatusResponse(BaseModel):
    """Detailed status of an integration connection."""
    connected: bool
    integration_name: str = "google_calendar"
    scopes: list[str] | None = None
    token_expires_at: datetime | None = None
    connected_at: datetime | None = None


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# ── List Connected Integrations ──


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


# ── Google Calendar: Generate OAuth URL ──


@router.get("/google-calendar/auth", response_model=OAuthURLResponse)
async def google_calendar_auth(
    user=Depends(get_current_user),
):
    """Generate a Google OAuth2 authorization URL.

    Returns a JSON response with the URL the client should open in a browser
    to begin the OAuth flow. Does NOT redirect.
    """
    try:
        from services.integrations.google_calendar import build_oauth_state, get_oauth_url

        url = get_oauth_url(state=build_oauth_state(user.id))
        return OAuthURLResponse(url=url)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to generate Google OAuth URL: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate OAuth URL. Check server configuration.",
        )


# ── Google Calendar: OAuth Callback ──


@router.get("/google-calendar/callback", response_model=MessageResponse)
async def google_calendar_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="Signed OAuth state from the auth request"),
    db: AsyncSession = Depends(get_db),
):
    """Exchange the Google OAuth2 authorization code for tokens.

    Stores the resulting access and refresh tokens in the database
    as an IntegrationCredential for the current user.
    """
    try:
        from services.integrations.google_calendar import consume_oauth_state, exchange_code

        user_id = consume_oauth_state(state)
        tokens = await exchange_code(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Google Calendar token exchange failed: %s", exc)
        raise HTTPException(status_code=500, detail="Token exchange failed. Please try again.")

    # Upsert: update existing or create new credential
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == user_id,
            IntegrationCredential.integration_name == "google_calendar",
        )
    )
    credential = result.scalar_one_or_none()

    if credential:
        credential.access_token = tokens["access_token"]
        credential.refresh_token = tokens.get("refresh_token") or credential.refresh_token
        credential.token_expires_at = tokens.get("expires_at")
        credential.scopes = tokens.get("scopes")
        credential.updated_at = datetime.now(timezone.utc)
    else:
        credential = IntegrationCredential(
            user_id=user_id,
            integration_name="google_calendar",
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            token_expires_at=tokens.get("expires_at"),
            scopes=tokens.get("scopes"),
        )
        db.add(credential)

    await db.commit()
    logger.info("Google Calendar connected for user %s", user_id)
    return MessageResponse(message="Google Calendar connected successfully.")


# ── Google Calendar: Disconnect ──


@router.delete("/google-calendar", response_model=MessageResponse)
async def google_calendar_disconnect(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Disconnect Google Calendar by deleting stored credentials."""
    result = await db.execute(
        delete(IntegrationCredential).where(
            IntegrationCredential.user_id == user.id,
            IntegrationCredential.integration_name == "google_calendar",
        )
    )
    await db.commit()

    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status_code=404, detail="Google Calendar integration not found.")

    logger.info("Google Calendar disconnected for user %s", user.id)
    return MessageResponse(message="Google Calendar disconnected.")


# ── Google Calendar: Connection Status ──


@router.get("/google-calendar/status", response_model=ConnectionStatusResponse)
async def google_calendar_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Check whether Google Calendar is connected for the current user."""
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == user.id,
            IntegrationCredential.integration_name == "google_calendar",
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        return ConnectionStatusResponse(connected=False)

    return ConnectionStatusResponse(
        connected=True,
        scopes=credential.scopes,
        token_expires_at=credential.token_expires_at,
        connected_at=credential.created_at,
    )
