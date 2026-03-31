# Experimental Integration Status Matrix (v2026-03-10)

## Current States

| Integration | State | Runtime Behavior | Owner |
|---|---|---|---|
| `loom` | `active` | Used by mastery graph + cross-course linking scheduler jobs | learning_science |
| `lector` | `active` | Used by heartbeat review reminders | learning_science |
| `notion_export` | `dormant` | Tool exists but is gated by `ENABLE_EXPERIMENTAL_NOTION_EXPORT` | integrations |
| `cat_pretest` | `active` / `dormant` | CAT adaptive diagnostic pretest behind `ENABLE_EXPERIMENTAL_CAT` | diagnosis |
| `browser` | `active` / `dormant` | Browser automation tool behind `ENABLE_EXPERIMENTAL_BROWSER` | agent_tools |
| `vision` | `active` / `dormant` | Vision / LaTeX OCR service behind `ENABLE_EXPERIMENTAL_VISION` | agent_tools |

## Soft-Delete Policy

1. `dormant` integrations stay wired but feature-gated behind explicit settings.
2. Active integrations must have a live runtime entrypoint or scheduler/tool registration.
3. Removed integrations should be deleted from this matrix instead of left as placeholders.
