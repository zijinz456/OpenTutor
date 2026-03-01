# OpenTutor

> **"Give me any learning material, I'll turn it into a personalized learning website that understands you better the more you use it."**

A self-hosted personalized learning agent. Upload any educational material (PDF, PPTX, DOCX, URL), and OpenTutor creates an interactive multi-panel learning experience with AI notes, quizzes, flashcards, and a chat assistant — all adapting to your preferences over time.

## Features

### Multi-Panel Learning Interface
- **AI Notes Panel** — Auto-restructured content with Mermaid diagrams + KaTeX math rendering
- **Interactive Quiz Panel** — Auto-extracted questions (7 types: MCQ, T/F, short answer, multi-answer, fill-in-blank, matching, ordering) with real-time color feedback
- **FSRS Flashcard Panel** — Spaced repetition flashcards with scheduling 30%+ more accurate than Anki's SM-2
- **AI Chat Assistant** — Course material RAG with SSE streaming responses
- **Knowledge Graph** — D3-powered visual topic map with mastery coloring
- **Learning Progress Tracker** — Course → chapter → knowledge point granularity

### Preference Learning (Core Innovation)
- **7-layer preference cascade** — Git Config-style resolution: system_default → template → global → global_scene → course → course_scene → temporary (last wins)
- **Behavior-based signal extraction** — Implicit + explicit signals from conversations (~95% return NONE = no noise)
- **Confidence scoring** — `base × frequency × recency × consistency` with 90-day exponential decay
- **NL preference tuning** — Say "switch to table format" or "make it more concise" and it changes immediately
- **Scene detection** — Auto-detects 6 learning contexts (assignment, exam review, weekly prep, etc.)

### Content Ingestion
- **Multi-format upload** — PDF, PPTX, DOCX, HTML, TXT, Markdown
- **URL scraping** — 3-layer browser cascade (httpx → Scrapling → Playwright) for any website including authenticated content
- **7-step ingestion pipeline** — MIME detect → content extract → LLM classify → SHA-256 dedup → fuzzy match → store → dispatch
- **Canvas LMS integration** — Sync courses, assignments, and submissions

### AI & Search
- **Multi-model LLM support** — OpenAI, Anthropic, DeepSeek, Ollama with circuit breaker + progressive cooldown fallback
- **RRF Hybrid Search** — Reciprocal Rank Fusion combining keyword (BM25), tree hierarchy, and vector search
- **EverMemOS Memory Pipeline** — 3-stage encode → consolidate → retrieve with pgvector embeddings

### Workflows
- **6 LangGraph-style pipelines** — Semester init, weekly prep, assignment analysis, study sessions, wrong answer review, exam prep
- **5 built-in learning templates** — STEM, Humanities, Language, Visual, Quick Review
- **Proactive scheduling** — APScheduler for reminders and FSRS review nudges

### i18n
- Chinese / English interface with 80+ translation keys

## Quick Start

### Docker (Recommended)

```bash
# 1. Clone
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor

# 2. Configure
cp .env.example .env
# Edit .env: add your API key (at least one of OPENAI_API_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY)

# 3. Start
docker compose up -d

# 4. Access
# Backend API: http://localhost:8000
# Frontend:    http://localhost:3000
```

The default compose stack now starts `db`, `redis`, `api`, and `web`, and the
API container auto-creates tables, seeds built-in system data, and runs the
background activity engine so queued agent tasks can execute automatically.

### Manual Setup

```bash
# Prerequisites: PostgreSQL 17 with pgvector, Redis, Python 3.11 (tiktoken requires <3.14), Node.js 20+

# Database
docker compose up -d db redis   # or install PostgreSQL + pgvector + Redis manually

# Backend
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../../.env.example .env   # then edit with your API keys
uvicorn main:app --reload    # http://localhost:8000

# Frontend (new terminal)
cd apps/web
npm install
npm run dev                  # http://localhost:3000
```

### Prerequisites
- Docker + Docker Compose (for Docker setup)
- Python 3.11 (for manual setup — tiktoken requires <3.14)
- Node.js 20+ (for frontend)
- PostgreSQL 17 with pgvector extension
- Redis 7+
- At least one LLM API key (OpenAI / Anthropic / DeepSeek / Ollama)

## Project Structure

```
OpenTutor/
├── apps/
│   ├── api/                        # FastAPI backend
│   │   ├── main.py                 # Entry point with lifespan management
│   │   ├── config.py               # Environment configuration (pydantic-settings)
│   │   ├── database.py             # SQLAlchemy async engine + session factory
│   │   ├── models/                 # 10 SQLAlchemy ORM models
│   │   ├── routers/                # 11 API endpoint modules
│   │   ├── schemas/                # Pydantic request/response models
│   │   ├── services/               # Core service layer
│   │   │   ├── llm/                #   Multi-provider LLM with circuit breaker
│   │   │   ├── ingestion/          #   7-step content ingestion pipeline
│   │   │   ├── parser/             #   PDF, quiz, notes, URL parsers
│   │   │   ├── preference/         #   7-layer cascade engine + signal extraction
│   │   │   ├── memory/             #   EverMemOS 3-stage memory pipeline
│   │   │   ├── search/             #   RRF hybrid search (keyword + tree + vector)
│   │   │   ├── spaced_repetition/  #   FSRS-4.5 algorithm implementation
│   │   │   ├── workflow/           #   6 LangGraph-style pipelines
│   │   │   ├── browser/            #   3-layer automation cascade
│   │   │   ├── knowledge/          #   Knowledge graph builder
│   │   │   ├── progress/           #   Learning progress tracker
│   │   │   ├── scheduler/          #   APScheduler for proactive reminders
│   │   │   └── templates/          #   5 built-in learning templates
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── web/                        # Next.js 16 frontend
│       ├── src/
│       │   ├── app/                # App Router (6 routes)
│       │   │   ├── page.tsx        #   Dashboard
│       │   │   ├── course/[id]/    #   Main learning interface (5 panels)
│       │   │   ├── onboarding/     #   5-step preference setup
│       │   │   ├── new/            #   4-step project creation
│       │   │   └── settings/       #   User settings
│       │   ├── components/         # 38 React components
│       │   │   ├── ui/             #   shadcn/ui primitives
│       │   │   ├── course/         #   Notes, quiz, flashcard, PDF panels
│       │   │   ├── chat/           #   SSE streaming chat
│       │   │   ├── workspace/      #   Activity bar, breadcrumbs, status bar
│       │   │   └── preference/     #   Onboarding wizard, confirm dialog
│       │   ├── store/              # Zustand state (course, chat)
│       │   └── lib/                # API client, i18n, utilities
│       └── package.json
│
├── .github/workflows/ci.yml       # 3-stage CI: checks → smoke → LLM integration
├── tests/                          # pytest unit tests
├── scripts/                        # Smoke test + LLM integration test scripts
├── docs/                           # Detailed specification
├── docker-compose.yml              # PostgreSQL + Redis + FastAPI
└── .env.example                    # Environment variable template
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Next.js 16 Frontend (React 19 + shadcn/ui + Tailwind)   │
│  Zustand state │ react-resizable-panels │ Mermaid + KaTeX │
└───────────────────────────┬──────────────────────────────┘
                            │ REST API + SSE
┌───────────────────────────▼──────────────────────────────┐
│  FastAPI Backend                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Router Layer (11 routers)                            │ │
│  │  upload │ chat │ courses │ preferences │ quiz        │ │
│  │  notes │ flashcards │ workflows │ progress │ canvas  │ │
│  └────────────────────────┬────────────────────────────┘ │
│  ┌────────────────────────▼────────────────────────────┐ │
│  │ Service Layer (11 modules)                           │ │
│  │  llm/router ──── circuit breaker + multi-provider    │ │
│  │  ingestion ───── 7-step classification pipeline      │ │
│  │  preference ──── 7-layer cascade + signal extraction │ │
│  │  memory ──────── EverMemOS encode→consolidate→retrieve│ │
│  │  search ──────── RRF hybrid (keyword+tree+vector)    │ │
│  │  spaced_rep ──── FSRS-4.5 from scratch               │ │
│  │  workflow ────── 6 LangGraph-style pipelines         │ │
│  │  browser ─────── httpx → Scrapling → Playwright      │ │
│  │  knowledge ───── topic graph builder                 │ │
│  │  progress ────── mastery tracker                     │ │
│  │  scheduler ───── APScheduler proactive reminders     │ │
│  └────────────────────────┬────────────────────────────┘ │
│  ┌────────────────────────▼────────────────────────────┐ │
│  │ Data Layer (SQLAlchemy async + Pydantic)             │ │
│  │  10 ORM models │ UUID PKs │ pgvector embeddings      │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────┬─────────────────┬──────────────────┬──────────┘
           ▼                 ▼                  ▼
    PostgreSQL 16       Redis 7            LLM APIs
    + pgvector         (caching)        (OpenAI/Anthropic/
                                        DeepSeek/Ollama)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/content/upload` | POST | Upload file (PDF/PPTX/DOCX/HTML/TXT/MD) |
| `/api/content/url` | POST | Scrape URL and ingest |
| `/api/chat/` | POST | SSE streaming chat with RAG |
| `/api/courses/` | GET/POST | Course CRUD |
| `/api/courses/{id}/content-tree` | GET | Hierarchical content tree |
| `/api/quiz/extract` | POST | Generate quiz from content |
| `/api/quiz/submit` | POST | Submit quiz answer + feedback |
| `/api/notes/generate` | POST | AI notes generation (5 formats) |
| `/api/preferences/` | GET/POST | View/update preferences |
| `/api/preferences/resolve` | GET | Resolve 7-layer cascade |
| `/api/flashcards/generate` | POST | Generate FSRS flashcards |
| `/api/flashcards/review` | POST | Review flashcard (FSRS rating 1-4) |
| `/api/workflows/semester-init` | POST | Semester setup pipeline |
| `/api/workflows/weekly-prep` | GET | Weekly study plan |
| `/api/workflows/assignment-analysis` | POST | Assignment analysis |
| `/api/workflows/wrong-answer-review` | GET | Wrong answer review |
| `/api/workflows/exam-prep` | POST | Exam preparation |
| `/api/progress/courses/{id}` | GET | Learning progress |
| `/api/progress/templates` | GET | Built-in learning templates |
| `/api/progress/courses/{id}/knowledge-graph` | GET | Knowledge graph data |
| `/api/canvas/sync` | POST | Sync from Canvas LMS |
| `/api/health` | GET | Health check |

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Next.js 16, React 19, Tailwind CSS v4 | App Router, modern UI |
| UI Components | shadcn/ui (Radix) | Accessible primitives |
| State | Zustand | Lightweight stores |
| Panels | react-resizable-panels | Draggable layout |
| Markdown | react-markdown + Mermaid + KaTeX | Rich content rendering |
| Backend | FastAPI + Uvicorn | Async Python API |
| ORM | SQLAlchemy 2.0 (async) + Alembic | Database access + migrations |
| Database | PostgreSQL 16 + pgvector | Structured data + vector search |
| Cache | Redis 7 | Session cache |
| LLM | OpenAI / Anthropic / DeepSeek / Ollama | Multi-provider with circuit breaker |
| Memory | EverMemOS pattern (pgvector) | Encode → consolidate → retrieve |
| Spaced Rep | FSRS-4.5 (custom impl) | 30%+ more accurate than SM-2 |
| Parsing | Marker + trafilatura | PDF/URL extraction |
| Scraping | httpx → Scrapling → Playwright | 3-layer browser cascade |
| Workflows | LangGraph-style pipelines | 6 automated study workflows |
| Scheduling | APScheduler | Proactive reminders |
| CI/CD | GitHub Actions | 3-stage pipeline |
| Containers | Docker Compose | PostgreSQL + Redis + API |

## Testing

```bash
# Backend unit tests
cd apps/api && python -m pytest -q

# Backend syntax check
python3 -m compileall apps/api

# Frontend lint + build
cd apps/web && npm run lint && npm run build

# E2E smoke test (no real LLM needed)
API_BASE=http://127.0.0.1:8000 STRICT_LLM=1 bash scripts/smoke_test.sh

# Real LLM integration test
export OPENAI_API_KEY=your_key   # or ANTHROPIC_API_KEY / DEEPSEEK_API_KEY
API_BASE=http://127.0.0.1:8000 bash scripts/llm_integration_test.sh
```

### CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs 3 stages:
1. **checks** — pytest + compileall + ESLint + Next.js build
2. **api-smoke** — E2E smoke test with PostgreSQL + pgvector service container
3. **llm-integration** — Real LLM API tests (only runs if API key secrets are configured)

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Cmd/Ctrl + 0 | Balanced layout |
| Cmd/Ctrl + 1 | Focus Notes panel |
| Cmd/Ctrl + 2 | Focus Quiz panel |
| Cmd/Ctrl + 3 | Focus Chat panel |

## Development Status

This project is under active development. Current state:
- **Core learning interface** — Functional (notes, quiz, flashcards, chat, progress)
- **Preference system** — Fully implemented (7-layer cascade, signal extraction, confidence)
- **Content ingestion** — Working for all supported formats
- **Memory pipeline** — Skeleton implemented, embeddings partially mocked
- **Hybrid search** — RRF framework in place, BM25 simplified
- **Canvas LMS** — Integration skeleton
- **Authentication** — Not yet implemented (single local user mode)

See [docs/SPEC.md](docs/SPEC.md) for the full specification.

## License

MIT
