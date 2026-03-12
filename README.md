<div align="center">

<img src="https://img.icons8.com/3d-fluency/94/graduation-cap.png" alt="OpenTutor Logo" width="80" />

# OpenTutor

**The first block-based adaptive learning workspace that runs locally.**

Drop in a PDF. Get an AI tutor that actually adapts to how *you* learn.

[![License](https://img.shields.io/github/license/zijinz456/OpenTutor?style=flat-square&labelColor=black)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=black)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=black)](https://nextjs.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white&labelColor=black)](https://www.docker.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square&labelColor=black)](CONTRIBUTING.md)

**English** | [中文](./README.zh-CN.md)

</div>

<!-- TODO: Replace with demo GIF once recorded -->
<!-- <p align="center"><img src="docs/assets/demo.gif" alt="OpenTutor demo — upload PDF, get adaptive workspace" width="800" /></p> -->

<p align="center"><img src="docs/assets/demo-workspace-full.png" alt="OpenTutor — block-based adaptive workspace with chapters, notes, quiz, knowledge graph, and progress tracking" width="800" /></p>

## The Problem

Every AI learning tool we tried had the same issue: they treat every student the same way. Same explanations. Same pace. Same questions. And they all require sending your data to the cloud.

## The Solution

OpenTutor is a **self-hosted, local-first** AI learning platform. Upload your course material, and within 30 seconds you get structured notes, flashcards, quizzes, and an AI tutor — all running on your machine, completely free.

What makes it different:

- **Block-based workspace** that reshapes itself based on how you learn
- **Runs locally** with open-source LLMs — no API keys required, no data leaves your machine
- **Grounded in learning science** — FSRS spaced repetition, knowledge graphs, cognitive load detection

```
Upload → AI Teaches → You Practice → AI Remembers → AI Reminds → Repeat
```

## Quick Start

### 3 commands. That's it.

```bash
git clone https://github.com/zijinz456/OpenTutor.git && cd OpenTutor
cp .env.example .env
docker compose up -d --build
```

Open [http://localhost:3001](http://localhost:3001). Done.

> No Docker? Use `bash scripts/quickstart.sh` instead — it handles Python venv, npm install, DB setup, and starts both servers.

### One-Click Cloud Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/zijinz456/OpenTutor)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template?referralCode=opentutor&repo=https://github.com/zijinz456/OpenTutor)

<details>
<summary><strong>Manual setup (without Docker)</strong></summary>

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

</details>

<details>
<summary><strong>Platform support</strong></summary>

| Platform | Status |
|---|---|
| macOS (Apple Silicon / Intel) | Supported |
| Linux (Ubuntu 22.04+) | Supported |
| Windows | Community-supported |

**Prerequisites:** Python 3.11+, Node.js 20+, Docker (optional)

</details>

> **Security Note:** Auth is disabled by default for local single-user use. Set `AUTH_ENABLED=true` and configure `JWT_SECRET_KEY` before any network-accessible deployment. See [SECURITY.md](SECURITY.md).

## Public Beta Notes (Local Single-User)

This repository currently targets a **local single-user public beta**.

- Supported first-class platforms: **macOS** and **Linux**
- Windows is community-supported
- Multi-user SaaS/classroom mode is out of scope for this beta

Known limitations for this beta:

- Mobile layout is not fully optimized across all workspace views
- Some advanced autonomous and graph-driven flows are still experimental
- LLM quality/latency depends on your local runtime and hardware

Before opening an issue, check:

- [Troubleshooting Guide](docs/troubleshooting.md)
- [Public Beta Release Notes](docs/public-beta-release-notes.md)
- [Bug Triage & SLA](docs/bug-triage-sla.md)

### Minimal Demo Flow (2-3 minutes)

1. Create/open a course
2. Upload a PDF/DOCX/PPTX file
3. Ask a grounded tutor question in chat
4. Complete one quiz or flashcard review
5. Check plan/review suggestions in workspace
6. Export at least one artifact (session or review content)

## Features

### Block-Based Adaptive Workspace

12 composable learning blocks — notes, quiz, flashcards, knowledge graph, study plan, analytics, and more. The workspace adapts: AI suggests layout changes based on your behavior, and progressively unlocks advanced features as you engage.

<p align="center"><img src="docs/assets/demo-workspace.png" alt="Block-based workspace with AI-generated notes and LaTeX" width="700" /></p>

### AI Tutor with Source Citations

Every answer is grounded in your material. The tutor adapts depth based on behavioral signals — fatigue detection, error patterns, message brevity. Supports Socratic questioning mode.

<p align="center"><img src="docs/assets/demo-chat.png" alt="AI tutor chat drawer with workspace" width="700" /></p>

### 30-Second Content Ingestion

Upload PDF, DOCX, PPTX, or connect Canvas LMS. Get structured notes, AI-generated flashcards, and quiz questions automatically. 7 question types: MCQ, short answer, fill-in-blank, true/false, matching, ordering, coding.

<p align="center"><img src="docs/assets/demo-setup.png" alt="Upload flow — drag and drop PDF" width="700" /></p>

### Adaptive Quiz & Practice

AI-generated quizzes with 7 question types. Wrong-answer tracking with diagnostic feedback. Difficulty adapts based on your performance.

<p align="center"><img src="docs/assets/demo-practice.png" alt="Quiz with multiple choice questions" width="700" /></p>

### Study Plan & Calendar

Plan your study schedule with calendar view, task tracking, and deadline management.

<p align="center"><img src="docs/assets/demo-plan.png" alt="Study plan calendar view" width="700" /></p>

### Spaced Repetition (FSRS 4.5)

Optimized free spaced repetition scheduling for flashcards. Tracks what you're forgetting and proactively reminds you to review.

### Knowledge Graph (LOOM) `[Experimental]`

Tracks concept mastery, prerequisite relationships, and weak areas. Based on [LOOM](https://arxiv.org/abs/2511.21037). Extracts concepts from your material, builds a knowledge graph, and generates optimal learning paths.

### Semantic Review (LECTOR) `[Experimental]`

Extends FSRS with knowledge-graph-aware review prioritization. Based on [LECTOR](https://arxiv.org/abs/2508.03275). Clusters related concepts for co-review, prioritizes prerequisites before dependents.

### 10+ LLM Providers

Local-first with Ollama by default. Switch to OpenAI, Anthropic, DeepSeek, Gemini, Groq, vLLM, LM Studio, OpenRouter, or any OpenAI-compatible endpoint.

```bash
# Local (free, default)
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b

# Cloud (optional)
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...
```

See [.env.example](.env.example) for the full list.

## Architecture

```
OpenTutor/
├── apps/
│   ├── api/              # FastAPI backend
│   │   ├── services/
│   │   │   ├── agent/              # 3 specialist agents (Tutor, Planner, Layout)
│   │   │   ├── ingestion/          # Content processing pipeline
│   │   │   ├── llm/                # Multi-provider LLM router + circuit breaker
│   │   │   ├── search/             # Hybrid BM25 + vector RAG
│   │   │   ├── spaced_repetition/  # FSRS scheduler + flashcards
│   │   │   └── learning_science/   # BKT, difficulty selection, cognitive load
│   │   ├── routers/           # 42 API route modules
│   │   └── models/            # 27 SQLAlchemy ORM models
│   └── web/              # Next.js 16 frontend
│       └── src/
│           ├── components/blocks/  # 12 composable learning blocks
│           ├── store/              # Zustand state stores
│           └── lib/block-system/   # Block registry, templates, feature unlock
├── tests/                # pytest + Playwright E2E (187+ tests)
└── docs/                 # PRD, SPEC, architecture decisions
```

### Agent System

3 specialist agents coordinated by an intent-routing orchestrator:

| Agent | Role |
|-------|------|
| **Tutor** | Teaches with adaptive depth, Socratic questioning, source citations |
| **Planner** | Study plans, goal tracking, deadline management |
| **Layout** | Workspace configuration based on activity context |

### Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Zustand, shadcn/ui |
| **Backend** | FastAPI, Python 3.11+, Pydantic 2, SQLAlchemy 2 (async), Alembic |
| **Database** | SQLite (local-first), optional PostgreSQL |
| **Learning Science** | FSRS 4.5, BKT, LOOM, LECTOR, Cognitive Load Theory |
| **CI/CD** | GitHub Actions, Docker Compose, Playwright |

## Research

OpenTutor builds on these papers:

| Paper | What We Use |
|-------|-------------|
| [LECTOR](https://arxiv.org/abs/2508.03275) (arxiv 2025) | Semantic spaced repetition via knowledge graph relationships |
| [LOOM](https://arxiv.org/abs/2511.21037) (arxiv 2025) | Dynamic learner memory graph for concept mastery tracking |
| [Cognitive Load + DKT](https://www.nature.com/articles/s41598-025-10497-x) (Nature 2025) | Behavioral signals for real-time difficulty adaptation |
| [FSRS 4.5](https://github.com/open-spaced-repetition/fsrs4.5) | Optimized free spaced repetition scheduling |

## Roadmap

- [x] Block-based adaptive workspace (12 block types)
- [x] Multi-agent tutor system (Tutor, Planner, Layout)
- [x] FSRS 4.5 spaced repetition
- [x] Canvas LMS integration
- [x] 10+ LLM provider support
- [x] LOOM knowledge graph — FSRS decay, cross-course linking, content node linking
- [x] LECTOR semantic review — confusion pairs, prerequisite ordering, FSRS integration
- [x] Cognitive load — 12-signal detection, intervention tracking, drift detection
- [ ] Cognitive load weight auto-tuning (data collection in progress)
- [ ] Mobile-responsive workspace
- [ ] Multi-user classroom mode
- [ ] Plugin system for custom blocks

See the [experimental status matrix](docs/experimental-status-matrix.md) for feature flags and module status.

## Contributing

We're building this in public and looking for collaborators. Whether you're into learning science, AI agents, frontend, or backend — there's a place for you.

```bash
# Run tests
python -m pytest tests/ -q -k "not llm_router"

# E2E tests (requires running stack)
npx playwright test
```

Check out the [good first issues](https://github.com/zijinz456/OpenTutor/labels/good%20first%20issue) to get started, or read [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## License

[MIT](LICENSE)

---

<div align="center">

**If OpenTutor helps your learning, consider giving it a star.**

[Report Bug](https://github.com/zijinz456/OpenTutor/issues/new?template=bug_report.md) · [Request Feature](https://github.com/zijinz456/OpenTutor/issues/new?template=feature_request.md) · [Join Discussion](https://github.com/zijinz456/OpenTutor/discussions)

</div>
