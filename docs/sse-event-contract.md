# Chat SSE Event Contract (v2026-03-10)

This document defines ordering guarantees for `/api/chat/` streaming responses.

## Core Events

- `status`: phase transitions (`routing` -> `loading` -> `generating`, optional `verifying`)
- `message`: token/content chunks
- `plan_step`: emitted once when a complex request is converted into a background task
- `block_update`: block decision payload (`operations`, `cognitive_state`, `explanation`)
- `done`: terminal envelope for the turn

## Ordering Guarantees

1. `done` is always the final event for a successful stream.
2. If `plan_step` is emitted, it is emitted before `done`.
3. If block decisions were computed, `block_update` is emitted before `done`.
4. `plan_step` does not short-circuit the turn: the assistant still streams a normal answer (`message` and `done`).

## Delivery Rules

- `plan_step`: at most once per turn.
- `block_update`: at most once per turn.
- `done`: exactly once per successful turn.

