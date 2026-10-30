# Experimental Integration Status Matrix (v2026-10-31)

## Current States

| Integration | Flag | Default | What the flag gates | Owner |
|---|---|---|---|---|
| `loom` | `ENABLE_EXPERIMENTAL_LOOM` (`services/loom_flags.loom_enabled()`) | off | Concept-graph build at ingestion (LLM per chunk), problem/card → concept linking, `concept_mastery` updates from quiz/flashcard attempts, prerequisite gaps on wrong answers, confusion-pair detection, `/flashcards/confusion-pairs`, chat-greeting mastery summary, cross-course linking job, agent prerequisite-gap signals, memory teaching-state. Off: `/progress/courses/{id}/knowledge-graph` falls back to the content tree + `learning_progress` mastery. | learning_science |
| `lector` | `ENABLE_EXPERIMENTAL_LECTOR` (`lector_enabled()` — requires LOOM) | off | `/progress/courses/{id}/review-session` + `/rate`, LECTOR ordering in `/flashcards/lector-order`, chat-greeting review summary, agent `lector_review` signal. Review ratings go through the same mastery ledger as quiz answers. | learning_science |
| `cognitive_load` | `ENABLE_COGNITIVE_LOAD` | off | `compute_cognitive_load` per chat turn (DB/text signals only, no LLM), cognitive block-decision rules, cognitive-load reordering of `/flashcards/due`. Off: neutral state (`score 0`, `level low`). | agent |
| `answer_verification` | `ENABLE_ANSWER_VERIFICATION` | off | Verifier + reflection LLM passes after LEARN/PLAN/GENERAL turns (1-3 extra LLM calls per turn). | agent |
| `cat_pretest` | `ENABLE_EXPERIMENTAL_CAT` | off | CAT adaptive diagnostic pretest (`/quiz/pretest/*`); writes an IRT ability estimate to `concept_mastery` from pretest answers. | diagnosis |
| `browser` | `ENABLE_EXPERIMENTAL_BROWSER` | off | Browser automation / `web_search` agent tool. | agent_tools |
| `vision` | `ENABLE_EXPERIMENTAL_VISION` | off | LaTeX OCR on images attached to chat messages. | agent_tools |
| `notion_export` | `ENABLE_EXPERIMENTAL_NOTION_EXPORT` | off | Notion export agent tool. | integrations |

## Policy

1. Every consumer of an experimental layer checks its flag (through the helper where one exists) and returns an empty/neutral result when off — never a 500 and never a silent LLM call.
2. Mastery numbers are written only from stored attempt facts (see ADR-009); an experimental layer may add a derived view but never a second writer.
3. Removed integrations are deleted from this matrix instead of left as placeholders.
