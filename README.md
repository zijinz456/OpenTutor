<div align="center">

<img src="https://img.icons8.com/3d-fluency/94/graduation-cap.png" alt="OpenTutor Logo" width="80" />

# OpenTutor

**Your self-hosted AI learning platform.**<br/>
Upload any material — get notes, quizzes, flashcards, and an AI tutor that remembers you.

[![CI](https://img.shields.io/github/actions/workflow/status/zijinz456/OpenTutor/ci.yml?branch=main&label=CI&logo=githubactions&logoColor=white&style=flat-square)](https://github.com/zijinz456/OpenTutor/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/zijinz456/OpenTutor?style=flat-square&labelColor=black)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=black)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=black)](https://nextjs.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white&labelColor=black)](https://www.docker.com/)

**English** | [中文](./README.zh-CN.md)

</div>

<!-- DEMO_SCREENSHOT_PLACEHOLDER: Replace with actual screenshot -->
<!-- <p align="center"><img src="docs/assets/screenshot.png" alt="OpenTutor Screenshot" width="800" /></p> -->

## What is OpenTutor?

Drop in a PDF, and within 30 seconds you have structured notes, flashcards, quizzes, and an AI tutor that adapts to you. It builds a personal knowledge graph of what you know, tracks what you're forgetting, and proactively reminds you to review — all running locally, completely free.

```
Upload → AI Teaches → You Practice → AI Remembers → AI Reminds → Repeat
```

<details>
<summary><kbd>Table of Contents</kbd></summary>

- [What is OpenTutor?](#what-is-opentutor)
- [Features](#features)
- [Quick Start](#quick-start)
- [LLM Configuration](#llm-configuration)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Research](#research)
- [Contributing](#contributing)
- [License](#license)

</details>

## Features

- 📄 **30-Second Ingestion** — Upload PDF, DOCX, PPTX, or paste a URL. Get a structured content tree, AI-generated notes, flashcards, and quiz questions — all indexed and searchable.

- 🎓 **AI Tutor with Source Citations** — Every answer cites the original material `[Source: Lecture_02.pdf]`. Adapts depth based on real-time cognitive load detection.

- 🧠 **Knowledge Graph (LOOM)** — Every interaction updates a personal knowledge graph: what you know, what you don't, what you're forgetting. Concept relationships, prerequisites, and confusion pairs — all tracked automatically.

- 🔁 **Semantic Spaced Repetition (LECTOR)** — Not just interval scheduling — reviews related concepts together, prioritizes weak prerequisites, and contrasts confused pairs. 7 question types: MCQ, short answer, fill-in-blank, true/false, matching, ordering, coding.

- 🔔 **Proactive Review Reminders** — Checks every 6 hours for concepts at risk of being forgotten. Sends in-app notifications: *"Your Chain Rule is decaying — do 2 quick problems?"*

- 📊 **Adaptive Difficulty** — 6 behavioral signals (fatigue, error patterns, help-seeking, message brevity, quiz performance, session length) dynamically adjust explanation depth and problem difficulty.

- 🔗 **Canvas LMS Integration** — Import courses, assignments, modules, and files directly from Canvas.

- 🤖 **10+ LLM Providers** — OpenAI, Anthropic, DeepSeek, Ollama, Gemini, Groq, vLLM, LM Studio, OpenRouter, or any OpenAI-compatible endpoint. Local-first with Ollama by default.

- 🔒 **Self-Hosted & Private** — Runs entirely on your machine. No data leaves your environment. Single-user mode by default — no sign-in needed.

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
bash scripts/dev_local.sh up --build
```

### One-Command Local

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
bash scripts/quickstart.sh
```

> Uses SQLite by default — no PostgreSQL needed. The script handles Python venv, npm install, DB setup, and starts both servers.

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
│   │   ├── routers/           # 22 API route modules
│   │   ├── models/            # 23 SQLAlchemy ORM models
│   │   ├── services/
│   │   │   ├── agent/              # 3 specialist agents + orchestrator
│   │   │   ├── ingestion/          # Content processing pipeline
│   │   │   ├── llm/                # Multi-provider LLM router
│   │   │   ├── search/             # Hybrid keyword + vector RAG
│   │   │   ├── spaced_repetition/  # FSRS scheduler + flashcards
│   │   │   ├── learning_science/   # BKT, difficulty selection
│   │   │   ├── loom.py             # LOOM knowledge graph
│   │   │   ├── lector.py           # LECTOR semantic review
│   │   │   └── cognitive_load.py   # Cognitive load detection
│   │   └── alembic/           # Database migrations
│   └── web/              # Next.js 16 frontend
│       └── src/
│           ├── app/                # 6 pages (App Router)
│           ├── components/         # 63 React components
│           ├── store/              # Zustand state stores
│           └── lib/                # API client + utilities
├── tests/                # 23 pytest + 23 Playwright E2E
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
| **Learning Science** | FSRS 4.5 · BKT · LECTOR · LOOM · Cognitive Load Theory |
| **CI/CD** | GitHub Actions · Docker Compose · Playwright |

## Research

OpenTutor builds on these papers:

| Paper | What We Use |
|-------|-------------|
| [LECTOR](https://arxiv.org/abs/2508.03275) (arxiv 2025) | Semantic spaced repetition via knowledge graph relationships |
| [LOOM](https://arxiv.org/abs/2511.21037) (arxiv 2025) | Dynamic learner memory graph for concept mastery tracking |
| [Cognitive Load + DKT](https://www.nature.com/articles/s41598-025-10497-x) (Nature 2025) | Behavioral signals for real-time difficulty adaptation |
| [FSRS 4.5](https://github.com/open-spaced-repetition/fsrs4.5) | Optimized free spaced repetition scheduling |

## Contributing

Contributions are welcome! Please see the [issues](https://github.com/zijinz456/OpenTutor/issues) page for open tasks.

```bash
# Run tests
python -m pytest tests/ -q -k "not llm_router"

# E2E tests (requires running stack)
npx playwright test
```

<!-- Uncomment when contributors grow:
<a href="https://github.com/zijinz456/OpenTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=zijinz456/OpenTutor" />
</a>
-->

## License

[MIT](LICENSE)

---

<div align="center">

If OpenTutor helps your learning, consider giving it a ⭐

</div>
