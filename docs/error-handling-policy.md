# Error Handling Policy (Public Beta)

This policy applies to the **local single-user public beta** channel.

## Error tiers

- `Recoverable`: transient/network/provider errors. Log at `warning` and continue with fallback/degraded path.
- `Degraded`: non-critical feature failure (for example optional generation). Log at `exception` and return partial result.
- `Terminal`: request/job cannot continue safely. Persist explicit failed state and return structured error.

## Rules

- Avoid bare `except Exception` in request-facing code paths.
- If a catch-all is required, keep it only at a clear boundary and document why.
- Every swallowed error must emit a log entry with context.
- New PRs must include regression tests or an explicit contract-update note when behavior changes.

## Approved catch-all boundaries (current beta)

- `apps/api/services/ingestion/pipeline.py`
  - Top-level ingestion boundary keeps a catch-all intentionally so every unexpected failure is persisted as `status=failed` instead of leaving jobs in indeterminate state.

## High-risk module status

- `chat`: no new catch-all introduced in this beta hardening pass.
- `ingestion`: background and metadata update paths narrowed to typed exception families; top-level catch-all retained as documented above.
- `scheduler`: notification persistence path narrowed to typed exception families.
- `health`: only typed reachability failures are handled.
