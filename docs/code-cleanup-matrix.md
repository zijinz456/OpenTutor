# Code Cleanup Matrix

This document records the high-confidence dead-code and simplification pass completed on 2026-03-30.

| Area | Candidate | Action | Rationale |
| --- | --- | --- | --- |
| Backend ingestion | `apps/api/services/ingestion/auto_generation.py` | Delete | Legacy duplicate of the packaged `services.ingestion.auto_generation` entrypoint. |
| Backend ingestion | `apps/api/services/ingestion/auto_generation_config.py` | Delete | Old auto-configuration helper replaced by the packaged auto-generation modules. |
| Backend ingestion | `apps/api/services/ingestion/auto_generation/__init__.py` | Keep | Single public import surface for auto-generation behavior. |
| Backend compatibility | `apps/api/services/preference/prompt.py` | Delete | Deprecated compatibility shim with no runtime consumers in the repo. |
| Backend compatibility | `apps/api/services/export/session_export.py` | Delete | Deprecated export shim with no runtime consumers in the repo. |
| Backend compatibility | `apps/api/services/agent/agents/tutor_prompts.py` | Delete | Deprecated prompt shim with no runtime consumers in the repo. |
| Backend compatibility | `apps/api/services/agent/stream_events.py` | Delete | Deprecated stream-event shim kept only by a compatibility test. |
| Backend tests | `tests/test_stream_events.py` | Delete | Covered only the deleted legacy stream-event shim. |
| Backend docs/status | `docs/experimental-status-matrix.md` | Simplify | Remove deprecated placeholders and align documentation with the live integrations matrix. |
| Backend status registry | `apps/api/services/experiments/status_matrix.py` | Simplify | Drop deprecated statuses and deleted integrations from the source of truth. |
| Frontend dashboard logic | `use-dashboard-data.ts` mode recommendation branch | Simplify | Consolidated duplicate recommendation rules and goal fetching into a shared evaluator plus one goal fetch per course. |
| Frontend course logic | `use-agent-lifecycle.ts` mode recommendation branch | Simplify | Reused the shared evaluator to avoid logic drift with the dashboard. |
| Frontend shared logic | `apps/web/src/app/_components/mode-recommendations.ts` | Add | New single source of truth for deadline/mastery/error-rate mode suggestions. |
| Frontend shared logic | `apps/web/src/lib/content-tree.ts` | Add | Merged duplicate tree traversal helpers that had diverged across notes and unit views. |
| Frontend layout sync | Repeated local save + unlock + API sync flows | Simplify | Centralized workspace layout persistence into one helper instead of repeating the same sequence across setup, dashboard, course, and creation flows. |
| Frontend orphan component | `apps/web/src/components/shared/upload-dialog.tsx` | Delete | No runtime consumers and corresponding E2E scenarios were already skipped as unintegrated. |
| Frontend orphan component | `apps/web/src/components/sections/pdf-viewer.tsx` | Delete | No runtime consumers outside its own test; dependent store state was also dead. |
| Frontend store | Legacy `layout` state and PDF overlay state in `workspace.ts` | Delete | Only the block-based `spaceLayout` system remains in use. |
| Frontend store | `cleanupExpiredBlocks` in `workspace-blocks.ts` | Delete | Unused store action with no runtime consumers. |
| Frontend helper | `apps/web/src/lib/layout-presets.ts` | Delete | Legacy layout system helper with no remaining runtime consumers. |
| Frontend helper | `apps/web/src/lib/constants.ts` | Delete | Unused constants file with no remaining consumers. |
| Frontend API helper | `getFileUrl` / `downloadCourseFile` in `apps/web/src/lib/api/courses.ts` | Delete | Only used by the deleted PDF viewer path. |
| Frontend barrel | `apps/web/src/lib/api/index.ts` | Keep, shrink | Public barrel remains, but deleted orphan exports were removed. |
| Frontend UI primitives | `avatar.tsx`, `card.tsx`, `command.tsx`, `dropdown-menu.tsx`, `resizable.tsx`, `separator.tsx`, `sheet.tsx`, `textarea.tsx` | Delete | No consumers after repo-wide reference checks. |
| E2E coverage | Skipped UploadDialog tests in `tests/e2e/course-flow.spec.ts` | Delete | They covered a feature explicitly marked as not integrated. |
| Backend ingestion | `apps/api/services/search/indexer.py` | Delete | SQLite-only no-op compatibility layer with one no-op caller and no remaining value after removing the fake indexing step. |
| Backend knowledge | Unused `graph_memory` exports (`get_learning_path_recommendations`, `_sync_to_knowledge_graph`) | Delete | Repo-wide search found no consumers; keeping them only increased the compatibility surface. |
| Backend progress | Analytics imports routed through `services.progress.tracker` | Simplify | Internal consumers now import read-only analytics from the analytics module directly instead of the mixed read/write tracker module. |
| Backend knowledge | `/api/progress/courses/{course_id}/knowledge-graph-mastery` | Delete | The endpoint had no repo consumers and only returned an empty placeholder payload. |
| Backend knowledge | `apps/api/services/loom.py` | Delete | Repo-internal callers now import directly from `loom_extraction`, `loom_mastery`, and `loom_graph` instead of going through a compatibility barrel. |
| Backend activity | `apps/api/services/activity/tasks.py` | Delete | Repo-internal callers now import directly from `task_types`, `task_review`, and `task_records`, removing the compatibility barrel. |

## Verification

- Repo-wide grep confirms the deleted symbols and deprecated import paths no longer have consumers.
- Web `lint`, web `build`, targeted Vitest suites, and backend router wiring tests passed after the cleanup.
- `tests/test_experiments.py` could not be executed in this environment because `aiosqlite` is missing.
