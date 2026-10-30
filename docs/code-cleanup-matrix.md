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

## 2026-10-30 — dead-code removal pass (`chore/remove-dead-code`)

Verified by repo-wide grep (`apps/api`, `tests`, `apps/web/src`) before each deletion; no live import path or frontend call was removed. Net change across `apps/api`: roughly 3.5k lines deleted, 0.4k added.

| Area | Candidate | Action | Rationale |
| --- | --- | --- | --- |
| Backend evaluation | `apps/api/services/evaluation/` (benchmark runner, routing/retrieval/response/recovery evals) | Delete | No non-test importer; the CI "Offline Regression Benchmark" step that drove it was removed with it. `tests/test_eval_regressions.py` and the `eval_response` case in `tests/test_services.py` deleted. |
| Backend experiments | `services/experiments/metrics.py`, `services/experiments/status_matrix.py` | Delete | No importer. `services/experiments/framework.py` stays (used by the flashcards router). Metrics/status tests removed from `tests/test_experiments.py`, `tests/test_learning_pipeline_e2e.py`, `tests/test_wiring_snapshots.py`. |
| Backend agent | `context_builder._load_experiment_config` stub and the `experiment_config` block in `prompt_builder.py` | Delete | Stub was `pass`; nothing ever populated `ctx.metadata["experiment_config"]`. |
| Backend tools | `services/agent/tools/yaml_runner.py` + `_register_yaml_tools` | Delete | Loaded `config/tools/*.yaml`, a directory that does not exist. |
| Backend prompts | `services/agent/prompt_loader.py`, `prompts/{teaching,exercise,planning,review}.md`, `prompts/includes/` | Delete | `render_prompt(agent.name)` never matched a file (agents are `tutor`/`planner`/`layout`/`onboarding`), so the Python fallback always ran. `build_system_prompt` now builds directly; `prompts/teaching_strategies.md` kept (read by `agents/prompts.py`). |
| Backend agent | `base_mixins.DelegationMixin` / `BackgroundTaskMixin`, `BaseAgent.delegate`, `capabilities.check_delegation_escalation`, `TaskPhase.PARALLEL_DISPATCH`/`MERGING`, `AgentContext.swarm_mode`/`parallel_branches`/`merge_strategy`, `SWARM_*` env entries | Delete | No caller of `delegate(`, `delegate_parallel(` or `spawn_background_task(`; `SWARM_*` variables were never read by `config.py`. |
| Backend agent | `services/agent/extensions.py` + 5 `run_hooks` call sites | Delete | No `Extension` subclass was ever registered. |
| Backend orchestrator | `orchestrate_simple`, `InputRequirement`, `BaseAgent.get_required_inputs`, `PlanningAgent.get_required_inputs` | Delete | No caller; the orchestrator never consulted required inputs. Clarify-input parsing kept (frontend `ClarifyCard` sends it). |
| Backend scheduler | `timing_analysis_job`, `escalation_check_job`, `subscribe_sse`, `unsubscribe_sse` | Delete | No-op stubs and their job registrations. |
| Backend shims | `services/agent/agenda_signals.py`; re-export blocks in `tools/react_loop.py`, `tools/react_helpers.py` (underscore aliases), `scheduler/engine.py`, `context_builder.py` | Delete | Importers updated to the real modules (`services.agent.signals`, `scheduler.engine_helpers`, `context_trimming`). |
| Backend scraper | `services/scraper/canvas_parser.py` + `tests/test_canvas_parser.py` | Delete | No runtime caller; the live Canvas path is `services/ingestion/canvas_*`. |
| Backend parser | `parser/pdf.parse_pdf_to_tree`, `_marker_pdf_to_markdown`, duplicate `_get_marker_models`; `parser/url.scrape_url_to_tree` | Delete | No callers; `ingestion/document_loader_formats._get_marker_models` is the single Marker loader. `_markdown_to_tree` and `extract_text_from_html` stay. |
| Backend knowledge | `graph_ops.store_graph_entities`, `_find_similar_memory` | Delete | No external caller. (`sync_to_knowledge_graph` in the same module also has no caller — left for a follow-up.) |
| Backend templates | `services/templates/system.py` DB round-trip, `seed_builtin_templates`, `POST /progress/templates/seed` | Simplify | The 5 presets are module constants with stable `uuid5` ids; `GET /progress/templates` and `POST /progress/templates/apply` keep their contracts (frontend `TemplatesSection` uses both). `LearningTemplate` model/table is now unused. |
| Backend planner | `StudyPlan` double-write in `agents/planner.py`, `models/study_plan.py`, `study_plans` table | Delete | Plans are persisted once as `generated_assets`; `GET /workflows/courses/{id}/study-plans` now reads from there with the same response shape. |
| Backend notifications | "notification system removed" stubs in `agenda.py`, `ambient_monitor.py`, `background_runtime._persist_pp_failures` | Simplify | `Notification` model/router/`_push_notification` are live, so agenda submit and ambient `notify` decisions now actually store a notification (with the existing cooldown check). |
| Backend flags | `voice_enabled` (config, `/health.features`) | Delete | Gated nothing. |
| Backend vision | Duplicate LaTeX-OCR calls in `agents/tutor.py` | Simplify | Single call site in `context_builder` (now gated by `ENABLE_EXPERIMENTAL_VISION`); tutor reuses `ctx.metadata["latex_ocr"]`. |
| Backend LLM | `llm_model_large` / `llm_model_small` and the `large`/`small` alias fallbacks in `llm/router.py` | Delete | One tier vocabulary: `fast` / `standard` / `frontier`. Agent `model_preference` hints updated. |
| Backend LLM | `background_runtime.record_llm_usage` (only metered ReAct tokens) | Replace | `services/llm/base_client` fires a usage hook every time a client records `_last_usage`; `services/llm/usage.install_usage_hook()` (startup) writes `usage_events` fire-and-forget with attribution from a context variable set by `get_current_user` and the orchestrator. |
| Backend reports | `report/generator._save_report` no-op and the `raise_on_persist_failure` flags | Delete | Returned `None`; `reports` table had no model. |
| Backend schema | `course_content_tree.blocks_json`, `course_content_tree.search_vector` (+ index), `learning_progress.ease_factor`, `ingestion_jobs.user_corrected_*`, `learning_templates.tab_preset`, `study_sessions.signals_extracted`; tables `reports`, `audit_logs`, `tool_call_events`, `study_plans` | Delete | Alembic `20261030_0027_drop_orphan_schema` (Postgres only; SQLite uses `create_all`). `tool_calls` was never a table (only a `usage_events` column) so nothing to drop. |

### Verification

- `python -m compileall -q apps/api` clean; `pyflakes` clean on touched files (pre-existing warnings untouched).
- `pytest tests` (minus the network-dependent tiktoken/DNS cases): 1143 passed, 6 skipped.
- Alembic heads: single head `20261030_0027`.
