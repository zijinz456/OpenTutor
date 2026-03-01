# OpenTutor Zenus

[![CI](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml/badge.svg)](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)

> **"Give me any learning material, I'll turn it into a personalized learning website that understands you better the more you use it."**

A self-hosted personalized learning agent. Upload any educational material (PDF, PPTX, DOCX, URL), and OpenTutor Zenus creates an interactive multi-panel learning experience with AI notes, quizzes, flashcards, and a chat assistant — all adapting to your preferences over time.

## Features

### Multi-Panel Learning Interface
- **AI Notes Panel** — Auto-restructured content with Mermaid diagrams + KaTeX math rendering
- **Interactive Quiz Panel** — Auto-extracted questions (7 types: MCQ, T/F, short answer, multi-answer, fill-in-blank, matching, ordering) with real-time color feedback
- **FSRS Flashcard Panel** — Spaced repetition flashcards with FSRS-4.5 scheduling (30%+ more accurate than Anki's SM-2)
- **AI Chat Assistant** — Course material RAG with SSE streaming responses
- **Knowledge Graph** — D3-powered visual topic map with mastery coloring
- **Learning Progress Tracker** — Course → chapter → knowledge point granularity with trend analytics
- **Study Plan Panel** — Semester and weekly study plan visualization
- **Wrong Answer Review Panel** — Error diagnostic with VCE classification + derived practice
- **PDF Viewer** — In-app document viewer for uploaded files

### Multi-Agent AI System
- **10 specialist agents** — Teaching, Exercise, Planning, Review, Preference, Scene, Code Execution, Curriculum, Assessment, Motivation
- **2-stage intent routing** — Rule-based pattern matching → LLM fallback classification (11 intent types)
- **ReAct tool system** — 8 built-in education tools (search content, lookup progress, create quiz, etc.) with thought-action-observation cycles
- **Fatigue detection** — Automatic motivational intercept when student frustration is detected
- **Reflection self-check** — Optional response improvement on substantive teaching answers
- **Background task queue** — Submit, approve, cancel, and retry long-running agent tasks
- **Tool extensibility** — Python plugins, MCP protocol integration, YAML declarative workflows
- **Context window management** — Token-aware compaction with LLM summarization of old conversation history

### Preference Learning (Core Innovation)
- **7-layer preference cascade** — Git Config-style resolution: system_default → template → global → global_scene → course → course_scene → temporary (last wins)
- **Behavior-based signal extraction** — Implicit + explicit signals from conversations (~95% return NONE = no noise)
- **Confidence scoring** — `base × frequency × recency × consistency` with 90-day exponential decay
- **NL preference tuning** — Say "switch to table format" or "make it more concise" and it changes immediately
- **5 built-in learning templates** — STEM, Humanities, Language, Visual, Quick Review

### Scene System
- **5 preset scenes** — Daily Study (📚), Exam Prep (🎯), Homework (✍️), Error Review (🔄), Notes (📝)
- **Custom scene creation** — Define your own tab layout, workflow, and AI behavior
- **Scene-scoped preferences** — Override preferences per learning context
- **UI snapshot persistence** — Save and restore tab layout, scroll positions per course-scene pair
- **Scene policy engine** — Auto-recommends optimal scene based on message content + active tab context

### Content Ingestion
- **Multi-format upload** — PDF, PPTX, DOCX, HTML, TXT, Markdown
- **URL scraping** — 3-layer browser cascade (httpx → Scrapling → Playwright) for any website including authenticated content
- **7-step ingestion pipeline** — MIME detect → content extract → LLM classify → SHA-256 dedup → fuzzy match → store → dispatch
- **Canvas LMS integration** — Sync courses, assignments, and submissions

### AI & Search
- **Multi-model LLM support** — 11 providers with circuit breaker + progressive cooldown fallback:
  - Cloud: OpenAI, Anthropic, DeepSeek, OpenRouter, Gemini, Groq
  - Local: Ollama, vLLM, LM Studio, TextGen WebUI, custom (any OpenAI-compatible endpoint)
- **Runtime LLM configuration** — Switch providers and models from the settings UI without restarting
- **Model size routing** — Large models for teaching/planning, small models for preference/scene agents
- **RRF Hybrid Search** — Reciprocal Rank Fusion combining BM25 full-text (PostgreSQL `ts_rank_cd`), tree hierarchy, and pgvector cosine similarity
- **RAG-Fusion** — Multi-query expansion for complex questions (LEARN/REVIEW intents)
- **EverMemOS Memory Pipeline** — Full 3-stage encode → consolidate → retrieve with 7 MemCell types, BM25+vector hybrid retrieval (0.7/0.3 weighted fusion)
- **Graph Memory** — Entity and relationship extraction from conversations, stored in knowledge graph

### Code Execution Sandbox
- **Container isolation** — Docker or Podman runtime for safe Python code execution
- **Process fallback** — Automatic fallback to subprocess when containers are unavailable
- **Configurable** — Custom container image, timeout (default 5s), runtime selection

### Evaluation & Experiments
- **Evaluation framework** — Automated benchmarks for intent routing accuracy, response quality, and RAG retrieval relevance
- **A/B testing** — Create experiments, assign variants, record metrics, analyze results

### Security & Middleware
- **Security headers** — CSP, HSTS, X-Frame-Options, X-Content-Type-Options
- **Rate limiting** — Token bucket algorithm (120 RPM default, 20 RPM for LLM endpoints)
- **Audit logging** — Request/response logging for debugging and compliance
- **Prompt injection detection** — Input screening for common injection patterns
- **JWT authentication** — Optional production mode with register/login/refresh (bcrypt + HS256)

### Workflows
- **6 LangGraph-style pipelines** — Semester init, weekly prep, assignment analysis, study sessions, wrong answer review, exam prep
- **Study plan persistence** — Save and retrieve semester/weekly plans
- **Proactive scheduling** — APScheduler for reminders and FSRS review nudges

### Notifications & PWA
- **SSE notification streaming** — Real-time notifications via Server-Sent Events
- **Service worker** — Cache-first for static assets, network-first for API calls
- **PWA manifest** — Installable as a Progressive Web App

### i18n
- Chinese / English interface with 100+ translation keys

## Quick Start

### Docker (Recommended)

```bash
# 1. Clone
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor

# 2. Configure
cp .env.example .env
# Edit .env: add your API key (at least one of OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY)
# Optional: OPENROUTER_API_KEY, GEMINI_API_KEY, GROQ_API_KEY for additional providers
# Optional: OLLAMA_BASE_URL for local inference
# Default compose runs with LLM_REQUIRED=true, so AI endpoints stay disabled until a real provider is configured

# 3. Start
docker compose up -d

# Or use the local dev wrapper
bash scripts/dev_local.sh up

# 4. Access
# Backend API: http://localhost:8000
# Frontend:    http://localhost:3000
```

The default compose stack starts `db`, `redis`, `api`, and `web`. The API container auto-creates tables, seeds built-in templates and scenes, and runs the background activity engine so queued agent tasks execute automatically.

### Local Dev Shortcuts

```bash
# Check whether the host is ready for full-stack validation
bash scripts/dev_local.sh preflight

# Run all host-safe checks even if Docker/Postgres is unavailable
bash scripts/dev_local.sh verify-host

# Start and wait for db + redis + api + web
bash scripts/dev_local.sh up

# Run smoke + regression + DB integration + representative Playwright flow
bash scripts/dev_local.sh verify

# Run the full Playwright suite against the existing local stack
bash scripts/dev_local.sh verify --all-e2e

# Add real-provider validation on top
bash scripts/dev_local.sh verify --with-real-llm

# Inspect or stop the stack
bash scripts/dev_local.sh status
bash scripts/dev_local.sh logs api
bash scripts/dev_local.sh down
```

The `verify` command hits the existing Docker Compose stack on `localhost:8000`
and `localhost:3000`; it does not boot a second hidden test server pair.
Use `preflight` when you want a fast readiness report, and `verify-host` when you
want the script to run everything possible on the current machine while marking
DB or stack-gated checks as explicit skips.
Both commands also write a markdown summary to
`tmp/verification-summary.md` by default; override it with
`REPORT_FILE=/custom/path.md`. A matching JSON summary is written to
`tmp/verification-summary.json` by default and can be overridden with
`REPORT_JSON_FILE=/custom/path.json`.

### Manual Setup

```bash
# Prerequisites: PostgreSQL 17 with pgvector, Redis, Python 3.11, Node.js 20+

# Database
docker compose up -d db redis   # or install PostgreSQL + pgvector + Redis manually

# Backend
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../../.env.example .env   # then edit with your API keys
alembic upgrade head && uvicorn main:app --reload

# Frontend (new terminal)
cd apps/web
npm install
npm run dev                  # http://localhost:3000
```

### Prerequisites
- Docker + Docker Compose (for Docker setup)
- Python 3.11 (required; `scripts/dev_local.sh verify` now hard-fails on other versions)
- Node.js 20+ (for frontend)
- PostgreSQL 17 with pgvector extension
- Redis 7+
- At least one LLM API key or local inference backend

## Project Structure

```
OpenTutor/
├── apps/
│   ├── api/                           # FastAPI backend
│   │   ├── main.py                    # Entry point with lifespan management
│   │   ├── config.py                  # Environment configuration (pydantic-settings)
│   │   ├── database.py                # SQLAlchemy async engine + session factory
│   │   ├── models/                    # 27 SQLAlchemy ORM models (18 files)
│   │   ├── routers/                   # 18 API endpoint modules (~90 endpoints)
│   │   ├── schemas/                   # Pydantic request/response models
│   │   ├── middleware/                # Security headers, rate limit, audit logging
│   │   ├── services/
│   │   │   ├── agent/                 #   Multi-agent orchestrator + 10 specialists
│   │   │   │   ├── orchestrator.py    #     Central coordinator (intent → context → route → stream)
│   │   │   │   ├── tools/             #     ReAct tool system + MCP client + YAML runner
│   │   │   │   └── [10 agents]        #     Teaching, Exercise, Planning, Review, etc.
│   │   │   ├── llm/                   #   11 LLM providers + circuit breaker
│   │   │   ├── ingestion/             #   7-step content ingestion pipeline
│   │   │   ├── preference/            #   7-layer cascade engine + signal extraction
│   │   │   ├── memory/                #   EverMemOS 3-stage memory pipeline
│   │   │   ├── search/                #   RRF hybrid search + RAG-fusion
│   │   │   ├── scene/                 #   5 preset scenes + policy engine
│   │   │   ├── knowledge/             #   Graph builder + graph memory
│   │   │   ├── spaced_repetition/     #   FSRS-4.5 algorithm implementation
│   │   │   ├── workflow/              #   6 LangGraph-style pipelines
│   │   │   ├── browser/               #   3-layer scraping cascade
│   │   │   ├── activity/              #   Background task engine
│   │   │   ├── evaluation/            #   Routing/response/retrieval evals
│   │   │   ├── experiment/            #   A/B testing engine
│   │   │   ├── diagnosis/             #   VCE error classification
│   │   │   ├── learning_science/      #   Difficulty selection + knowledge tracing
│   │   │   ├── auth/                  #   JWT + password hashing
│   │   │   ├── scheduler/             #   APScheduler for proactive reminders
│   │   │   ├── templates/             #   5 built-in learning templates
│   │   │   └── parser/                #   PDF, quiz, notes, URL parsers
│   │   ├── alembic/                   # 12 database migrations
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── web/                           # Next.js 16 frontend
│       ├── src/
│       │   ├── app/                   # App Router (6 routes)
│       │   │   ├── page.tsx           #   Dashboard
│       │   │   ├── course/[id]/       #   Main learning interface (multi-panel)
│       │   │   ├── analytics/         #   Learning analytics dashboard
│       │   │   ├── settings/          #   User settings + LLM configuration
│       │   │   ├── onboarding/        #   5-step preference setup
│       │   │   └── new/               #   4-step project creation
│       │   ├── components/            # React components
│       │   │   ├── course/            #   Notes, quiz, flashcard, chat, review, etc.
│       │   │   ├── chat/              #   SSE streaming chat
│       │   │   ├── workspace/         #   Activity bar, status bar
│       │   │   ├── scene/             #   Scene selector
│       │   │   ├── preference/        #   Onboarding wizard, confirm dialog
│       │   │   └── ui/                #   shadcn/ui primitives
│       │   ├── store/                 # Zustand state (course, chat, scene)
│       │   └── lib/                   # API client, i18n, utilities
│       ├── public/
│       │   ├── sw.js                  # Service worker (offline support)
│       │   └── manifest.json          # PWA manifest
│       └── package.json
│
├── tests/                             # 11 pytest files + 21 Playwright E2E specs
├── scripts/                           # Smoke test + LLM integration test scripts
├── docs/                              # Detailed specification
├── .github/workflows/ci.yml           # 4-stage CI: checks → smoke → e2e → LLM
├── docker-compose.yml                 # PostgreSQL + Redis + API + Web
└── .env.example                       # Environment variable template
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Next.js 16 Frontend (React 19 + shadcn/ui + Tailwind CSS v4)   │
│  Zustand state │ react-resizable-panels │ Mermaid + KaTeX        │
│  6 routes │ PWA + service worker │ SSE streaming │ i18n (zh/en)  │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST API + SSE
┌────────────────────────────▼────────────────────────────────────┐
│  FastAPI Backend                                                 │
│                                                                  │
│  ┌──── Middleware ─────────────────────────────────────────────┐ │
│  │ SecurityHeaders │ RateLimit (120/20 RPM) │ AuditLog          │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──── Router Layer (18 routers, ~90 endpoints) ───────────────┐ │
│  │ content │ chat │ courses │ preferences │ quiz │ notes         │ │
│  │ flashcards │ workflows │ progress │ scenes │ canvas │ scrape  │ │
│  │ wrong-answers │ tasks │ notifications │ eval │ experiments    │ │
│  └────────────────────────┬─────────────────────────────────────┘ │
│                           │                                      │
│  ┌──── Agent Orchestrator ▼────────────────────────────────────┐ │
│  │ Intent classify → Context load → Trim → Route → Stream      │ │
│  │                                                              │ │
│  │ Teaching │ Exercise │ Planning │ Review │ Preference │ Scene  │ │
│  │ CodeExec │ Curriculum │ Assessment │ Motivation               │ │
│  │                                                              │ │
│  │ ReAct tools │ MCP client │ YAML workflows │ Reflection       │ │
│  └────────────────────────┬─────────────────────────────────────┘ │
│                           │                                      │
│  ┌──── Service Layer ─────▼────────────────────────────────────┐ │
│  │ llm/          ── 11 providers + circuit breaker + fallback   │ │
│  │ ingestion/    ── 7-step classification pipeline              │ │
│  │ preference/   ── 7-layer cascade + signal extraction         │ │
│  │ memory/       ── EverMemOS encode → consolidate → retrieve   │ │
│  │ search/       ── RRF hybrid (BM25 + tree + vector) + fusion  │ │
│  │ scene/        ── 5 presets + policy engine + snapshots        │ │
│  │ spaced_rep/   ── FSRS-4.5 from scratch                      │ │
│  │ workflow/     ── 6 LangGraph-style pipelines                 │ │
│  │ knowledge/    ── Topic graph + graph memory                  │ │
│  │ browser/      ── httpx → Scrapling → Playwright              │ │
│  │ activity/     ── Background task engine                      │ │
│  │ evaluation/   ── Routing/response/retrieval benchmarks       │ │
│  │ experiment/   ── A/B testing                                 │ │
│  │ diagnosis/    ── VCE error classification                    │ │
│  └────────────────────────┬─────────────────────────────────────┘ │
│                           │                                      │
│  ┌──── Data Layer ────────▼────────────────────────────────────┐ │
│  │ SQLAlchemy 2.0 (async) │ 27 ORM models │ UUID PKs            │ │
│  │ pgvector embeddings │ Alembic migrations (12 versions)       │ │
│  └──────────────────────────────────────────────────────────────┘ │
└───────────┬─────────────────┬──────────────────┬────────────────┘
            ▼                 ▼                  ▼
     PostgreSQL 17       Redis 7           LLM APIs (11+)
     + pgvector         (caching)       Cloud: OpenAI / Anthropic /
                                        DeepSeek / OpenRouter /
                                        Gemini / Groq
                                        Local: Ollama / vLLM /
                                        LM Studio / TextGen WebUI
```

## API Endpoints

<details>
<summary><strong>Content Management</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/content/upload` | POST | Upload file (PDF/PPTX/DOCX/HTML/TXT/MD) |
| `/api/content/url` | POST | Scrape URL and ingest |
| `/api/content/jobs/{course_id}` | GET | Ingestion job status |
| `/api/content/files/{job_id}` | GET | File details |
| `/api/content/files/by-course/{course_id}` | GET | List files in course |

</details>

<details>
<summary><strong>Chat</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat/` | POST | SSE streaming chat with RAG |
| `/api/chat/courses/{id}/sessions` | GET | List chat sessions |
| `/api/chat/sessions/{id}/messages` | GET | Get session messages |

</details>

<details>
<summary><strong>Courses</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/courses/` | GET | List courses |
| `/api/courses/` | POST | Create course |
| `/api/courses/{id}` | GET | Get course details |
| `/api/courses/{id}` | DELETE | Delete course |
| `/api/courses/{id}/content-tree` | GET | Hierarchical content tree |

</details>

<details>
<summary><strong>Quiz</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/quiz/extract` | POST | Generate quiz from content |
| `/api/quiz/{course_id}` | GET | List practice problems |
| `/api/quiz/submit` | POST | Submit quiz answer + feedback |
| `/api/quiz/{course_id}/generated-batches` | GET | List generated batches |
| `/api/quiz/save-generated` | POST | Save AI-generated quiz set |

</details>

<details>
<summary><strong>Notes</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notes/restructure` | POST | AI notes generation (5 formats) |
| `/api/notes/generated/save` | POST | Save generated notes |
| `/api/notes/generated/{course_id}` | GET | List generated notes |

</details>

<details>
<summary><strong>Flashcards</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/flashcards/generate` | POST | Generate FSRS flashcards |
| `/api/flashcards/review` | POST | Review flashcard (FSRS rating 1-4) |
| `/api/flashcards/generated/save` | POST | Save generated flashcard set |
| `/api/flashcards/generated/{course_id}` | GET | List generated flashcard sets |

</details>

<details>
<summary><strong>Preferences</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/preferences/` | GET | List user preferences |
| `/api/preferences/` | POST | Set preference |
| `/api/preferences/signals` | GET | List preference signals |
| `/api/preferences/resolve` | GET | Resolve 7-layer cascade |
| `/api/preferences/runtime/llm` | GET | Get runtime LLM configuration |
| `/api/preferences/runtime/llm` | PUT | Update LLM provider/model |
| `/api/preferences/runtime/llm/test` | POST | Test LLM connection |

</details>

<details>
<summary><strong>Scenes</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scenes/` | GET | List available scenes |
| `/api/scenes/{course_id}/active` | GET | Get active scene for course |
| `/api/scenes/{course_id}/switch` | POST | Switch scene + save snapshot |
| `/api/scenes/custom` | POST | Create custom scene |

</details>

<details>
<summary><strong>Workflows</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workflows/semester-init` | POST | Semester setup pipeline |
| `/api/workflows/weekly-prep` | GET | Weekly study plan |
| `/api/workflows/assignment-analysis` | POST | Assignment analysis |
| `/api/workflows/wrong-answer-review` | GET | Wrong answer review |
| `/api/workflows/wrong-answer-review/mark` | POST | Mark as reviewed |
| `/api/workflows/exam-prep` | POST | Exam preparation |
| `/api/workflows/study-plans/save` | POST | Save study plan |

</details>

<details>
<summary><strong>Progress</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/progress/courses/{id}` | GET | Course learning progress |
| `/api/progress/overview` | GET | Overall learning stats |
| `/api/progress/courses/{id}/trends` | GET | Course learning trends |
| `/api/progress/trends` | GET | Global learning trends |
| `/api/progress/templates` | GET | Built-in learning templates |
| `/api/progress/templates/apply` | POST | Apply template to course |
| `/api/progress/memory-stats` | GET | Memory pipeline statistics |
| `/api/progress/memory-consolidate` | POST | Trigger memory consolidation |
| `/api/progress/courses/{id}/knowledge-graph` | GET | Knowledge graph data |

</details>

<details>
<summary><strong>Wrong Answers</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/wrong-answers/{course_id}` | GET | List wrong answers |
| `/api/wrong-answers/{id}/retry` | POST | Retry practice problem |
| `/api/wrong-answers/{id}/derive` | POST | Derive similar question |
| `/api/wrong-answers/{id}/diagnose` | POST | VCE error diagnosis |
| `/api/wrong-answers/{course_id}/stats` | GET | Wrong answer statistics |

</details>

<details>
<summary><strong>Agent Tasks</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tasks/` | GET | List agent tasks |
| `/api/tasks/submit` | POST | Submit new background task |
| `/api/tasks/{id}/approve` | POST | Approve task execution |
| `/api/tasks/{id}/reject` | POST | Reject task execution |
| `/api/tasks/{id}/cancel` | POST | Cancel task |
| `/api/tasks/{id}/resume` | POST | Resume cancelled task from checkpoint |
| `/api/tasks/{id}/retry` | POST | Retry failed task |

</details>

<details>
<summary><strong>Study Goals</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/goals/` | GET | List durable study goals |
| `/api/goals/` | POST | Create a study goal |
| `/api/goals/{id}` | PATCH | Update goal status, milestone, or next action |

</details>

<details>
<summary><strong>Notifications</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notifications/` | GET | List notifications |
| `/api/notifications/{id}/read` | POST | Mark as read |
| `/api/notifications/stream` | GET | SSE notification stream |

</details>

<details>
<summary><strong>Scraping</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scrape/sources` | GET | List scrape sources |
| `/api/scrape/sources` | POST | Create scrape source |
| `/api/scrape/sources/{id}` | PATCH | Update scrape source |
| `/api/scrape/sources/{id}` | DELETE | Delete scrape source |
| `/api/scrape/sources/{id}/scrape-now` | POST | Manual scrape trigger |
| `/api/scrape/auth/sessions` | GET | List auth sessions |
| `/api/scrape/auth/login` | POST | Save login credentials |

</details>

<details>
<summary><strong>Canvas LMS</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/canvas/login` | POST | Canvas authentication |
| `/api/canvas/sync` | POST | Sync courses + assignments |

</details>

<details>
<summary><strong>Evaluation</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/eval/routing` | POST | Test intent routing accuracy |
| `/api/eval/response` | POST | Test response quality |
| `/api/eval/retrieval` | POST | Test RAG retrieval relevance |

</details>

<details>
<summary><strong>Experiments (A/B Testing)</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/experiments/` | POST | Create experiment |
| `/api/experiments/` | GET | List experiments |
| `/api/experiments/{id}/analyze` | GET | Analyze results |
| `/api/experiments/{id}/end` | POST | End experiment |
| `/api/experiments/record-metric` | POST | Record metric event |
| `/api/experiments/my-variants` | GET | Get assigned variants |

</details>

<details>
<summary><strong>Auth (when AUTH_ENABLED=true)</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/register` | POST | Register new user |
| `/api/auth/login` | POST | Login (returns JWT) |
| `/api/auth/refresh` | POST | Refresh access token |

</details>

<details>
<summary><strong>Health</strong></summary>

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check (LLM status, providers, sandbox) |

</details>

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Next.js 16, React 19, Tailwind CSS v4 | App Router, modern UI |
| UI Components | shadcn/ui (Radix) | Accessible primitives |
| State | Zustand | Lightweight stores |
| Panels | react-resizable-panels | Draggable layout |
| Markdown | react-markdown + Mermaid + KaTeX | Rich content rendering |
| Charts | Recharts | Analytics visualization |
| PDF | react-pdf | In-app document viewer |
| Backend | FastAPI + Uvicorn | Async Python API |
| ORM | SQLAlchemy 2.0 (async) + Alembic | Database access + migrations |
| Database | PostgreSQL 17 + pgvector | Structured data + vector search |
| Cache | Redis 7 | Session cache |
| LLM | OpenAI / Anthropic / DeepSeek / Ollama + 7 more | 11 providers with circuit breaker |
| Agents | Custom orchestrator + BaseAgent + ReActMixin | 10 specialist agents |
| Memory | EverMemOS pattern (pgvector) | Encode → consolidate → retrieve |
| Spaced Rep | FSRS-4.5 (custom impl) | 30%+ more accurate than SM-2 |
| Parsing | Crawl4AI + trafilatura | Unified content extraction |
| Scraping | httpx → Scrapling → Playwright | 3-layer browser cascade |
| Workflows | LangGraph-style pipelines | 6 automated study workflows |
| Scheduling | APScheduler | Proactive reminders |
| Auth | python-jose + bcrypt | JWT tokens + password hashing |
| CI/CD | GitHub Actions | 4-stage pipeline |
| Containers | Docker Compose | PostgreSQL + Redis + API + Web |

## Testing

```bash
# Host-safe validation with explicit skip reporting
bash scripts/dev_local.sh verify-host

# Local default path: boot stack + run full validation script
bash scripts/dev_local.sh up
bash scripts/dev_local.sh verify

# Backend unit tests
cd apps/api && python -m pytest -q

# Backend syntax check
python3 -m compileall apps/api

# Frontend lint + build
cd apps/web && npm run lint && npm run build

# E2E smoke test (no real LLM needed)
API_BASE=http://127.0.0.1:8000 STRICT_LLM=0 bash scripts/smoke_test.sh

# Regression benchmark with retrieval fixture seeding
API_BASE=http://127.0.0.1:8000/api bash scripts/run_regression_benchmark.sh

# Real LLM integration test
export OPENAI_API_KEY=your_key   # or ANTHROPIC_API_KEY / DEEPSEEK_API_KEY
API_BASE=http://127.0.0.1:8000 bash scripts/llm_integration_test.sh

# Browser E2E (Playwright-managed ephemeral stack)
npx playwright test

# Browser E2E against the already running local stack
PLAYWRIGHT_USE_EXISTING_SERVER=1 \
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 \
PLAYWRIGHT_API_URL=http://127.0.0.1:8000/api \
npx playwright test tests/e2e/course-flow.spec.ts --project=chromium
```

### Test Suite
- **11 pytest files** — Unit tests, integration tests, regression tests (API routing, services, scraping, Canvas, code execution, ingestion, agent runtime)
- **21 Playwright E2E specs** — Dashboard, course flow, quiz, flashcards, notes, chat, settings, analytics, scenes, onboarding, review, progress, study plan, keyboard shortcuts, workspace layout, upload dialog, NL tuning, navigation, persistence, new project

### CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs 4 stages:
1. **checks** — pytest + compileall + ESLint + Next.js build
2. **api-smoke** — E2E smoke test with PostgreSQL + pgvector service container
3. **e2e-ui** — Playwright browser tests with Chromium
4. **llm-integration** — Real LLM API + browser E2E tests (only runs if API key secrets are configured)

## Roadmap

- Product agent roadmap: [docs/agent-product-roadmap.md](docs/agent-product-roadmap.md)
- Runtime remediation roadmap: [docs/agent-remediation-roadmap.md](docs/agent-remediation-roadmap.md)
- Agent eval and regression notes: [docs/agent-eval-regression.md](docs/agent-eval-regression.md)

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Cmd/Ctrl + 0 | Balanced layout |
| Cmd/Ctrl + 1 | Focus Notes panel |
| Cmd/Ctrl + 2 | Focus Quiz panel |
| Cmd/Ctrl + 3 | Focus Chat panel |

## Environment Variables

<details>
<summary><strong>Full configuration reference</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| **Database** | | |
| `DATABASE_URL` | `postgresql+asyncpg://opentutor:REDACTED_DEV_PASSWORD@localhost:5432/opentutor` | PostgreSQL connection string |
| **LLM Provider** | | |
| `LLM_PROVIDER` | `openai` | Primary provider: openai, anthropic, deepseek, ollama, openrouter, gemini, groq, vllm, lmstudio, textgenwebui, custom |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for primary provider |
| `LLM_MODEL_LARGE` | _(empty)_ | Model for teaching/planning agents (e.g. gpt-4o) |
| `LLM_MODEL_SMALL` | _(empty)_ | Model for preference/scene agents (e.g. gpt-4o-mini) |
| `LLM_REQUIRED` | `false` (`true` in default Docker Compose) | If true, fail startup when no LLM provider is available |
| **Cloud API Keys** | | |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key |
| `ANTHROPIC_API_KEY` | _(empty)_ | Anthropic API key |
| `DEEPSEEK_API_KEY` | _(empty)_ | DeepSeek API key |
| `OPENROUTER_API_KEY` | _(empty)_ | OpenRouter API key |
| `GEMINI_API_KEY` | _(empty)_ | Google Gemini API key |
| `GROQ_API_KEY` | _(empty)_ | Groq API key |
| **Local Inference** | | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `VLLM_BASE_URL` | `http://localhost:8000/v1` | vLLM server URL |
| `LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio server URL |
| `TEXTGENWEBUI_BASE_URL` | `http://localhost:5000/v1` | TextGen WebUI server URL |
| **Custom Endpoint** | | |
| `CUSTOM_LLM_API_KEY` | _(empty)_ | API key for custom OpenAI-compatible endpoint |
| `CUSTOM_LLM_BASE_URL` | _(empty)_ | Base URL for custom endpoint |
| `CUSTOM_LLM_MODEL` | _(empty)_ | Model name for custom endpoint |
| **Authentication** | | |
| `AUTH_ENABLED` | `false` | Enable JWT authentication (local mode when false) |
| `JWT_SECRET_KEY` | `change-me-in-production` | JWT signing secret (min 32 chars when auth enabled) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| **CORS** | | |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins, or `*` |
| **File Upload** | | |
| `UPLOAD_DIR` | `./uploads` | Upload file directory |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max upload size |
| `SCRAPE_FIXTURE_DIR` | _(empty)_ | Local-only HTML fixtures for deterministic URL scrape tests |
| **Runtime Bootstrap** | | |
| `APP_AUTO_CREATE_TABLES` | `false` | Deprecated. Startup is migration-first via `alembic upgrade head` |
| `APP_AUTO_SEED_SYSTEM` | `false` | Seed built-in templates + scenes |
| `APP_RUN_SCHEDULER` | `false` | Enable APScheduler |
| `APP_RUN_ACTIVITY_ENGINE` | `false` | Enable background task executor |
| **Code Sandbox** | | |
| `CODE_SANDBOX_BACKEND` | `auto` | auto, container, or process |
| `CODE_SANDBOX_RUNTIME` | `docker` | docker or podman |
| `CODE_SANDBOX_IMAGE` | `python:3.11-alpine` | Container image |
| `CODE_SANDBOX_TIMEOUT_SECONDS` | `5` | Execution timeout |

</details>

## Development Status

| Feature | Status | Notes |
|---------|--------|-------|
| Core learning interface | Fully implemented | Notes, quiz, flashcards, chat, progress, PDF viewer |
| Multi-agent system | Fully implemented | 10 agents, 2-stage routing, ReAct tools, orchestrator |
| Preference system | Fully implemented | 7-layer cascade, signal extraction, confidence scoring |
| Scene system | Fully implemented | 5 presets + custom, policy engine, snapshots |
| Content ingestion | Fully implemented | All formats (PDF/PPTX/DOCX/HTML/TXT/MD) + URL scraping |
| Memory pipeline | Fully implemented | EverMemOS 3-stage, 7 MemCell types, auto-consolidation |
| Hybrid search | Fully implemented | RRF (BM25 + tree + vector) + RAG-fusion |
| Authentication | Fully implemented | Optional via `AUTH_ENABLED` (JWT + bcrypt) |
| LLM providers | Fully implemented | 11 providers with circuit breaker + runtime config UI |
| Code sandbox | Fully implemented | Docker/Podman with process fallback |
| A/B experiments | Fully implemented | Create, assign variants, record metrics, analyze |
| Notifications | Fully implemented | SSE streaming + in-app notifications |
| PWA / Offline | Fully implemented | Service worker + manifest |
| Canvas LMS | Integration skeleton | Login + sync available, complex auth flows limited |

See [docs/SPEC.md](docs/SPEC.md) for the full specification.

## License

MIT
