# Autonomous Build State

## Project
- **Spec file:** spec.md
- **Project directory:** /Users/zijinzhang/Desktop/OpenTutor
- **Branch:** main
- **Status:** IN_PROGRESS
- **Started:** 2026-02-26
- **Last updated:** 2026-02-26

## Current Position
- **Phase:** 1 of 5
- **Task:** 1 of 6
- **Last completed:** Project initialization
- **Next up:** FastAPI + PostgreSQL + Docker Compose setup

## Tech Stack
| Component | Choice | Rationale |
|-----------|--------|-----------|
| Frontend  | Next.js 15 + shadcn/ui + Tailwind | Spec requirement, App Router |
| Backend   | Python FastAPI | Spec requirement |
| Database  | PostgreSQL + pgvector | Spec requirement, structured + vector |
| Cache     | Redis | Session cache, rate limiting |
| LLM       | Multi-model (Claude/GPT/DeepSeek) | Spec requirement, env var switch |
| Testing   | pytest (backend) + Vitest (frontend) | Spec requirement |
| Workflow  | LangGraph | Spec requirement |
| Memory    | EverMemOS pattern (PostgreSQL) | Spec requirement |

## Phases

### Phase 1: Backend Skeleton + Docker (Phase 0-A Week 1) - in_progress
- [ ] Task 1: Docker Compose + project directory structure
- [ ] Task 2: PostgreSQL schema (6 core tables) + Alembic
- [ ] Task 3: FastAPI skeleton + routers (upload, chat, courses, preferences)
- [ ] Task 4: File upload API + Marker PDF parsing
- [ ] Task 5: PageIndex content tree integration
- [ ] Task 6: Chat API with SSE streaming + RAG

### Phase 2: Frontend Skeleton (Phase 0-A Week 2) - pending
- [ ] Task 1: Next.js + shadcn/ui + Tailwind init
- [ ] Task 2: Dashboard page (course list + create)
- [ ] Task 3: File upload page (drag & drop + URL input)
- [ ] Task 4: Three-panel layout (react-resizable-panels)
- [ ] Task 5: Chat panel (assistant-ui integration)
- [ ] Task 6: Notes panel (Markdown rendering)

### Phase 3: Content Generation + Preferences (Phase 0-B) - pending
- [ ] Task 1: AI notes reconstruction (bullet/table/mindmap)
- [ ] Task 2: Mermaid.js + KaTeX rendering
- [ ] Task 3: Quiz extraction from PDF (7 question types)
- [ ] Task 4: Interactive quiz UI
- [ ] Task 5: Preference onboarding wizard (5 steps)
- [ ] Task 6: NL layout control (CopilotKit pattern)

### Phase 4: Preference Learning + Memory (Phase 0-C) - pending
- [ ] Task 1: Preference signal extraction (openakita Compiler pattern)
- [ ] Task 2: Confidence calculation + 90-day decay
- [ ] Task 3: Preference confirmation dialog
- [ ] Task 4: LangGraph WF-4 study session workflow
- [ ] Task 5: EverMemOS memory pipeline (encode/consolidate/retrieve)
- [ ] Task 6: pgvector conversation memory

### Phase 5: Integration Testing + Polish - pending
- [ ] Task 1: End-to-end test suite
- [ ] Task 2: Error/loading/empty state UI
- [ ] Task 3: Toast notifications (sonner)
- [ ] Task 4: Keyboard shortcuts
- [ ] Task 5: Final review and cleanup

## Acceptance Criteria (from spec)
- [ ] Upload PDF → DB has content tree → Chat API references courseware
- [ ] Three-panel layout displays and resizes
- [ ] AI notes panel shows restructured content with Mermaid/KaTeX
- [ ] Quiz panel has extracted questions with interactive answering
- [ ] Say "switch to table" → layout/format changes immediately
- [ ] Preferences remembered across sessions
- [ ] End-to-end: PDF → 3 panels → preference init → learn → preference remembered

## Deferred Issues
| # | Issue | Phase | Workaround | Severity |
|---|-------|-------|------------|----------|

## Session History
| # | Start | End | Phases Completed | Notes |
|---|-------|-----|-----------------|-------|
| 1 | 2026-02-26 | | | Initial build |
