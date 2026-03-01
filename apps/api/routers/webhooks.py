"""Webhook endpoints for multi-channel messaging (WhatsApp, iMessage).

These endpoints receive inbound messages from external messaging platforms,
verify their authenticity, parse the payload, and dispatch the message
through the agent pipeline in a background task so we can return 200
immediately (required by most messaging platform webhook contracts).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, Request, Response

from config import settings
from database import async_session

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WhatsApp Cloud API
# ---------------------------------------------------------------------------

@router.get("/whatsapp")
async def whatsapp_verify(
    request: Request,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> Response:
    """WhatsApp webhook verification challenge (GET).

    When you register a webhook URL with Meta, they send a GET request
    with ``hub.mode=subscribe``, ``hub.verify_token=<your_token>``, and
    ``hub.challenge=<random_string>``.  We must echo back the challenge
    if the verify token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verification succeeded")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed (bad token or mode)")
    return Response(content="Verification failed", status_code=403)


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    """Receive incoming WhatsApp messages (POST).

    1. Read raw body and verify HMAC-SHA256 signature.
    2. Parse the webhook payload into an IncomingMessage.
    3. Dispatch processing in a background task.
    4. Return 200 immediately (WhatsApp requires fast acknowledgement).
    """
    from services.channels.whatsapp import WhatsAppAdapter
    from services.channels.dispatcher import dispatch_message

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    adapter = WhatsAppAdapter()

    # Verify HMAC signature
    if not await adapter.verify_webhook(body, headers):
        logger.warning("WhatsApp webhook signature verification failed")
        # Still return 200 to avoid Meta retrying endlessly,
        # but do not process the message.
        return Response(status_code=200)

    # Parse the JSON payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("WhatsApp webhook: invalid JSON body")
        return Response(status_code=200)

    # Parse into an IncomingMessage (may be None for status updates)
    incoming = await adapter.parse_webhook(payload, headers)
    if incoming is None:
        # Not a user message (delivery receipt, status update, etc.)
        return Response(status_code=200)

    # Dispatch in background so we can ACK the webhook immediately
    asyncio.create_task(
        _dispatch_with_session(adapter, incoming),
        name=f"whatsapp-dispatch-{incoming.message_id}",
    )

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# iMessage via BlueBubbles
# ---------------------------------------------------------------------------

@router.post("/imessage")
async def imessage_webhook(request: Request) -> Response:
    """Receive incoming iMessage via BlueBubbles webhook (POST).

    1. Verify the shared secret header.
    2. Parse the BlueBubbles webhook payload.
    3. Dispatch processing in a background task.
    4. Return 200 immediately.
    """
    from services.channels.imessage import IMessageAdapter
    from services.channels.dispatcher import dispatch_message

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    adapter = IMessageAdapter()

    # Verify shared secret
    if not await adapter.verify_webhook(body, headers):
        logger.warning("iMessage webhook secret verification failed")
        return Response(status_code=401)

    # Parse the JSON payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("iMessage webhook: invalid JSON body")
        return Response(status_code=200)

    # Parse into an IncomingMessage
    incoming = await adapter.parse_webhook(payload, headers)
    if incoming is None:
        return Response(status_code=200)

    # Dispatch in background
    asyncio.create_task(
        _dispatch_with_session(adapter, incoming),
        name=f"imessage-dispatch-{incoming.message_id}",
    )

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _dispatch_with_session(adapter, incoming) -> None:
    """Run dispatch_message inside a fresh database session.

    Background tasks don't have access to the request-scoped DB session,
    so we create a new one from the session factory.
    """
    from services.channels.dispatcher import dispatch_message

    try:
        async with async_session() as db:
            await dispatch_message(
                adapter=adapter,
                incoming=incoming,
                db=db,
                db_factory=async_session,
            )
    except Exception as exc:
        logger.error(
            "Background dispatch failed for %s/%s: %s",
            incoming.channel_type,
            incoming.channel_id,
            exc,
            exc_info=True,
        )
