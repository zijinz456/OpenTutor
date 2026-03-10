<div align="center">

<img src="https://img.icons8.com/3d-fluency/94/graduation-cap.png" alt="OpenTutor Logo" width="80" />

# OpenTutor

**Your self-hosted AI learning platform.**<br/>
Upload any material — get notes, quizzes, flashcards, and an AI tutor that adapts to you.

[![License](https://img.shields.io/github/license/zijinz456/OpenTutor?style=flat-square&labelColor=black)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=black)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=black)](https://nextjs.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white&labelColor=black)](https://www.docker.com/)

**English** | [中文](./README.zh-CN.md)

</div>

<!-- Replace with actual screenshot when available -->
<!-- <p align="center"><img src="docs/assets/screenshot.png" alt="OpenTutor Screenshot" width="800" /></p> -->

## What is OpenTutor?

Drop in a PDF, and within 30 seconds you have structured notes, flashcards, quizzes, and an AI tutor that adapts to you. It builds a personal knowledge graph of what you know, tracks what you're forgetting, and proactively reminds you to review — all running locally, completely free.

```
Upload → AI Teaches → You Practice → AI Remembers → AI Reminds → Repeat
```

## Features

- **30-Second Ingestion** — Upload PDF, DOCX, PPTX, or paste a URL. Get structured notes, AI-generated flashcards, and quiz questions.

- **AI Tutor with Source Citations** — Every answer cites the original material. Adapts depth based on behavioral signals (fatigue, error patterns, message brevity).

- **Block-Based Adaptive Workspace** — 12 composable learning blocks (notes, quiz, flashcards, knowledge graph, study plan, analytics, etc). The system progressively unlocks features based on your learning behavior and suggests layout changes via AI.

- **Knowledge Graph (LOOM)** — Tracks concept mastery, prerequisite relationships, and weak areas. *Experimental — active development.*

- **Spaced Repetition (FSRS 4.5 + LECTOR)** — FSRS scheduling for flashcards. LECTOR adds semantic review prioritization based on knowledge graph relationships. *LECTOR is experimental.*

- **Proactive Review Reminders** — Checks for concepts at risk of being forgotten and sends in-app notifications.

- **Quiz System** — 7 question types: MCQ, short answer, fill-in-blank, true/false, matching, ordering, coding. Wrong-answer tracking with diagnostic feedback.

- **Canvas LMS Integration** — Import courses, modules, assignments, and files directly from Canvas.

- **10+ LLM Providers** — OpenAI, Anthropic, DeepSeek, Ollama, Gemini, Groq, vLLM, LM Studio, OpenRouter, or any OpenAI-compatible endpoint. Local-first with Ollama by default.

- **Self-Hosted & Private** — Runs entirely on your machine. No data leaves your environment. Single-user mode by default.

## Beta Scope (Current Release)

- **Stable path (recommended):** local single-user mode, course/content ingestion, chat tutoring, core quiz/notes/review flows.
- **Experimental path:** LOOM knowledge graph, LECTOR semantic review priority, advanced autonomous agent behaviors.
- **Non-default integrations:** messaging channels, external tool side effects, and some automation stacks require extra setup and are not part of the default quickstart success criteria.

## Quick Start

### Supported Host Platforms (Beta)

| Platform | Status |
|---|---|
| macOS (Apple Silicon / Intel) | ✅ Supported |
| Linux (Ubuntu 22.04+) | ✅ Supported |
| Windows | ⚠️ Not a first-class target in this beta cycle |

### Minimum Prerequisites

- Python 3.11
- Node.js 20+
- Bash 3.2+ (`bash --version`)
- `curl`
- Docker Desktop / Docker Engine (optional, only for containerized flow)

### Expected First-Run Time

- One-command local: ~10-30 minutes (depends on network and npm/pip cache)
- Docker: ~8-25 minutes (depends on image build cache)

### Docker (recommended)

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
docker compose up -d --build
```

### One-Command Local

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
bash scripts/quickstart.sh
```

> Uses SQLite by default — no PostgreSQL needed. The script handles Python venv, npm install, DB setup, and starts both servers.
> Optional custom ports: `API_PORT=38000 WEB_PORT=33000 bash scripts/quickstart.sh`
> If quickstart fails, run `bash scripts/check_local_mode.sh --env-file .env --skip-api` and then check [docs/troubleshooting.md](docs/troubleshooting.md).

### Manual

```bash
# Backend
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-core.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd apps/web && npm install && npm run dev
```

Visit [http://localhost:3001](http://localhost:3001).

## LLM Configuration

Default: local Ollama. Switch to any provider by editing `.env`:

```bash
# Local (free)
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b

# Cloud
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...

# Multi-size routing (optional)
LLM_MODEL_LARGE=gpt-4o          # Teaching, planning
LLM_MODEL_SMALL=gpt-4o-mini     # Classification, extraction
```

See [.env.example](.env.example) for the full list of supported providers and options.

## Architecture

```
OpenTutor/
├── apps/
│   ├── api/              # FastAPI backend
│   │   ├── routers/           # 23 API route modules
│   │   ├── models/            # 24 SQLAlchemy ORM models
│   │   ├── services/
│   │   │   ├── agent/              # 3 specialist agents + orchestrator
│   │   │   ├── ingestion/          # Content processing pipeline
│   │   │   ├── llm/                # Multi-provider LLM router
│   │   │   ├── search/             # Hybrid keyword + vector RAG
│   │   │   ├── spaced_repetition/  # FSRS scheduler + flashcards
│   │   │   ├── learning_science/   # BKT, difficulty selection
│   │   │   ├── loom.py             # Knowledge graph (experimental)
│   │   │   ├── lector.py           # Semantic review (experimental)
│   │   │   └── cognitive_load.py   # Behavioral signal analysis
│   │   └── alembic/           # Database migrations
│   └── web/              # Next.js 16 frontend
│       └── src/
│           ├── app/                # 13 pages (App Router)
│           ├── components/         # 84 React components
│           ├── store/              # Zustand state stores
│           └── lib/                # API client, block system, i18n
├── tests/                # pytest + Playwright E2E
└── scripts/              # Dev, CI, deployment
```

### Agent System

3 specialist agents coordinated by an intent-routing orchestrator:

| Agent | Role |
|-------|------|
| **Tutor** | Teaches with adaptive depth, Socratic questioning, source citations |
| **Planner** | Study plans, goal tracking, deadline management |
| **Layout** | Workspace configuration based on activity context |

Agents use a ReAct tool loop with access to content search, quiz generation, flashcard creation, web search, and code execution.

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Zustand, shadcn/ui |
| **Backend** | FastAPI, Python 3.11+, Pydantic 2, SQLAlchemy 2 (async), Alembic |
| **Database** | SQLite (aiosqlite, local-first) |
| **Learning Science** | FSRS 4.5, BKT, LECTOR (experimental), LOOM (experimental), Cognitive Load Theory |
| **CI/CD** | GitHub Actions, Docker Compose, Playwright |

## Research

OpenTutor builds on these papers:

| Paper | What We Use |
|-------|-------------|
| [LECTOR](https://arxiv.org/abs/2508.03275) (arxiv 2025) | Semantic spaced repetition via knowledge graph relationships |
| [LOOM](https://arxiv.org/abs/2511.21037) (arxiv 2025) | Dynamic learner memory graph for concept mastery tracking |
| [Cognitive Load + DKT](https://www.nature.com/articles/s41598-025-10497-x) (Nature 2025) | Behavioral signals for real-time difficulty adaptation |
| [FSRS 4.5](https://github.com/open-spaced-repetition/fsrs4.5) | Optimized free spaced repetition scheduling |

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.
For release readiness, use [docs/beta-release-checklist.md](docs/beta-release-checklist.md).
Current stabilization sprint execution plan: [docs/github-beta-sprint-plan.md](docs/github-beta-sprint-plan.md).
Final 2-5 day closeout runbook: [docs/release-closeout-runbook.md](docs/release-closeout-runbook.md).

```bash
# Run tests
python -m pytest tests/ -q -k "not llm_router"

# E2E tests (requires running stack)
npx playwright test
```

## License

[MIT](LICENSE)

---

<div align="center">

If OpenTutor helps your learning, consider giving it a ⭐

</div>
