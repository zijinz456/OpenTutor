# Contributing to OpenTutor

Thanks for your interest in contributing! OpenTutor is built in public, and we welcome contributors of all experience levels.

## Where to Start

**New here?** Check out issues labeled [`good first issue`](https://github.com/zijinz456/OpenTutor/labels/good%20first%20issue) — they're scoped, well-documented, and a great way to get familiar with the codebase.

**Want to discuss first?** Open a [GitHub Discussion](https://github.com/zijinz456/OpenTutor/discussions) or comment on an existing issue before starting work on larger changes.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Git

### Quick Start (5 minutes)

```bash
# Clone
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor

# Backend
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-core.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd apps/web
npm install
npm run dev
```

Visit http://localhost:3001.

### LLM Setup

By default, OpenTutor uses Ollama for local inference:

```bash
# Install Ollama: https://ollama.com
ollama pull llama3.2:3b
```

Or configure any supported provider in `.env` (copy from `.env.example`).

### Docker Alternative

```bash
cp .env.example .env
docker compose up -d --build
```

## Project Architecture

```
apps/api/                    # FastAPI backend
  routers/                   # 42 API route modules
  models/                    # 27 SQLAlchemy ORM models
  services/
    agent/                   # 3 specialist agents + orchestrator
      tools/                 # 20+ agent tools
    ingestion/               # Content processing pipeline (PDF, DOCX, Canvas)
    llm/                     # Multi-provider LLM router + circuit breaker
    search/                  # Hybrid BM25 + vector RAG
    spaced_repetition/       # FSRS scheduler + flashcards
    learning_science/        # BKT, difficulty selection, cognitive load
    block_decision/          # ML-based block recommendations

apps/web/                    # Next.js 16 frontend
  src/app/                   # 13 pages (App Router)
  src/components/
    blocks/                  # 12 composable learning blocks
    chat/                    # Chat UI (drawer, messages, input)
    course/                  # Course-specific components
  src/store/                 # Zustand state stores
  src/lib/
    block-system/            # Block registry, templates, feature unlock
    api/                     # API client

tests/                       # pytest + Playwright E2E
scripts/                     # Dev, CI, deployment scripts
```

### Key Concepts

- **Block System** — The core UI paradigm. 12 composable blocks (notes, quiz, flashcards, knowledge graph, etc.) in a drag-droppable grid. See `apps/web/src/lib/block-system/`.
- **Agent Orchestrator** — Intent classification routes user messages to specialist agents (Tutor, Planner, Layout). See `apps/api/services/agent/orchestrator.py`.
- **LOOM** — Knowledge graph that extracts concepts from course material and tracks mastery. See `apps/api/services/loom*.py`.
- **LECTOR** — Semantic spaced repetition that extends FSRS with graph-awareness. See `apps/api/services/lector.py`.

## Making Changes

### Branch Naming

- `feat/short-description` for features
- `fix/short-description` for bug fixes
- `docs/short-description` for documentation

### Code Style

**Python (Backend)**
- Formatter: `ruff format`
- Linter: `ruff check`
- Type hints on all public functions

**TypeScript (Frontend)**
- Linter: `eslint`
- Use TypeScript strict mode (no `any`)
- Components use functional style with hooks

### Commit Messages

Use conventional-style prefixes:

```
feat: add flashcard export
fix: quiz scoring edge case with empty answers
docs: update LLM configuration guide
test: add ingestion pipeline integration test
refactor: extract block layout logic from course page
```

## Running Tests

```bash
# Backend unit + integration tests
cd apps/api
python -m pytest tests/ -q

# Skip LLM-dependent tests (faster)
python -m pytest tests/ -q -k "not llm_router"

# Frontend lint
cd apps/web
npm run lint

# E2E tests (requires running stack)
npx playwright test
```

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes with clear, focused commits
3. Add or update tests for your changes
4. Ensure all tests pass locally
5. Open a PR with a clear description of what and why
6. Link any related issues

### PR Review Checklist

- [ ] Tests pass
- [ ] PR includes either regression tests or a clear API/contract update note
- [ ] No new `any` types in TypeScript
- [ ] No bare `except Exception: pass` in Python
- [ ] i18n keys added for any new user-facing strings (both `en.json` and `zh.json`)
- [ ] No hardcoded secrets or API keys

## Adding a New Block Type

The block system is designed for extensibility. To add a new block:

1. **Create the component** in `apps/web/src/components/blocks/blocks/my-block.tsx`
2. **Register it** in `apps/web/src/lib/block-system/registry.ts`:
   ```ts
   my_block: {
     label: "My Block",
     icon: MyIcon,
     component: lazy(() => import("@/components/blocks/blocks/my-block")),
     defaultSize: "medium",
     category: "learning",
   }
   ```
3. **Add i18n keys** in `apps/web/src/locales/en.json` and `zh.json`
4. **Optional: Add a decision rule** in `apps/api/services/block_decision/rules.py` to auto-suggest your block based on signals
5. **Optional: Add unlock conditions** in `apps/web/src/lib/block-system/feature-unlock.ts`

See existing blocks like `review-block.tsx` or `flashcard-block.tsx` for examples.

## Ways to Contribute

Code is not the only way to help:

- **Bug reports** — Found something broken? [Open an issue](https://github.com/zijinz456/OpenTutor/issues/new?template=bug_report.md)
- **Documentation** — Improve guides, add examples, fix typos
- **Translations** — Help make OpenTutor accessible in more languages
- **Testing** — Try the app and report your experience
- **Design** — UI/UX improvements, accessibility audit
- **Learning science** — Help improve our adaptive algorithms (LOOM, LECTOR, FSRS tuning)

## Reporting Issues

- Use [GitHub Issues](https://github.com/zijinz456/OpenTutor/issues)
- Include steps to reproduce
- Include browser/OS/Python version if relevant
- For LLM-related issues, include provider and model name

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
