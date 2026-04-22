"""In-memory TTL cache for tutor-turn flashcard candidates (§14.5 v2.1 T5).

Part of the non-blocking card delivery pipeline:

1. After the tutor's final ``replace`` event is streamed to the client, the
   orchestrator launches ``extract_card_candidates`` as a background task
   via :func:`services.agent.background_runtime.track_background_task`.
2. The orchestrator also yields a synthetic SSE ``pending_cards`` event
   carrying a freshly-minted ``message_id`` so the frontend knows "cards
   MIGHT arrive for this message — poll in a few seconds."
3. The background task, on completion, calls :func:`put` with the extracted
   cards.
4. The frontend hits ``GET /api/courses/sessions/{sid}/messages/{mid}/card-candidates``
   which calls :func:`await_or_get` — it waits up to ``timeout_s`` for
   :func:`put` to fire, or returns immediately if the entry is already
   cached, or returns ``None`` on miss+timeout.

Design notes
------------
* **Single-loop asyncio, no locks.** The cache is mutated only from
  coroutines running on the same event loop. ``dict`` and ``TTLCache``
  operations we perform (``__setitem__``, ``__getitem__``, ``pop``,
  ``setdefault``) are synchronous and uninterruptible from the perspective
  of the coroutine that calls them — no ``await`` between check-and-mutate.
  That gives us trivial atomicity without ``asyncio.Lock``. If we ever go
  multi-worker (Gunicorn forks, not threads), each worker gets its own
  cache — the price of the design is that a poll must hit the same worker
  that ran the chat turn. FastAPI default single-worker dev mode fine;
  production multi-worker would need Redis. Out of scope for v2.1.

* **Two stores kept in sync.** One TTLCache for the card payload itself,
  one parallel ``dict`` for the ``asyncio.Event`` objects that let pollers
  block instead of busy-looping. The Event dict has no TTL of its own —
  when the payload TTL expires the matching Event is orphaned until the
  next ``put`` or ``await_or_get`` call for that key prunes it. In
  practice, orphaned Events are tiny (``asyncio.Event`` ≈ ~100 bytes) and
  key churn is bounded by ``cachetools.TTLCache(maxsize=200)`` so the
  memory footprint stays tiny even if we never pruned. We do prune
  anyway, on every access path, to keep shape sane.

* **Cache sizing.** ``maxsize=200`` * ``ttl=300s`` = 5-minute window for
  200 concurrent messages. A single user sending a chat turn every 2-3s
  over 5 minutes hits at most ~150 entries. Plenty of headroom. Worst-
  case memory ≈ 200 × (3 cards × 700 bytes each) ≈ 420 KB. Negligible.

* **Never raises.** ``put`` and ``await_or_get`` are explicit about their
  failure modes: ``put`` always succeeds (overwrite-on-dupe), and
  ``await_or_get`` returns ``None`` on timeout / unknown key.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from cachetools import TTLCache

if TYPE_CHECKING:
    from schemas.curriculum import CardCandidate

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────

# Max number of concurrently-cached (session_id, message_id) entries.
# 200 covers even chatty multi-user dev; single-user personal deployment
# will rarely exceed 20.
_CACHE_MAXSIZE: int = 200

# TTL in seconds. 5 minutes covers a comfortable polling window — the
# frontend polls within 1-10s of receiving ``pending_cards``, and we keep
# the entry around long enough that a page reload within the same minute
# can still grab the cards (future UX nicety).
_CACHE_TTL_SEC: float = 300.0

# Default wait timeout for ``await_or_get``. The spec calls for ≤10s on
# the endpoint; we default to it here so callers can omit the arg. The
# LLM-side budget inside ``extract_card_candidates`` is 8s, so a 10s
# frontend-side wait is a 2s safety margin for the scheduler to hand back
# control after the task completes.
_DEFAULT_TIMEOUT_SEC: float = 10.0


# ── State ───────────────────────────────────────────────────

# Payload cache. Key = (session_id, message_id) tuple of UUIDs.
# Value = ``list[CardCandidate]``. Empty list is a legitimate value — it
# means "we tried and the LLM returned zero cards", distinct from "we
# never ran" (key absent).
_cache: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SEC)

# Event registry. Same key as ``_cache``. Present whenever at least one
# of {producer called ``put``, consumer called ``await_or_get``} has run.
# ``put`` sets the event; ``await_or_get`` awaits it. If a key arrives
# ``await_or_get``-first, we create the event eagerly so a later ``put``
# can signal it.
_events: dict[tuple[uuid.UUID, uuid.UUID], asyncio.Event] = {}


# ── Helpers ─────────────────────────────────────────────────


def _key(session_id: uuid.UUID, message_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (session_id, message_id)


def _get_or_create_event(key: tuple[uuid.UUID, uuid.UUID]) -> asyncio.Event:
    """Look up the event for ``key`` or lazily create one.

    Safe under single-loop asyncio — both ``dict.get`` and ``dict[...] =``
    are synchronous and run without yielding.
    """

    event = _events.get(key)
    if event is None:
        event = asyncio.Event()
        _events[key] = event
    return event


def _prune_event_if_payload_evicted(key: tuple[uuid.UUID, uuid.UUID]) -> None:
    """Drop the event record if the payload has TTL-expired.

    We can't hook into ``TTLCache`` eviction callbacks cleanly, so we
    lazily prune on every access. Side effect: an event that was created
    eagerly by a consumer but never signalled still gets pruned once its
    matching payload (if any) expires.
    """

    if key not in _cache and key in _events:
        # Payload no longer in TTLCache → the entry is dead. Drop the
        # event so a later ``put`` for the same key re-creates a fresh
        # unsignalled one.
        _events.pop(key, None)


# ── Public API ──────────────────────────────────────────────


def put(
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    cards: list["CardCandidate"],
) -> None:
    """Store ``cards`` under ``(session_id, message_id)`` and wake waiters.

    Overwrite-safe: a repeated ``put`` on the same key replaces the value
    and re-signals the event. In the orchestrator hookflow this shouldn't
    happen (message_id is a fresh UUID per turn) but the semantics are
    defined anyway so retry scenarios don't surprise.

    Args:
        session_id: Chat session UUID (``ctx.session_id``).
        message_id: Fresh UUID minted by the orchestrator for this turn.
        cards: List of 0-3 validated ``CardCandidate`` instances. Empty
            list is a legitimate value — callers (the endpoint) should
            still return it; the frontend decides whether to render a
            toast or drop silently.
    """

    key = _key(session_id, message_id)
    _cache[key] = list(cards)  # copy to decouple from caller's mutation
    event = _get_or_create_event(key)
    event.set()
    logger.debug(
        "card_cache.put: session=%s message=%s cards=%d",
        session_id,
        message_id,
        len(cards),
    )


async def await_or_get(
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    timeout_s: float = _DEFAULT_TIMEOUT_SEC,
) -> list["CardCandidate"] | None:
    """Return cached cards, waiting up to ``timeout_s`` if not yet ready.

    Three branches:
    1. Payload already cached → return it immediately (no wait).
    2. Event registered but not yet set → ``await event.wait()`` bounded
       by ``timeout_s``. On success, return the now-cached payload.
    3. Nothing registered at all → create an event eagerly and wait. The
       eager creation lets a racing ``put`` (which might arrive
       milliseconds after we checked the cache) still signal us.

    Returns:
        ``list[CardCandidate]`` (possibly empty) on hit within timeout,
        or ``None`` on timeout+miss.
    """

    key = _key(session_id, message_id)

    _prune_event_if_payload_evicted(key)

    # Fast path — payload already available.
    cached = _cache.get(key)
    if cached is not None:
        logger.debug(
            "card_cache.await_or_get: fast hit for session=%s message=%s (%d cards)",
            session_id,
            message_id,
            len(cached),
        )
        return list(cached)

    # Slow path — wait for a producer. We MUST create the event before
    # re-checking the cache, otherwise a ``put`` that lands between our
    # initial miss and our ``event.wait()`` call would be silently
    # dropped by this consumer.
    event = _get_or_create_event(key)

    # Re-check the cache now that the event exists. A ``put`` that
    # happened between the first check and now would have both populated
    # the cache and set the event — either way we get its result.
    cached = _cache.get(key)
    if cached is not None:
        return list(cached)

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.debug(
            "card_cache.await_or_get: timeout (%.1fs) for session=%s message=%s",
            timeout_s,
            session_id,
            message_id,
        )
        return None

    # Event fired — payload should be present.
    cached = _cache.get(key)
    if cached is None:
        # Rare: payload TTL-expired between event.set() and our re-read.
        # Treat as miss. In practice this requires TTL ≤ scheduling
        # latency, which doesn't happen with 300s TTL.
        logger.warning(
            "card_cache: event fired but payload missing for session=%s message=%s",
            session_id,
            message_id,
        )
        return None
    return list(cached)


def clear() -> None:
    """Drop all cached entries and events. Exposed for tests."""
    _cache.clear()
    _events.clear()


__all__ = ["put", "await_or_get", "clear"]
