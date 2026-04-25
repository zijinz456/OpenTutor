"""Process-local job store for standard-room generation — Phase 16b A.

This product is single-user local-first (see plan), so a per-process
in-memory store is good enough for the SSE stream. No DB writes here.

Responsibilities
----------------
* ``create_job`` mints a job record and stores it.
* ``update_status`` / ``append_event`` mutate the record AND fan out to
  any active subscribers (SSE consumer side).
* ``subscribe`` returns an async iterator that yields events as they
  land — backed by ``asyncio.Queue`` so the router can use a simple
  ``async for ... yield`` pattern.
* TTL cleanup: jobs are evicted after ``JOB_TTL`` to avoid unbounded
  memory growth across long-running processes.

Why an in-memory store and not a DB row?
* Spec Part D.2 explicitly allows it for this slice.
* Status churn is high-frequency (queued → outline → tasks → persisting
  → completed) and writing each transition to Postgres just to feed an
  SSE channel that no one will replay later is wasteful.
* The actual durable artefact (the ``PathRoom``) is what gets persisted
  by ``path_room_factory.generate_and_persist_room``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Literal, Optional

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────

# How long a finished/aged job stays accessible before garbage-collection.
# Spec Part D.11: TTL is fine; the stream must remain stable for a test
# lifetime, which is well under an hour.
JOB_TTL: timedelta = timedelta(hours=1)

# Sentinel sent on the per-subscriber queue to terminate ``subscribe``
# once the job reaches a terminal state.
_TERMINAL_SENTINEL: dict[str, Any] = {"__terminal__": True}


# ── Types ────────────────────────────────────────────────────────────


JobStatus = Literal[
    "queued",
    "outline",
    "tasks",
    "persisting",
    "completed",
    "error",
]

_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "error"})


@dataclass
class JobRecord:
    """Single generation job's state.

    Mutated in place by ``update_status`` / ``append_event``. Treat it
    as read-only outside the store; never mutate fields directly from
    callers.
    """

    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    request_summary: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)
    room_id: Optional[uuid.UUID] = None
    path_id: Optional[uuid.UUID] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    # Subscribers are kept inside the record so a single reader can
    # detach without affecting others. Not exposed in the public API.
    _subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)

    def is_terminal(self) -> bool:
        """True once the job has reached completed/error."""

        return self.status in _TERMINAL_STATUSES


# ── Store ────────────────────────────────────────────────────────────


_JOBS: dict[str, JobRecord] = {}
_LOCK = asyncio.Lock()


def _now() -> datetime:
    """UTC ``datetime`` — extracted so tests could monkeypatch later."""

    return datetime.now(timezone.utc)


def _evict_expired_locked() -> None:
    """Drop jobs older than ``JOB_TTL``. Caller must hold ``_LOCK``."""

    cutoff = _now() - JOB_TTL
    stale = [jid for jid, rec in _JOBS.items() if rec.updated_at < cutoff]
    for jid in stale:
        # Defensive: notify anyone still subscribed before dropping.
        rec = _JOBS.pop(jid, None)
        if rec is not None:
            for q in rec._subscribers:
                try:
                    q.put_nowait(_TERMINAL_SENTINEL)
                except asyncio.QueueFull:
                    # Subscriber queue is unbounded by default; this is
                    # only here to silence the type checker / future-proof.
                    pass


# ── Public API ───────────────────────────────────────────────────────


async def create_job(request_summary: dict[str, Any]) -> JobRecord:
    """Mint a new ``queued`` job record.

    Args:
        request_summary: Caller-provided dict of non-sensitive request
            fields (path_id, course_id, topic, difficulty, task_count).
            Stored as-is for inspection in the SSE payload.
    """

    async with _LOCK:
        _evict_expired_locked()
        now = _now()
        record = JobRecord(
            job_id=str(uuid.uuid4()),
            status="queued",
            created_at=now,
            updated_at=now,
            request_summary=dict(request_summary),
        )
        _JOBS[record.job_id] = record
        return record


async def get(job_id: str) -> Optional[JobRecord]:
    """Lookup by id, or ``None`` if unknown / evicted."""

    async with _LOCK:
        _evict_expired_locked()
        return _JOBS.get(job_id)


async def update_status(
    job_id: str,
    status: JobStatus,
    *,
    room_id: Optional[uuid.UUID] = None,
    path_id: Optional[uuid.UUID] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Optional[JobRecord]:
    """Move a job to a new status and broadcast a status event.

    Returns the mutated record, or ``None`` if the job has been evicted.
    Broadcasts a synthetic event so subscribers see status transitions
    even without explicit ``append_event`` calls.
    """

    async with _LOCK:
        record = _JOBS.get(job_id)
        if record is None:
            return None
        record.status = status
        record.updated_at = _now()
        if room_id is not None:
            record.room_id = room_id
        if path_id is not None:
            record.path_id = path_id
        if error_code is not None:
            record.error_code = error_code
        if error_message is not None:
            record.error_message = error_message

        event = {
            "job_id": record.job_id,
            "status": record.status,
            "updated_at": record.updated_at.isoformat(),
        }
        if record.room_id is not None:
            event["room_id"] = str(record.room_id)
        if record.path_id is not None:
            event["path_id"] = str(record.path_id)
        if record.error_code is not None:
            event["error_code"] = record.error_code
        if record.error_message is not None:
            event["error_message"] = record.error_message

        record.events.append(event)
        _broadcast_locked(record, event)
        if record.is_terminal():
            _close_subscribers_locked(record)
        return record


async def append_event(job_id: str, payload: dict[str, Any]) -> Optional[JobRecord]:
    """Record a free-form progress event without changing status.

    Useful for "outline received", "tasks generated", etc. The status
    field stays whatever it was; subscribers get ``payload`` verbatim.
    Returns the mutated record, or ``None`` if the job has been evicted.
    """

    async with _LOCK:
        record = _JOBS.get(job_id)
        if record is None:
            return None
        record.updated_at = _now()
        record.events.append(dict(payload))
        _broadcast_locked(record, payload)
        return record


async def subscribe(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield events as they land for a given job.

    Replays any events already recorded (so a late subscriber doesn't
    miss the start of the stream), then yields live events until the
    job reaches a terminal status, at which point the iterator stops.

    If the job is unknown / already evicted, the iterator is empty.
    """

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    backlog: list[dict[str, Any]] = []
    terminal_after_backlog = False

    async with _LOCK:
        record = _JOBS.get(job_id)
        if record is None:
            return
        # Snapshot existing events so this subscriber sees the full
        # history. Future events go through ``_broadcast_locked``.
        backlog = list(record.events)
        if record.is_terminal():
            terminal_after_backlog = True
        else:
            record._subscribers.append(queue)

    for event in backlog:
        yield event
    if terminal_after_backlog:
        return

    try:
        while True:
            event = await queue.get()
            if event is _TERMINAL_SENTINEL:
                return
            yield event
    finally:
        # Detach so a disconnected subscriber doesn't hold the queue.
        async with _LOCK:
            record = _JOBS.get(job_id)
            if record is not None and queue in record._subscribers:
                record._subscribers.remove(queue)


# ── Internal helpers ─────────────────────────────────────────────────


def _broadcast_locked(record: JobRecord, event: dict[str, Any]) -> None:
    """Push ``event`` onto every active subscriber queue.

    Caller must hold ``_LOCK``. ``put_nowait`` is safe because the
    queues are unbounded.
    """

    for q in record._subscribers:
        q.put_nowait(dict(event))


def _close_subscribers_locked(record: JobRecord) -> None:
    """Send the terminal sentinel to every subscriber.

    Caller must hold ``_LOCK``. After this returns the subscriber list
    is cleared — consumers that call ``subscribe`` again on the same
    job_id (within TTL) get the full event backlog and then stop.
    """

    for q in list(record._subscribers):
        q.put_nowait(_TERMINAL_SENTINEL)
    record._subscribers.clear()


def _reset_for_tests() -> None:
    """Drop every stored job. Call from a test fixture, never from prod."""

    _JOBS.clear()


__all__ = [
    "JOB_TTL",
    "JobRecord",
    "JobStatus",
    "append_event",
    "create_job",
    "get",
    "subscribe",
    "update_status",
]
