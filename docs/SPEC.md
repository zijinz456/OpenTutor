# OpenTutor — Reverse-Engineered Product & Technical Specification (Archived Snapshot)

> Generated: 2026-02-27
> Scope at generation time: historical branch snapshot
>
> **Important:** This document is archived context, not the authoritative live spec.
> For current behavior, use `README.md`, `docs/PRD.md`, and code under `apps/api` + `apps/web`.
> Current release channel in this repository is SQLite-first local single-user mode.

---

## 1. Problem Statement

### User Pain Points
Students face three major problems every time they use ChatGPT for learning:
1. **Repetitive prompting** — Must re-describe learning preferences and format requirements every time
2. **No memory** — AI does not remember whether you prefer tables or mind maps, detailed or concise responses
3. **Tedious material gathering** — Need to manually download and organize study materials from Canvas/Blackboard

### Product Positioning
> "Give me any study material, and I will turn it into a personalized learning website that understands you better over time."

OpenTutor is a self-hosted, open-source personalized learning agent. Upload PDF/PPTX/DOCX/URL and it automatically creates a three-panel learning interface with AI notes, quizzes, flashcards, and a chat assistant -- everything gradually adapts to your preferences as you use it.

### Core Differentiation
| Competitor | Limitation | What OpenTutor Goes Beyond |
|------|------|---------------------|
| ChatGPT | Chat only, no memory, text output only | Delivers a complete learning website |
| NotebookLM | Understands documents but only supports chat | Turns documents into an interactive learning space |
| Canvas/Blackboard | Just a document repository | AI auto-organizes + restructures + personalized presentation |
| Quizlet/Anki | Flashcards only, requires manual input | Auto-generates from any material, integrated with notes/Q&A |

---

## 2. Solution Overview

### High-Level Architecture
```
┌──────────────────────────────────────────────────────────┐
│  Frontend — Next.js 16 + shadcn/ui + Tailwind CSS 4      │
│  (React 19, Zustand 5, react-resizable-panels 4)         │
│                        ↕ REST API + SSE                   │
│  Backend — Python FastAPI                                 │
│  ├── API routers (composed + subrouters)                  │
│  ├── Service modules (business logic)                     │
│  └── ORM models (data layer)                              │
│                        ↕                                  │
│  Data — SQLite local mode (Redis optional)                │
└──────────────────────────────────────────────────────────┘
```

### Design Attributes
- **Transparent**: Preferences are viewable and overridable in settings, not a black box
- **Progressive**: Three-stage approach from simple options to natural language to automatic behavior learning
- **Lazy extraction**: Signal extraction defaults to no-extract (~95% returns NONE), avoiding noise
- **Bounded**: Circuit breaker + backoff strategy prevents LLM cascade failures
- **Local-first**: Self-deployed via Docker, data never leaves the user's machine

---

## 3. Product Requirements

### 3.1 User-Visible Behavior

| # | Requirement | Status | Implementation Location |
|---|------|------|----------|
| R1 | Upload PDF/PPTX/DOCX/HTML/TXT/MD and auto-parse into a content tree | ✅ | `routers/upload.py` + `services/ingestion/pipeline.py` |
| R2 | Input URL to auto-fetch and parse content | ✅ | `routers/upload.py` + `services/parser/url.py` |
| R3 | Three-panel learning interface (Notes + Quiz + Chat) | ✅ | `app/course/[id]/page.tsx` |
| R4 | AI notes panel with Mermaid diagrams + KaTeX math formulas | ✅ | `components/course/notes-panel.tsx` + `markdown-renderer.tsx` |
| R5 | Interactive quiz panel (7 question types) | ✅ | `components/course/quiz-panel.tsx` |
| R6 | SSE streaming AI chat with course content RAG | ✅ | `components/chat/chat-panel.tsx` + `routers/chat.py` |
| R7 | 5-step preference onboarding (language/mode/detail level/layout/examples) | ✅ | `app/onboarding/page.tsx` |
| R8 | Natural language preference tuning ("switch to table format") | ✅ | `components/course/nl-tuning-fab.tsx` |
| R9 | Automatic behavioral preference learning | ✅ | `services/preference/extractor.py` |
| R10 | FSRS spaced repetition flashcards | ✅ | `services/spaced_repetition/fsrs.py` |
| R11 | Knowledge graph visualization | ✅ | `components/course/knowledge-graph.tsx` |
| R12 | Learning progress tracking (course -> chapter -> knowledge point) | ✅ | `services/progress/tracker.py` |
| R13 | Canvas LMS integration | ✅ | `routers/canvas.py` + `services/browser/automation.py` |
| R14 | Bilingual interface (Chinese/English) | ✅ | `lib/i18n.ts` (100+ translation keys) |
| R15 | Keyboard shortcuts to switch layouts (Cmd+0/1/2/3) | ✅ | `app/course/[id]/page.tsx` |

### 3.2 Supported Workflows

| Workflow | Description | Endpoint |
|--------|------|------|
| WF-1 Semester Init | Create courses + preference presets + study plan | `POST /api/workflows/semester-init` |
| WF-2 Weekly Prep | Deadlines + progress -> weekly plan | `GET /api/workflows/weekly-prep` |
| WF-3 Assignment Analysis | Analyze assignment requirements -> methodology guide | `POST /api/workflows/assignment-analysis` |
| WF-4 Study Session | Load context -> search -> generate -> extract signals | `POST /api/chat/` (core chat) |
| WF-5 Wrong Answer Review | Cluster wrong answers -> targeted review | `GET /api/workflows/wrong-answer-review` |
| WF-6 Exam Prep | Assess readiness -> day-by-day plan | `POST /api/workflows/exam-prep` |

### 3.3 Scope Boundaries

**Included**:
- Single-user local deployment mode
- PDF/PPTX/DOCX/HTML/TXT/MD file parsing
- URL scraping (3-layer cascade: httpx -> Scrapling -> Playwright)
- 4 LLM providers (OpenAI/Anthropic/DeepSeek/Ollama)
- 7-layer preference cascade (temporary -> course_scene -> course -> global_scene -> global -> template -> system_default)

**Not included**:
- Multi-user authentication (Phase 1)
- Real-time collaboration
- Native mobile applications
- Cloud deployment services

---

## 4. Architecture

### 4.1 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Next.js 16)                       │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Onboard  │  │Dashboard │  │  /new    │  │ Settings │           │
│  │/onboarding│  │   /     │  │ Creation │  │/settings │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │              │              │                 │
│  ┌────┴──────────────┴──────────────┴──────────────┴─────┐         │
│  │              Course Workspace /course/[id]             │         │
│  │  ┌──────────┬──────────┬──────────┬───────────┐       │         │
│  │  │ActivityBar│PDF Viewer│AI Notes │Quiz/Cards │Chat  │         │
│  │  │(sidebar) │(Panel 1)│(Panel 2)│(Panel 3)  │(P4)  │         │
│  │  └──────────┴──────────┴──────────┴───────────┘       │         │
│  │  StatusBar | Breadcrumbs | NL Tuning FAB               │         │
│  └───────────────────────────────────────────────────────┘         │
│                                                                     │
│  State: Zustand (CourseStore + ChatStore)                           │
│  API Client: fetch + SSE generator                                  │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ REST + SSE
┌─────────────────────────┴───────────────────────────────────────────┐
│                        BACKEND (FastAPI)                             │
│                                                                     │
│  ┌─── Routers (11) ────────────────────────────────────────────┐   │
│  │ /content/upload  /chat  /courses  /preferences  /quiz       │   │
│  │ /notes  /workflows  /progress  /flashcards  /canvas         │   │
│  │ /notifications                                               │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                              │                                      │
│  ┌─── Services (14) ────────┴──────────────────────────────────┐   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │ Preference │  │  Memory    │  │   Search   │            │   │
│  │  │  Engine    │  │ Pipeline   │  │  (Hybrid)  │            │   │
│  │  │ 7-layer    │  │ EverMemOS  │  │ RRF Fusion │            │   │
│  │  │ cascade    │  │ 3-stage    │  │ K+V+Tree   │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │ Ingestion  │  │    LLM     │  │  Workflow   │            │   │
│  │  │ Pipeline   │  │   Router   │  │  (6 pipes)  │            │   │
│  │  │ 7-step     │  │ + Circuit  │  │ LangGraph   │            │   │
│  │  │ classify   │  │  Breaker   │  │ StateGraph  │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │  Spaced    │  │  Browser   │  │  Progress   │            │   │
│  │  │ Repetition │  │ Automation │  │  Tracker    │            │   │
│  │  │ FSRS-4.5   │  │ 3-layer    │  │ Mastery     │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │ Knowledge  │  │ Templates  │  │ Scheduler   │            │   │
│  │  │   Graph    │  │ (5 built-  │  │ APScheduler │            │   │
│  │  │ D3-compat  │  │   in)      │  │ 3 jobs      │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  Parsers: PDF (Marker) │ URL (trafilatura) │ Quiz │ Notes  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── Models (14 ORM tables) ──────────────────────────────────┐   │
│  │ User, Course, CourseContentTree, UserPreference,             │   │
│  │ PreferenceSignal, PracticeProblem, PracticeResult,           │   │
│  │ ConversationMemory(pgvector), IngestionJob, StudySession,    │   │
│  │ Assignment, WrongAnswer, LearningProgress, LearningTemplate  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────────────────┐
│                        DATA LAYER                                    │
│  PostgreSQL + pgvector (14 tables, 1536-dim embeddings)              │
│  Redis (caching, rate limiting)                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Lifecycle

```
                     Upload File / Input URL
                           │
                           ▼
              ┌──────────────────────┐
              │  7-Step Ingestion    │
              │  SHA-256 dedup       │
              │  MIME detection      │
              │  Content extraction  │
              │  LLM classification  │
              │  Fuzzy course match  │
              │  Storage + dispatch  │
              └──────────┬───────────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
    CourseContentTree  Assignment  PracticeProblem
    (hierarchical      (homework)  (quiz questions)
     content tree)
           │
           ▼
    ┌──────────────┐    ┌──────────────┐
    │ Hybrid Search│◄───│ User Message │
    │ K + V + Tree │    └──────┬───────┘
    │ RRF Fusion   │           │
    └──────┬───────┘    ┌──────┴───────┐
           │            │ Preferences  │
           ▼            │ 7-layer      │
    ┌──────────────┐    │ cascade      │
    │ LLM Router   │◄───┴──────────────┘
    │ + Memory     │
    │ + RAG context│
    └──────┬───────┘
           │
           ▼
    SSE Streaming Response ────────────┐
           │                           │
           ▼                           ▼
    Frontend Panel Render      Async Post-Processing
                    ┌─────────┴─────────┐
                    ▼                   ▼
            Signal Extractor    Memory Encoder
            (preference signal  (conversation memory
             extraction)         encoding)
                    │                   │
                    ▼                   ▼
            PreferenceSignal    ConversationMemory
            (accumulate ->      (pgvector embedding)
             promote)
```

---

## 5. Technical Design

### 5.1 Preference System -- 7-Layer Cascade (Git Config Pattern)

**Core innovation**: Modeled after Git's config cascade (system -> global -> local), implementing a 7-layer preference override system.

```
Priority (high -> low):
1. temporary    — Session-specific temporary preference (highest priority)
2. course_scene — Course + scene specific (Phase 1)
3. course       — Course-level preference
4. global_scene — Global + scene specific (Phase 1)
5. global       — Global user preference
6. template     — Learning template preset
7. system_default — System default value (lowest priority)
```

**Preference dimensions** (7 total):
| Dimension | Options | Default |
|------|--------|------|
| `note_format` | bullet_point, table, mind_map, step_by_step, summary | bullet_point |
| `detail_level` | concise, balanced, detailed | balanced |
| `language` | en, zh, auto | en |
| `layout_preset` | balanced, notesFocused, quizFocused, chatFocused, fullNotes | balanced |
| `explanation_style` | formal, conversational, socratic, example_heavy, step_by_step | step_by_step |
| `quiz_difficulty` | easy, adaptive, hard | adaptive |
| `visual_preference` | auto, text_heavy, diagram_heavy, mixed | auto |

**Signal extraction flow** (openakita Compiler Pattern):
```
After conversation completes (async):
  1. LLM analyzes user_message + assistant_response
  2. Default is no extraction (~95% returns NONE)
  3. If signal found -> create PreferenceSignal
  4. Calculate confidence:
     confidence = base_score x frequency x recency x consistency
     - explicit expression base=0.7, modification behavior=0.5, behavioral inference=0.3
     - frequency = min(count/5, 1.0)
     - recency = exp(-days/90)
  5. confidence >= 0.4 -> promote to UserPreference
```

### 5.2 Memory System -- EverMemOS 3 Stages

```
Stage 1: ENCODE
  Conversation -> LLM summary -> OpenAI embedding (1536-dim) -> ConversationMemory

Stage 2: CONSOLIDATE
  Word-overlap clustering (threshold=0.7)
  Exponential decay: importance x exp(-days/90)
  Deduplication and merging

Stage 3: RETRIEVE
  User message -> embedding -> pgvector cosine distance
  Minimum similarity 0.3
  Top-K injection into system prompt
```

### 5.3 LLM Routing -- Provider Registry + Circuit Breaker

```
Supported providers:
  ├── OpenAI (gpt-4, gpt-4o-mini, gpt-3.5-turbo)
  ├── Anthropic (claude-3)
  ├── DeepSeek
  └── Ollama (local models)

Circuit Breaker:
  - 3 consecutive failures -> circuit opens
  - Progressive cooldown: [5s, 10s, 20s, 60s]
  - Auto-reset after 120s

Fallback Chain:
  Primary -> Backup1 -> Backup2 -> Error
```

### 5.4 Hybrid Search -- RRF Fusion

```
3-way retrieval:
  ├── Keyword Search: multi-word BM25-lite, level boost
  ├── Vector Search: pgvector cosine similarity
  └── Tree Search: PageIndex hierarchical navigation

RRF fusion ranking:
  score = sum of 1/(60 + rank_i) for each retriever
```

### 5.5 FSRS Spaced Repetition

FSRS-4.5 algorithm implemented from scratch (30%+ more accurate than Anki's SM-2):
- 17 weight parameters (from research paper)
- Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
- State machine: new -> learning -> review -> relearning
- Scheduling: `max(1, round(stability))` days
- Card parameters: difficulty (1-10), stability (days), retrievability

### 5.6 Content Ingestion -- 7-Step Pipeline

```
Step 0: SHA-256 deduplication
Step 1: MIME type detection (python-magic / file extension)
Step 2: Content extraction
  ├── PDF -> Marker -> Markdown
  ├── PPTX -> python-pptx -> text
  ├── DOCX -> python-docx -> text
  ├── HTML -> trafilatura -> text
  └── TXT/MD -> direct read
Step 3: LLM classification (lecture_slides, textbook, assignment, exam_schedule, syllabus, notes, other)
Step 4: Fuzzy course matching (thefuzz, 70% threshold)
Step 5: Content tree construction (PageIndex stack-based heading parser)
Step 6: Dispatch (content_tree, assignments)
```

### 5.7 Browser Automation -- 3-Layer Cascade

```
Layer 1: httpx (simple HTTP, fastest)
    ↓ on failure
Layer 2: Scrapling (anti-bot bypass, JS rendering)
    ↓ on failure
Layer 3: Playwright (full browser, session persistence)
```

### 5.8 Workflow Engine -- LangGraph StateGraph

WF-4 (Study Session) and WF-2 (Weekly Prep) use LangGraph StateGraph:
```python
# WF-4 Study Session
load_context → search_content → generate_response → extract_signals

# WF-2 Weekly Prep
load_deadlines → load_stats → generate_plan
```

### 5.9 Natural Language Interface Control -- CopilotKit Pattern

LLM embeds `[ACTION:...]` markers in responses, parsed and executed by the frontend:
```
[ACTION:set_layout_preset:notesFocused]    -> Expand notes panel
[ACTION:set_preference:note_format:table]  -> Switch note format to table
```

### 5.10 Frontend State Management

**CourseStore (Zustand)**:
```
courses[], activeCourse, contentTree[], loading, error
fetchCourses(), setActiveCourse(), addCourse(), removeCourse(), fetchContentTree()
```

**ChatStore (Zustand)**:
```
messages[], isStreaming, error, onAction callback
sendMessage() — SSE streaming iteration, parses content/action events
```

---

## 6. File Inventory

### Backend (apps/api/) -- 75 files

| File Path | Purpose |
|----------|------|
| `main.py` | FastAPI app entry point, 11 router mounts, lifecycle management |
| `config.py` | Pydantic Settings config (DB, LLM, Upload) |
| `database.py` | SQLAlchemy async engine + session factory |
| `models/__init__.py` | 14 ORM model registrations |
| `models/user.py` | User model (single-user mode) |
| `models/course.py` | Course model + relationships |
| `models/content.py` | Course content tree (hierarchical PageIndex structure) |
| `models/preference.py` | User preferences + preference signals |
| `models/practice.py` | Practice problems + results |
| `models/memory.py` | Conversation memory + pgvector embeddings |
| `models/ingestion.py` | Ingestion jobs, study sessions, assignments, wrong answers |
| `models/progress.py` | Learning progress + learning templates |
| `routers/__init__.py` | Router module initialization |
| `routers/upload.py` | File upload + URL scraping endpoints |
| `routers/chat.py` | SSE streaming chat + RAG + preference injection |
| `routers/courses.py` | Course CRUD + content tree queries |
| `routers/preferences.py` | Preference management + cascade resolution |
| `routers/quiz.py` | Quiz extraction + answer submission |
| `routers/notes.py` | AI notes restructuring |
| `routers/workflows.py` | 6 learning workflow endpoints |
| `routers/progress.py` | Progress tracking + template management + knowledge graph |
| `routers/flashcards.py` | FSRS flashcard generation + review |
| `routers/canvas.py` | Canvas LMS login + sync |
| `routers/notifications.py` | Notification list + read marking |
| `schemas/course.py` | Course request/response Pydantic models |
| `schemas/preference.py` | Preference request/response models |
| `schemas/chat.py` | Chat request/response models |
| `services/llm/router.py` | LLM provider registry + Circuit Breaker |
| `services/parser/pdf.py` | PDF -> Markdown -> content tree (PageIndex) |
| `services/parser/url.py` | URL scraping (trafilatura) |
| `services/parser/quiz.py` | LLM question extraction (7 question types) |
| `services/parser/notes.py` | LLM notes restructuring (5 formats) |
| `services/preference/engine.py` | 7-layer preference cascade resolver |
| `services/preference/extractor.py` | Preference signal extraction (5 dimensions, 4 signal types) |
| `services/preference/confidence.py` | Confidence calculation + signal promotion |
| `services/preference/scene.py` | Scene detection (7 learning scenes, regex) |
| `services/preference/prompt.py` | Preference -> natural language system prompt |
| `services/memory/pipeline.py` | EverMemOS 3-stage memory pipeline |
| `services/ingestion/pipeline.py` | 7-step content ingestion pipeline |
| `services/search/hybrid.py` | RRF hybrid search (keyword + vector + tree) |
| `services/knowledge/graph.py` | Knowledge graph construction (D3 format) |
| `services/progress/tracker.py` | Learning progress tracking + mastery calculation |
| `services/scheduler/engine.py` | APScheduler 3 background tasks |
| `services/spaced_repetition/fsrs.py` | FSRS-4.5 algorithm implementation |
| `services/spaced_repetition/flashcards.py` | Flashcard generation + review processing |
| `services/templates/system.py` | 5 built-in learning templates |
| `services/browser/automation.py` | 3-layer browser cascade + Canvas login |
| `services/workflow/graph.py` | LangGraph StateGraph workflow engine |
| `services/workflow/semester_init.py` | WF-1 Semester initialization |
| `services/workflow/weekly_prep.py` | WF-2 Weekly preparation |
| `services/workflow/assignment_analysis.py` | WF-3 Assignment analysis |
| `services/workflow/study_session.py` | WF-4 Study session |
| `services/workflow/wrong_answer_review.py` | WF-5 Wrong answer review |
| `services/workflow/exam_prep.py` | WF-6 Exam preparation |

### Frontend (apps/web/) -- 35+ files

| File Path | Purpose |
|----------|------|
| `src/app/layout.tsx` | Root layout (metadata + Sonner toast) |
| `src/app/page.tsx` | Home dashboard (course card grid, auto-redirect to onboarding) |
| `src/app/course/[id]/page.tsx` | Course workspace (4 resizable panels + keyboard shortcuts) |
| `src/app/onboarding/page.tsx` | 5-step preference onboarding (split-screen design) |
| `src/app/new/page.tsx` | 4-step project creation flow (upload + parse + feature selection) |
| `src/app/settings/page.tsx` | Settings page (language switching + template application) |
| `src/components/course/notes-panel.tsx` | Notes panel (TOC navigation + Markdown rendering) |
| `src/components/course/quiz-panel.tsx` | Quiz panel (interactive answering + color feedback) |
| `src/components/course/flashcard-panel.tsx` | Flashcard panel (flip animation + FSRS scoring) |
| `src/components/course/progress-panel.tsx` | Progress panel (segmented progress bar + stats cards) |
| `src/components/course/knowledge-graph.tsx` | Knowledge graph (Canvas 2D force-directed graph) |
| `src/components/course/markdown-renderer.tsx` | Markdown renderer (KaTeX + Mermaid) |
| `src/components/course/upload-dialog.tsx` | Upload dialog (file + URL dual modes) |
| `src/components/course/pdf-viewer.tsx` | PDF viewer (placeholder, Phase 1) |
| `src/components/course/nl-tuning-fab.tsx` | Natural language tuning floating action button |
| `src/components/chat/chat-panel.tsx` | Chat panel (SSE streaming + message bubbles) |
| `src/components/preference/preference-confirm-dialog.tsx` | Preference confirmation dialog |
| `src/components/workspace/activity-bar.tsx` | Left activity bar (VS Code style) |
| `src/components/workspace/status-bar.tsx` | Bottom status bar |
| `src/components/ui/*.tsx` | Shared shadcn/ui base components |
| `src/store/course.ts` | Zustand course state management |
| `src/store/chat.ts` | Zustand chat state management |
| `src/lib/api.ts` | REST API client + SSE stream parsing |
| `src/lib/i18n.ts` | Internationalization (6 languages, 100+ keys) |
| `src/lib/utils.ts` | Tailwind class name merging utility |
| `src/app/globals.css` | OKLCH color system + design tokens |

---

## 7. API Endpoint Summary

| Endpoint | Method | Description |
|------|------|------|
| `/api/health` | GET | Health check |
| `/api/content/upload` | POST | Upload file (PDF/PPTX/DOCX/HTML/TXT/MD) |
| `/api/content/url` | POST | Scrape URL and ingest |
| `/api/content/jobs/{course_id}` | GET | View ingestion job list |
| `/api/chat/` | POST | SSE streaming chat (RAG + preferences) |
| `/api/courses/` | GET | List all courses |
| `/api/courses/` | POST | Create new course |
| `/api/courses/{id}` | GET | Get course details |
| `/api/courses/{id}` | DELETE | Delete course (cascade) |
| `/api/courses/{id}/content-tree` | GET | Get course content tree |
| `/api/preferences/` | GET | View user preferences |
| `/api/preferences/` | POST | Create/update preference (Upsert) |
| `/api/preferences/resolve` | GET | Cascade-resolve effective preferences |
| `/api/quiz/extract` | POST | Extract quiz questions from content |
| `/api/quiz/{course_id}` | GET | List all questions for a course |
| `/api/quiz/submit` | POST | Submit answer and get feedback |
| `/api/notes/restructure` | POST | AI notes restructuring |
| `/api/workflows/semester-init` | POST | WF-1 Semester initialization |
| `/api/workflows/weekly-prep` | GET | WF-2 Weekly preparation |
| `/api/workflows/assignment-analysis` | POST | WF-3 Assignment analysis |
| `/api/workflows/wrong-answer-review` | GET | WF-5 Wrong answer review |
| `/api/workflows/wrong-answer-review/mark` | POST | Mark wrong answer as reviewed |
| `/api/workflows/exam-prep` | POST | WF-6 Exam preparation |
| `/api/progress/courses/{id}` | GET | Learning progress overview |
| `/api/progress/templates` | GET | List learning templates |
| `/api/progress/templates/apply` | POST | Apply learning template |
| `/api/progress/templates/seed` | POST | Seed built-in templates |
| `/api/progress/courses/{id}/knowledge-graph` | GET | Knowledge graph data |
| `/api/flashcards/generate` | POST | Generate FSRS flashcards |
| `/api/flashcards/review` | POST | Review flashcard (FSRS scoring) |
| `/api/canvas/login` | POST | Canvas LMS browser login |
| `/api/canvas/sync` | POST | Sync Canvas courses/assignments |
| `/api/notifications/` | GET | Get notification list |
| `/api/notifications/{id}/read` | POST | Mark notification as read |

---

## 8. Data Models (14 Tables)

```
User ──────────────────────────────────────┐
  │                                         │
  ├── Course ─────────────────────────────┐ │
  │     ├── CourseContentTree (self-ref)   │ │
  │     ├── PracticeProblem               │ │
  │     │     └── PracticeResult          │ │
  │     ├── Assignment                    │ │
  │     ├── LearningProgress              │ │
  │     └── IngestionJob                  │ │
  │                                       │ │
  ├── UserPreference                      │ │
  ├── PreferenceSignal                    │ │
  ├── ConversationMemory (pgvector 1536d) │ │
  ├── StudySession                        │ │
  ├── WrongAnswer                         │ │
  └── (references) LearningTemplate       │ │
                                          │ │
LearningTemplate (standalone, 5 built-in) ┘ ┘
```

### Key Table Descriptions

| Table | Column Count | Key Characteristics |
|------|--------|----------|
| `users` | 3 | Single-user mode, Phase 0 |
| `courses` | 6 | JSONB metadata_, cascade delete |
| `course_content_tree` | 10 | Self-referential (parent_id), PageIndex hierarchy |
| `user_preferences` | 9 | 3-7 layer scope, confidence score |
| `preference_signals` | 7 | 4 signal types, JSONB context |
| `practice_problems` | 8 | 7 question types, JSONB options |
| `practice_results` | 5 | Correct/incorrect determination, AI explanation |
| `conversation_memories` | 9 | Vector(1536) embedding, importance decay |
| `ingestion_jobs` | 15 | SHA-256 dedup, 7-step state machine |
| `study_sessions` | 9 | Message/quiz/signal counts |
| `assignments` | 8 | Canvas/manual source, deadlines |
| `wrong_answers` | 8 | review_count, mastered flag |
| `learning_progress` | 12 | mastery_score, FSRS ease_factor |
| `learning_templates` | 7 | JSONB preferences, is_builtin |

---

## 9. Frontend Routing & UI Architecture

### Route Table

| Route | Page | Description |
|------|------|------|
| `/` | Dashboard | Course card grid, first-time onboarding redirect |
| `/onboarding` | Onboarding | 5-step preference setup (split-screen) |
| `/new` | New Project | 4-step creation flow (mode -> upload -> parse -> features) |
| `/course/[id]` | Workspace | 4-panel learning workspace |
| `/settings` | Settings | Language switching + template management |

### Course Workspace Layout

```
┌───────────────────────────────────────────────────────────────┐
│ Breadcrumbs: Course > Chapter > Section                       │
├────┬──────────┬──────────┬─────────────────┬──────────────────┤
│    │          │          │  Tab: Quiz      │                  │
│ A  │  PDF     │  AI      │  Tab: Flashcard │    Chat         │
│ c  │  Viewer  │  Notes   │  Tab: Progress  │    Panel        │
│ t  │  (25%)   │  (25%)   │  Tab: KG        │    (25%)        │
│ i  │          │          │     (25%)       │                  │
│ v  │          │          │                 │                  │
│ i  │          │          │                 │                  │
│ t  │          │          │                 │                  │
│ y  │          │          │                 │                  │
│    │          │          │                 │                  │
│ B  │          │          │                 │                  │
│ a  │          │          │                 │                  │
│ r  │          │          │                 │                  │
├────┴──────────┴──────────┴─────────────────┴──────────────────┤
│ Hidden Panels Restore Bar (collapsed panels shown here)       │
├───────────────────────────────────────────────────────────────┤
│ Status Bar: Course Name │ Chapter │ Practice │ Study Time     │
└───────────────────────────────────────────────────────────────┘
                                                ┌─────────────┐
                                                │ NL Tuning   │
                                                │ FAB Button  │
                                                └─────────────┘
```

**Layout presets** (Cmd+0/1/2/3):
| Shortcut | Preset | PDF | Notes | Quiz | Chat |
|--------|------|-----|-------|------|------|
| Cmd+0 | balanced | 25% | 25% | 25% | 25% |
| Cmd+1 | notesFocused | 15% | 45% | 20% | 20% |
| Cmd+2 | quizFocused | 15% | 15% | 50% | 20% |
| Cmd+3 | chatFocused | 15% | 15% | 15% | 55% |

---

## 10. Borrowed Design Patterns

| Source Project | Pattern | Application in OpenTutor |
|----------|------|----------------------|
| EverMemOS | 3-stage memory pipeline | `services/memory/pipeline.py` |
| PageIndex | Heading-based Markdown tree parsing | `services/parser/pdf.py` |
| openakita | Dual-track LLM + "default no-extract" | `services/preference/extractor.py` |
| openakita | Compiler pattern lightweight extraction | Signal extraction async post-processing |
| nanobot | Provider Registry keyword registration | `services/llm/router.py` |
| spaceforge | FSRS flashcard UI pattern | `components/course/flashcard-panel.tsx` |
| CopilotKit | NL -> UI control via ACTION markers | `routers/chat.py` [ACTION:...] |
| Marker | PDF -> Markdown conversion | `services/parser/pdf.py` |
| Git | Config cascade (system -> global -> local) | `services/preference/engine.py` |

---

## 11. Technology Stack Summary

### Backend Dependencies
| Category | Technology | Version |
|------|------|------|
| Framework | FastAPI | 0.115.6 |
| Server | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy (async) | 2.0.36 |
| Database | PostgreSQL + pgvector | 0.3.6 |
| Cache | Redis | 5.2.1 |
| LLM | OpenAI + Anthropic | 1.65.2 / 0.46.0 |
| Workflow | LangGraph | >=0.2.0 |
| Scheduler | APScheduler | >=3.10.0 |
| PDF | Marker (optional) + trafilatura | 2.0.0 |
| Browser | Scrapling + Playwright | >=0.2 / >=1.49.0 |
| Canvas | canvasapi | >=3.3.0 |

### Frontend Dependencies
| Category | Technology | Version |
|------|------|------|
| Framework | Next.js | 16.1.6 |
| UI | React | 19.2.3 |
| State | Zustand | 5.0.11 |
| Styling | Tailwind CSS | 4 |
| Component Library | Radix UI + shadcn | latest |
| Panels | react-resizable-panels | 4.6.5 |
| Markdown | react-markdown + KaTeX + Mermaid | latest |
| Notifications | Sonner | 2.0.7 |
| Icons | lucide-react | 0.575.0 |

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|------|----------|
| LLM service unavailable | Core functionality down | Circuit Breaker + multi-provider Fallback |
| pgvector performance bottleneck | Memory retrieval slows down | Minimum similarity threshold + Top-K limit |
| Poor PDF parsing quality | Incomplete content tree | Marker (high quality) fallback to PyPDF2 |
| Preference signal noise | Incorrect preference overrides | "Default no-extract" (~95% NONE) + confidence threshold |
| Single-user mode security | No auth protection | Local deployment only, add auth in Phase 1 |
| Large file uploads | Memory overflow | 50MB limit + SHA-256 dedup |
| Canvas session expiration | Sync interrupted | Session persistence + expiration reminder notification |
| react-resizable-panels v4 API changes | Layout control issues | Already adapted to v4 API (useGroupRef, orientation) |

---

## 13. Statistical Summary

| Metric | Value |
|------|------|
| Total lines of code | ~12,110 LOC |
| Commits | 2 (Phase 0-A, Phase 0-B+C) |
| Backend source files | ~75 |
| Frontend source files | ~35 |
| ORM tables | 14 |
| API endpoints | 34 |
| API router modules | 11 |
| Service modules | 14 |
| Learning workflows | 6 |
| Preference dimensions | 7 |
| Preference cascade layers | 7 |
| Question types | 7 |
| LLM providers | 4 |
| Built-in learning templates | 5 |
| i18n languages | 6 |
| i18n translation keys | 100+ |
| Frontend routes | 6 |
| Frontend panels | 4 (resizable) |
| Layout presets | 5 |
