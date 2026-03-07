# Contributing to OpenTutor

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Git

### Quick Start

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
- [ ] No new `any` types in TypeScript
- [ ] No bare `except Exception: pass` in Python
- [ ] i18n keys added for any new user-facing strings (both `en.json` and `zh.json`)
- [ ] No hardcoded secrets or API keys

## Project Structure

```
apps/api/          # FastAPI backend
  routers/         # API endpoints
  models/          # SQLAlchemy ORM models
  services/        # Business logic
  schemas/         # Pydantic request/response schemas

apps/web/          # Next.js frontend
  src/app/         # Pages (App Router)
  src/components/  # React components
  src/store/       # Zustand state stores
  src/lib/         # API client, utilities, block system

tests/             # pytest + Playwright E2E
scripts/           # Development and deployment scripts
```

## Reporting Issues

- Use GitHub Issues
- Include steps to reproduce
- Include browser/OS/Python version if relevant
- For LLM-related issues, include provider and model name

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
