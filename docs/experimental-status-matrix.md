# Experimental Integration Status Matrix (v2026-03-10)

## Current States

| Integration | State | Runtime Behavior | Owner |
|---|---|---|---|
| `loom` | `active` | Used by mastery graph + cross-course linking scheduler jobs | learning_science |
| `lector` | `active` | Used by heartbeat review reminders | learning_science |
| `notion_export` | `dormant` | Tool exists but is gated by `ENABLE_EXPERIMENTAL_NOTION_EXPORT` | integrations |
| `legacy_stream_events` | `deprecated` | Compatibility shim only; orchestrator emits raw SSE events | agent_runtime |
| `session_export_sqlite` | `deprecated` | No active route/tool entrypoint | data_portability |
| `preference_prompt_template` | `deprecated` | Prompt composition moved into agent prompt builders | agent_runtime |
| `tutor_prompts_legacy` | `deprecated` | Compatibility shim forwarding to `agents/prompts.py` | agent_runtime |

## Soft-Delete Policy

1. `deprecated` modules remain importable for one migration cycle.
2. Each deprecated module emits deprecation telemetry/logging/warning on import.
3. Physical deletion target: next major cleanup milestone after all references are removed.

