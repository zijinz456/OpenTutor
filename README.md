# OpenTutor Zenus

[![CI](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml/badge.svg)](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)

A self-hosted personalized learning agent. Upload any educational material (PDF, PPTX, DOCX, URL) and OpenTutor Zenus creates an interactive multi-panel workspace with AI-generated notes, quizzes, flashcards, and a chat assistant that adapts to your preferences over time.

This repo is designed to run locally in `single_user` mode, in the same spirit as OpenClaw: no end-user sign-in flow, one local owner profile, and the backend auto-binds requests to that local owner account.

## Quick Start (Docker)

> **Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
# Optional: configure Ollama locally or add a cloud API key later
bash scripts/check_local_mode.sh --skip-api
bash scripts/dev_local.sh up --build
```

Open [http://localhost:3000](http://localhost:3000) once all services are healthy.

If `8000` or `3000` is already occupied on your machine, publish the stack on alternate ports:

```bash
API_PORT=38000 WEB_PORT=33000 bash scripts/dev_local.sh up --build
API_PORT=38000 WEB_PORT=33000 bash scripts/dev_local.sh beta-check
```

## Quick Start (Local Development)

> **Prerequisites:** Python 3.11 and Node 20+. PostgreSQL is optional now: the default host quickstart uses SQLite lite mode unless you explicitly set `DATABASE_URL` to PostgreSQL.

### One-command setup

**macOS / Linux:**
```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
bash scripts/check_local_mode.sh --skip-api
bash scripts/quickstart.sh
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/zijinz456/OpenTutor.git; cd OpenTutor
Copy-Item .env.example .env
.\scripts\quickstart.ps1
```

The script checks prerequisites, creates a virtualenv, bootstraps the configured local database, installs frontend packages, and starts both servers. By default the app prefers local Ollama; if no working provider is available it falls back to mock responses for development only.

Host quickstart behavior:

- Leave `DATABASE_URL` blank to use SQLite at `~/.opentutor/data.db`.
- Set `DATABASE_URL=postgresql+asyncpg://...` only if you want host PostgreSQL mode.
- For the most stable first run, prefer Docker or SQLite lite mode.

### Platform-specific prerequisites

| Tool | macOS | Ubuntu / Debian | Fedora | Windows |
|------|-------|-----------------|--------|---------|
| Python 3.11 | `brew install python@3.11` | `sudo apt install python3.11 python3.11-venv` | `sudo dnf install python3.11` | [python.org](https://www.python.org/downloads/) |
| Node.js 20+ | `brew install node` | [nodesource.com](https://nodesource.com/) | `sudo dnf install nodejs` | [nodejs.org](https://nodejs.org/) |
| PostgreSQL 16+ (optional) | `brew install postgresql@16` | `sudo apt install postgresql` | `sudo dnf install postgresql-server` | [postgresql.org](https://www.postgresql.org/download/windows/) |
| pgvector (optional) | `brew install pgvector` | [build from source](https://github.com/pgvector/pgvector#linux) | [build from source](https://github.com/pgvector/pgvector#linux) | [pgvector Windows](https://github.com/pgvector/pgvector#windows) |

### Manual setup (any platform)

```bash
# API
cd apps/api
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-core.txt
cp ../../.env.example .env       # edit .env with your API keys
uvicorn main:app --reload --port 8000

# Web (separate terminal)
cd apps/web
npm install
npm run dev
```

Install `requirements-full.txt` when you need browser-based Canvas login/scraping,
Google or Notion integrations, MCP, Anki/Calendar export, or CI/Docker parity.
`requirements.txt` remains as a backward-compatible alias to the full dependency set.
The Docker local stack also defaults to the core layer; set
`API_PYTHON_REQUIREMENTS=requirements-full.txt` if you want full container parity.
When the Docker API uses a host-run Ollama or LM Studio server, compose now routes
to `host.docker.internal` automatically. Override with `DOCKER_OLLAMA_BASE_URL`,
`DOCKER_LMSTUDIO_BASE_URL`, `DOCKER_VLLM_BASE_URL`, or
`DOCKER_TEXTGENWEBUI_BASE_URL` if your local runtime lives elsewhere.

If you want PostgreSQL instead of the default SQLite lite mode:

```bash
createdb opentutor
psql opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
cd apps/api
python -m alembic upgrade head
```

Open [http://localhost:3000](http://localhost:3000).

There is intentionally no normal end-user login page in the default local setup. If requests start failing with auth-like symptoms, check `.env` first and run `bash scripts/check_local_mode.sh`.

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
| **Database** | PostgreSQL 17 + pgvector, SQLite compatibility path, Redis 7 optional |
| **LLM** | Multi-provider (OpenAI, Anthropic, DeepSeek, Ollama, OpenRouter, Gemini, Groq, vLLM, LM Studio, TextGen WebUI, or any OpenAI-compatible endpoint) |
| **Agents** | 6 specialist agents (Teaching, Exercise, Planning, Review, Preference, Scene) + 2-stage intent routing + LangGraph workflows |
| **Search** | Hybrid keyword + vector search, RAG Fusion |
| **Testing** | Playwright (E2E), pytest (unit/integration) |
| **CI/CD** | GitHub Actions (3-stage: checks, smoke, LLM integration) |
| **Deployment** | Docker Compose (`AUTH_ENABLED=false`, `DEPLOYMENT_MODE=single_user`, strict container sandbox by default) |

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

Default local configuration prefers Ollama:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b
OLLAMA_BASE_URL=http://localhost:11434
```

You can also point the app at a cloud provider. Supports model size routing where agents automatically pick large or small models based on their role:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_MODEL_LARGE=gpt-4o          # for teaching/planning agents
LLM_MODEL_SMALL=gpt-4o-mini     # for preference/scene agents
```

If you do not configure a working provider, health will report `mock_fallback`. That mode is useful for UI development and smoke testing, but not for a local beta where chat, notes, quiz generation, flashcards, and planning should actually work.

For cloud LLMs:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...
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
| `LLM_PROVIDER` | `ollama` | LLM provider to use |
| `LLM_MODEL` | `llama3.2:3b` | Model name |
| `DATABASE_URL` | empty (`SQLite` fallback) | Leave blank for SQLite lite mode, or set a PostgreSQL connection string |
| `AUTH_ENABLED` | `false` | Keep `false` for the default local deployment path |
| `DEPLOYMENT_MODE` | `single_user` | Keep `single_user` for this repo's intended local mode |
| `APP_AUTO_CREATE_TABLES` | `true` | Auto-create DB tables on startup |
| `APP_AUTO_SEED_SYSTEM` | `true` | Seed templates, preset scenes, and demo data on startup |
| `APP_RUN_ACTIVITY_ENGINE` | `false` | Run the background durable-task worker in-process |
| `CODE_SANDBOX_BACKEND` | `auto` | Prefer container sandbox when Docker/Podman is available, otherwise fail over according to runtime policy |
| `MCP_ENABLED` | `false` | Enable external MCP server mounts and tool loading |
| `PLUGIN_SYSTEM_ENABLED` | `false` | Enable the pluggy plugin system on startup |

## Scripts

```bash
scripts/dev_local.sh up          # Start the full stack with docker compose or docker-compose
scripts/dev_local.sh check-local-mode  # Verify .env and the running API are still in local single-user mode
scripts/dev_local.sh beta-check  # Verify the running stack is ready for the local single-user beta
scripts/dev_local.sh verify      # Run smoke + integration + E2E tests
scripts/dev_local.sh down        # Stop the stack
scripts/dev_local.sh reset       # Stop and remove volumes
scripts/check_local_mode.sh      # Standalone local-mode sanity check
scripts/smoke_test.sh            # Quick API smoke test
```

See [docs/local-single-user.md](docs/local-single-user.md) for the local-only deployment contract and common failure modes.

## Local Beta Gate

For the technical-user local single-user beta, the minimum release gate is:

```bash
bash scripts/check_local_mode.sh --skip-api
bash scripts/dev_local.sh up --build
bash scripts/dev_local.sh beta-check
```

`beta-check` fails unless the running stack is in local single-user mode, the schema is ready, and a real LLM provider is reachable.
When Docker is running, the verification scripts now auto-detect the compose-published API and web ports.

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
