# Autonomous Build State

## Project
- **Spec file:** spec.md
- **Project directory:** /Users/zijinzhang/Desktop/OpenTutor
- **Branch:** main
- **Status:** IN_PROGRESS
- **Started:** 2026-02-26
- **Last updated:** 2026-02-26

## Current Position
- **Phase:** 5 of 5
- **Task:** Polish & integration testing
- **Last completed:** Phase 0-C (Preference learning + Memory + Workflows)
- **Next up:** End-to-end testing and cleanup

## Tech Stack
| Component | Choice | Rationale |
|-----------|--------|-----------|
| Frontend  | Next.js 16 + shadcn/ui + Tailwind | Spec requirement, App Router |
| Backend   | Python FastAPI | Spec requirement |
| Database  | PostgreSQL + pgvector | Spec requirement, structured + vector |
| Cache     | Redis | Session cache, rate limiting |
| LLM       | Multi-model (Claude/GPT/DeepSeek) | Spec requirement, env var switch |
| Memory    | EverMemOS pattern (pgvector) | Spec requirement |

## Phases

### Phase 1: Backend Skeleton + Docker (Phase 0-A Week 1) - DONE
- [x] Task 1: Docker Compose + project directory structure
- [x] Task 2: PostgreSQL schema (7 tables) + auto-create
- [x] Task 3: FastAPI skeleton + 6 routers
- [x] Task 4: File upload API + Marker PDF parsing
- [x] Task 5: PageIndex content tree integration
- [x] Task 6: Chat API with SSE streaming + RAG

### Phase 2: Frontend Skeleton (Phase 0-A Week 2) - DONE
- [x] Task 1: Next.js + shadcn/ui + Tailwind init
- [x] Task 2: Dashboard page (course list + create)
- [x] Task 3: File upload dialog (drag & drop + URL)
- [x] Task 4: Three-panel layout (react-resizable-panels v4)
- [x] Task 5: Chat panel (SSE streaming)
- [x] Task 6: Notes panel (Markdown rendering)

### Phase 3: Content Generation + Preferences (Phase 0-B) - DONE
- [x] Task 1: AI notes reconstruction (bullet/table/mindmap/step/summary)
- [x] Task 2: Mermaid.js + KaTeX rendering
- [x] Task 3: Quiz extraction from PDF (7 question types)
- [x] Task 4: Interactive quiz UI (spaceforge pattern)
- [x] Task 5: Preference onboarding wizard (5 steps)
- [x] Task 6: NL layout control (CopilotKit pattern)
- [x] Task 7: Chapter navigation (TOC sidebar)
- [x] Task 8: NL preference tuning via chat

### Phase 4: Preference Learning + Memory (Phase 0-C) - DONE
- [x] Task 1: Preference signal extraction (openakita Compiler pattern)
- [x] Task 2: Confidence calculation + 90-day decay
- [x] Task 3: Preference confirmation dialog
- [x] Task 4: WF-4 study session workflow (LangGraph-style)
- [x] Task 5: EverMemOS memory pipeline (encode/consolidate/retrieve)
- [x] Task 6: pgvector conversation memory
- [x] Task 7: Keyboard shortcuts (Cmd+0/1/2/3)

### Phase 5: Integration Testing + Polish - in_progress
- [ ] Task 1: Verify Python backend syntax
- [ ] Task 2: Error/loading/empty state UI audit
- [ ] Task 3: Final commit and cleanup

## Acceptance Criteria (from spec)
- [x] Upload PDF → DB has content tree → Chat API references courseware
- [x] Three-panel layout displays and resizes
- [x] AI notes panel shows restructured content with Mermaid/KaTeX
- [x] Quiz panel has extracted questions with interactive answering
- [x] Say "switch to table" → layout/format changes immediately
- [x] Preferences remembered across sessions
- [ ] End-to-end: PDF → 3 panels → preference init → learn → preference remembered

## Deferred Issues
| # | Issue | Phase | Workaround | Severity |
|---|-------|-------|------------|----------|
| 1 | Marker-pdf heavy dep | Phase 1 | Optional install | Low |
| 2 | Full LangGraph StateGraph | Phase 1 | Sequential pipeline | Low |

## Session History
| # | Start | End | Phases Completed | Notes |
|---|-------|-----|-----------------|-------|
| 1 | 2026-02-26 | 2026-02-26 | Phase 0-A | Backend + Frontend skeleton |
| 2 | 2026-02-26 | 2026-02-26 | Phase 0-B, 0-C | Content gen + preferences + memory |
