# OpenTutor Zenus

[![CI](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml/badge.svg)](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)

A self-hosted personalized learning agent. Upload any educational material (PDF, PPTX, DOCX, URL) and OpenTutor Zenus creates an interactive multi-panel workspace with AI-generated notes, quizzes, flashcards, and a chat assistant that adapts to your preferences over time.

The default local deployment mode is `single_user`: the first local account becomes the owner profile, durable tasks remain course-scoped, and the settings/health UI surfaces the active deployment mode and sandbox status explicitly.

## Quick Start (Docker)

> **Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
# Add at least one LLM API key to .env (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
bash scripts/dev_local.sh up --build
```

Open [http://localhost:3000](http://localhost:3000) once all services are healthy.

## Quick Start (Local Development)

> **Prerequisites:** Python 3.11, Node 20+, PostgreSQL 17 with pgvector extension, Redis 7+.

```bash
# Database
createdb opentutor
psql opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
redis-server

# API
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../../.env.example .env   # edit .env with your API keys
python -m alembic upgrade head
uvicorn main:app --reload --port 8000

# Web (separate terminal)
cd apps/web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Architecture

```
OpenTutor/
├── apps/
│   ├── api/          # FastAPI backend (Python 3.11)
│   │   ├── routers/       # 25 API route modules
│   │   ├── models/        # 28 SQLAlchemy ORM models
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   ├── services/      # Core business logic
│   │   │   ├── agent/          # Multi-agent system (6 specialists + orchestrator)
│   │   │   ├── workflow/       # LangGraph workflow engine
│   │   │   ├── ingestion/      # Content ingestion pipeline
│   │   │   ├── llm/            # Multi-provider LLM router
│   │   │   ├── search/         # Hybrid + RAG fusion search
│   │   │   ├── notification/   # Push notification system
│   │   │   └── ...
│   │   └── alembic/       # Database migrations
│   └── web/          # Next.js frontend (React 19 + TypeScript)
│       └── src/
│           ├── app/            # 7 pages (App Router)
│           ├── components/     # 33 React components
│           ├── store/          # Zustand state stores
│           └── lib/            # Utilities + API client
├── tests/
│   ├── e2e/          # 22 Playwright E2E specs
│   └── test_*.py     # 16 Python unit/integration tests
├── scripts/          # Dev, CI, and verification scripts
├── docs/             # Detailed specifications and roadmaps
└── docker-compose.yml
```

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Zustand, shadcn/ui, Radix UI |
| **Backend** | FastAPI, Python 3.11, Pydantic 2, SQLAlchemy 2 (async), Alembic |
| **Database** | PostgreSQL 17 + pgvector + Redis 7 |
| **LLM** | Multi-provider (OpenAI, Anthropic, DeepSeek, Ollama, OpenRouter, Gemini, Groq, vLLM, LM Studio, TextGen WebUI, or any OpenAI-compatible endpoint) |
| **Agents** | 6 specialist agents (Teaching, Exercise, Planning, Review, Preference, Scene) + 2-stage intent routing + LangGraph workflows |
| **Search** | Hybrid keyword + vector search, RAG Fusion |
| **Testing** | Playwright (E2E), pytest (unit/integration) |
| **CI/CD** | GitHub Actions (3-stage: checks, smoke, LLM integration) |
| **Deployment** | Docker Compose (`DEPLOYMENT_MODE=single_user`, strict container sandbox by default) |

## Multi-Agent System

OpenTutor uses a swarm of 6 specialist agents coordinated by an orchestrator:

- **Teaching Agent** - Explains concepts with adaptive depth and scaffolding
- **Exercise Agent** - Generates practice problems calibrated to difficulty
- **Planning Agent** - Creates study plans and schedules
- **Review Agent** - Analyzes wrong answers and identifies knowledge gaps
- **Preference Agent** - Extracts and applies learning style preferences
- **Scene Agent** - Manages contextual study modes

A 2-stage router (keyword heuristic + LLM classifier) routes each user message to the appropriate agent. Agents use a ReAct tool loop with access to education tools, code execution sandbox, and content search.

## Scene System

5 preset learning scenes that adjust agent behavior, UI layout, and workflow:

| Scene | Purpose |
|-------|---------|
| `study_session` | General learning and concept exploration |
| `exam_prep` | Focused exam preparation and timed practice |
| `assignment` | Guided homework assistance |
| `review_drill` | Wrong answer analysis and targeted review |
| `note_organize` | Note summarization and organization |

## LLM Configuration

Set `LLM_PROVIDER` and the corresponding API key in `.env`. Supports model size routing where agents automatically pick large or small models based on their role:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_MODEL_LARGE=gpt-4o          # for teaching/planning agents
LLM_MODEL_SMALL=gpt-4o-mini     # for preference/scene agents
```

For local LLMs (no API key needed):

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5
OLLAMA_BASE_URL=http://localhost:11434
```

## Key Features

- **Content ingestion** - Upload PDF, PPTX, DOCX, or scrape URLs. Automatic chunking, embedding, and indexing.
- **Interactive workspace** - Chat, notes, quiz, flashcards, progress, knowledge graph, and study plan panels.
- **Spaced repetition** - FSRS-based flashcard scheduling with forgetting curve forecasts.
- **Preference learning** - 7-layer preference cascade (temporary > course_scene > course > global_scene > global > template > system_default).
- **Canvas LMS integration** - Import courses, assignments, and materials from Canvas.
- **Push notifications** - Web Push API for study reminders and task updates.
- **Multi-channel messaging** - WhatsApp and iMessage support via webhooks.
- **Code sandbox** - Secure containerized code execution (Docker/Podman).
- **A/B experiments** - Built-in experimentation engine for testing agent configurations.

## Environment Variables

See [.env.example](.env.example) for the full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openai` | LLM provider to use |
| `LLM_MODEL` | `gpt-4o-mini` | Model name |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `AUTH_ENABLED` | `false` | Enable JWT authentication |
| `DEPLOYMENT_MODE` | `single_user` | Deployment mode (`single_user` or `multi_user`) |
| `APP_AUTO_CREATE_TABLES` | `false` | Auto-create DB tables on startup |
| `APP_AUTO_SEED_SYSTEM` | `false` | Seed templates and preset scenes |
| `APP_RUN_ACTIVITY_ENGINE` | `false` | Run the background durable-task worker in-process |
| `CODE_SANDBOX_BACKEND` | `container` | Secure sandbox backend (`process` only for pytest or explicit local override) |

## Scripts

```bash
scripts/dev_local.sh up          # Start the full stack with docker compose or docker-compose
scripts/dev_local.sh verify      # Run smoke + integration + E2E tests
scripts/dev_local.sh down        # Stop the stack
scripts/dev_local.sh reset       # Stop and remove volumes
scripts/smoke_test.sh            # Quick API smoke test
```

## Testing

```bash
# Python unit/integration tests
python -m pytest tests/test_services.py tests/test_api_unit_basics.py -q

# E2E tests (requires running stack)
npx playwright test

# Single E2E spec
npx playwright test tests/e2e/course-flow.spec.ts
```

## CI Pipeline

GitHub Actions runs a 3-stage pipeline on every push:

1. **Checks** - Linting, type checking, unit tests
2. **Smoke** - API smoke tests against a PostgreSQL + pgvector service container
3. **LLM Integration** - Real LLM provider tests (conditional, requires `ENABLE_LLM_TESTS=true`)

## License

MIT
