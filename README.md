# OpenTutor

[![CI](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml/badge.svg)](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)

**Your learning WordPress.** Upload any material, get a complete AI-powered learning platform — locally, for free.

OpenTutor is a self-hosted personal learning agent. Drop in a PDF, and within 30 seconds you have structured notes, flashcards, quizzes, and an AI tutor that adapts to you. It remembers what you know, what you're forgetting, and proactively reminds you to review.

## Why OpenTutor?

|  | NotebookLM | HyperKnow | Anki | **OpenTutor** |
|--|------------|-----------|------|---------------|
| Understands your materials | Yes | Yes | No | **Yes** |
| Generates practice problems | No | Limited | No | **Yes (7 types)** |
| Tracks what you're forgetting | No | No | Yes | **Yes (semantic)** |
| Reminds you to review | No | No | Manual | **Automatic** |
| Runs locally | No | No | Yes | **Yes** |
| Free | Limited | $12/mo | Yes | **Yes** |

## The Core Loop

```
Upload → AI Teaches → You Practice → AI Remembers → AI Reminds → Repeat
```

Every feature exists to make this loop faster, smarter, and more personalized.

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
bash scripts/dev_local.sh up --build
```

Open [http://localhost:3000](http://localhost:3000).

### Local Development

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
bash scripts/quickstart.sh
```

Uses SQLite by default — no PostgreSQL needed to get started. The script handles Python venv, npm install, DB setup, and starts both servers.

### Manual Setup

```bash
# Backend
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-core.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd apps/web
npm install && npm run dev
```

## 6 Core Features

### 1. Upload → 30-Second Results
Drop a PDF, DOCX, PPTX, or URL. Within 30 seconds: structured content tree, AI-generated notes, flashcards, and quiz questions — all indexed and searchable.

### 2. AI Tutor with Source Citations
Every answer cites the original material: `[Source: Lecture_02.pdf]`. The tutor adapts its depth based on real-time cognitive load detection — simplifies when you're struggling, deepens when you're ready.

### 3. Smart Practice (LECTOR)
Not just spaced repetition — **semantic** spaced repetition. Based on [LECTOR (arxiv:2508.03275)](https://arxiv.org/abs/2508.03275):
- Reviews related concepts together, not in isolation
- Prioritizes weak prerequisites before dependent concepts
- Contrasts commonly confused concept pairs
- 7 question types: MCQ, short answer, fill-in-blank, true/false, matching, ordering, coding

### 4. AI Memory (LOOM Knowledge Graph)
Based on [LOOM (arxiv:2511.21037)](https://arxiv.org/abs/2511.21037). Every interaction updates a personal knowledge graph:
- What you know, what you don't, what you're forgetting
- Concept relationships: prerequisites, related topics, confusion pairs
- Mastery scores with FSRS-based stability tracking

### 5. Proactive Reminders (Heartbeat)
The AI doesn't wait for you — it checks every 6 hours:
- Which concepts are at risk of being forgotten?
- Any deadlines approaching?
- Sends in-app notifications: *"Your Chain Rule is decaying — do 2 quick problems?"*

### 6. Adaptive Difficulty (Cognitive Load Detection)
6 behavioral signals monitored in real-time:
- Session fatigue, error patterns, help-seeking frequency
- Message brevity, quiz performance trends, session length
- Automatically adjusts explanation depth and problem difficulty

## Architecture

```
OpenTutor/
├── apps/
│   ├── api/              # FastAPI backend (Python)
│   │   ├── routers/           # 22 API route modules
│   │   ├── models/            # 23 SQLAlchemy ORM models
│   │   ├── services/
│   │   │   ├── agent/              # 3 specialist agents + orchestrator
│   │   │   ├── ingestion/          # Content processing pipeline
│   │   │   ├── llm/                # Multi-provider LLM router
│   │   │   ├── search/             # Hybrid keyword + vector RAG
│   │   │   ├── spaced_repetition/  # FSRS scheduler + flashcards
│   │   │   ├── learning_science/   # BKT, difficulty selection
│   │   │   ├── scheduler/          # APScheduler background jobs
│   │   │   ├── loom.py             # Knowledge graph service
│   │   │   ├── lector.py           # Semantic review engine
│   │   │   └── cognitive_load.py   # Real-time load detection
│   │   └── alembic/           # Database migrations
│   └── web/              # Next.js 16 frontend
│       └── src/
│           ├── app/                # 6 pages (App Router)
│           ├── components/         # 63 React components
│           ├── store/              # Zustand state stores
│           └── lib/                # API client + utilities
├── tests/                # 23 Python + 23 Playwright E2E tests
└── scripts/              # Dev, CI, and deployment scripts
```

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Zustand, shadcn/ui |
| **Backend** | FastAPI, Python 3.11+, Pydantic 2, SQLAlchemy 2 (async), Alembic |
| **Database** | PostgreSQL + pgvector (production) or SQLite (development) |
| **LLM** | 10+ providers: OpenAI, Anthropic, DeepSeek, Ollama, Gemini, Groq, vLLM, LM Studio, OpenRouter, TextGen WebUI, or any OpenAI-compatible endpoint |
| **Learning Science** | FSRS 4.5, BKT, LECTOR, LOOM, cognitive load theory |
| **Testing** | pytest (unit/integration), Playwright (E2E) |
| **CI/CD** | GitHub Actions, Docker Compose |

## Agent System

3 specialist agents coordinated by an intent-routing orchestrator:

| Agent | Role |
|-------|------|
| **Tutor** | Teaches concepts with adaptive depth, Socratic questioning, source citations |
| **Planner** | Creates study plans, tracks goals, manages deadlines |
| **Layout** | Configures workspace panels based on activity context |

Agents use a ReAct tool loop with access to: content search, quiz generation, flashcard creation, web search, and code execution.

## LLM Configuration

Default: local Ollama. Works with any provider.

```bash
# Local (free)
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b

# Cloud
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...

# Multi-size routing
LLM_MODEL_LARGE=gpt-4o          # Teaching, planning
LLM_MODEL_SMALL=gpt-4o-mini     # Classification, extraction
```

## Canvas LMS Integration

Import courses directly from Canvas:

```bash
CANVAS_BASE_URL=https://canvas.university.edu
```

Login via browser session, then OpenTutor automatically pulls modules, files, assignments, and deadlines.

## API Endpoints

Key endpoints added in this version:

| Endpoint | Description |
|----------|-------------|
| `GET /api/notifications` | List in-app notifications (unread count + items) |
| `POST /api/notifications/{id}/read` | Mark notification as read |
| `GET /api/chat/greeting/{course_id}` | AI greeting with LOOM/LECTOR context |
| `GET /api/progress/courses/{id}/loom` | Knowledge graph (nodes, edges, mastery) |
| `GET /api/progress/courses/{id}/review-session` | LECTOR semantic review items |

## Background Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| Agenda Tick | Every 2h | Proactive agent loop (signals → tasks) |
| Heartbeat Review | Every 6h | LECTOR-powered forgetting detection + notifications |
| Smart Review Trigger | Every 4h | FSRS forgetting cost batching |
| Memory Consolidation | Every 6h | Dedup, decay, categorize memories |
| Scrape Refresh | Every 1h | Re-scrape enabled URLs |
| Weekly Prep | Monday 8am | Weekly study plan refresh |
| BKT Training | Saturday 3am | Retrain knowledge tracing parameters |

## Testing

```bash
# Unit + integration tests
python -m pytest tests/ -q -k "not llm_router"

# E2E tests (requires running stack)
npx playwright test

# Smoke test
bash scripts/smoke_test.sh
```

## Research Papers

OpenTutor implements ideas from:

- **LECTOR** — [LLM-Enhanced Concept-aware Tutoring and Optimized Review](https://arxiv.org/abs/2508.03275) — Semantic spaced repetition using knowledge graph relationships
- **LOOM** — [Learner-Oriented Ontology Memory](https://arxiv.org/abs/2511.21037) — Dynamic learner memory graph for concept tracking
- **Cognitive Load + DKT** — [Nature: s41598-025-10497-x](https://www.nature.com/articles/s41598-025-10497-x) — Behavioral signals for adaptive difficulty
- **FSRS 4.5** — Free Spaced Repetition Scheduler — Optimized interval scheduling

## License

MIT
