# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- Tutor chat now receives the conversation history. Previously every turn was sent to the model as system prompt + current message only, so follow-up questions had no context; the Socratic state machine and cognitive-load session counter also never saw prior turns.
- Chat post-processing (memory encoding, preference extraction, tutor notes, LLM usage records) now runs in-process when the activity engine is off (the default). It used to be written to a queue nobody drained.
- Automatic quiz generation after upload, the `generate_quiz` task and the chat quiz tool all crashed on `QuizExtractionOutcome` (treated as a list). Fixed, and the second per-node generator that raced with `auto_prepare` on every upload was removed.
- Answer grading is no longer an exact string comparison: option labels vs option text, true/false spellings, select-all sets, numbers/percentages, punctuation and width differences are all handled; `fill_blank` questions can carry `accepted_answers`; free-text answers fall back to semantic grading and the rationale is returned (`grading_mode`, `grading_rationale`) and stored on wrong-answer records.
- Mastery no longer includes a study-time term that nothing ever populated (which capped mastery at 0.7 while "mastered" required 0.8). Answer time from quiz submissions is now accumulated as study time.
- `/progress/courses/{id}/velocity` and `/forecast` now verify course ownership and filter by the requesting user.

## [0.1.1-alpha] - 2026-03-12

### Fixed
- Clarify protocol now uses JSON instead of string interpolation to prevent parsing errors with special characters
- Silent exception swallowing in memory pipeline (`except Exception: pass`) replaced with specific exception types and debug logging
- Narrowed broad `except Exception` catches in quiz_generation, memory pipeline, and onboarding persistence
- Fixed broken `test_lector.py` import after `lector_analytics` module removal (graceful skip)

### Improved
- SQLite WAL mode enabled with performance pragmas (busy_timeout, cache_size, synchronous=NORMAL) for better concurrent read/write performance
- CSP `connect-src` directive now environment-aware — `localhost` only allowed in development
- Web Dockerfile upgraded to multi-stage build (builder + runtime) for smaller production images
- Evaluation router tagged as `internal` in OpenAPI docs
- Added `storage.ts` utility for SSR-safe localStorage access

### Added
- Clarify message parsing on backend (orchestrator) — supports both JSON and legacy `[CLARIFY:key:value]` formats, populates `ctx.clarify_inputs`
- 30 new backend tests: JWT auth (7), circuit breaker (9), clarify parser (8), SQLite WAL (1), plus 5 existing test fixes
- Backend test count: 961 passing (up from ~800)

## [0.1.0-alpha] - 2026-03-08

### Added
- Block-based adaptive workspace with 12 block types and progressive feature unlock
- AI tutor with source citations, Socratic questioning, and adaptive depth
- Multi-agent system: Tutor, Planner, and Layout agents with ReAct tool loop
- Content ingestion pipeline: PDF, DOCX, PPTX, URL scraping with 3-tier classification
- Canvas LMS integration with deep module/file extraction
- Quiz generation with 7 question types (MCQ, short answer, fill-in-blank, true/false, matching, ordering, coding)
- Flashcard system with FSRS 4.5 spaced repetition scheduling
- Knowledge graph (LOOM) for concept mastery tracking (experimental)
- Semantic review prioritization (LECTOR) (experimental)
- Cognitive load detection from behavioral signals (experimental)
- Proactive review reminders via in-app notifications
- 10+ LLM provider support (OpenAI, Anthropic, DeepSeek, Ollama, Gemini, Groq, vLLM, LM Studio, OpenRouter, custom)
- Multi-provider LLM router with circuit breaker and fallback
- Bilingual interface (English + Chinese) with 759 i18n keys
- 5 workspace templates (STEM Student, Humanities Scholar, Visual Learner, Quick Reviewer, Blank Canvas)
- Analytics dashboard with learning progress tracking
- Study planner with goal tracking and deadline management
- Docker deployment with multi-stage builds and healthchecks
- One-command local setup via quickstart.sh
- 4-stage CI pipeline (checks, API smoke, E2E, LLM integration)
- 23 pytest test modules + 23 Playwright E2E tests
- Security middleware: rate limiting, prompt injection detection, security headers
- Code sandbox for executing user code (container or process isolation)

### Security
- Rate limiting (simple RPM or cost-aware GCRA mode)
- Prompt injection pre-filter
- Security headers (CSP, HSTS, X-Frame-Options)
- Non-root Docker container user
