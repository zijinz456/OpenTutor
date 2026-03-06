# OpenTutor Deployment Guide

OpenTutor is a local-first, single-user AI tutoring platform. This guide covers every way to get it running on your machine.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Local Development Setup](#2-local-development-setup)
3. [Docker Deployment](#3-docker-deployment)
4. [Environment Variables Reference](#4-environment-variables-reference)
5. [Database](#5-database)
6. [LLM Provider Configuration](#6-llm-provider-configuration)
7. [TLS/SSL](#7-tlsssl)
8. [Monitoring](#8-monitoring)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Quick Start

The fastest way to get OpenTutor running. Choose one of two paths:

### Option A: Quickstart Script (recommended for first-time setup)

This script checks prerequisites, creates the database, runs migrations, and starts both servers.

**macOS / Linux:**

```bash
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor
bash scripts/quickstart.sh
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor
.\scripts\quickstart.ps1
```

The script will:
1. Verify prerequisites (Node.js 20+, Python 3.11, PostgreSQL, curl)
2. Create `.env` from `.env.example` if it does not exist
3. Auto-detect Ollama and configure it as the LLM provider if no cloud API key is set (bash script only)
4. Create a Python virtual environment at `apps/api/.venv/` and install dependencies
5. Create the `opentutor` database and enable the pgvector extension
6. Run Alembic migrations
7. Install frontend npm packages
8. Start the API server (port 8000) and the web server (port 3000)

Once ready, open **http://localhost:3000** in your browser.

> The app works without an LLM API key -- it will return mock responses. Add a key to `.env` later for real AI features. See [LLM Provider Configuration](#6-llm-provider-configuration).

### Option B: Docker Compose (fully containerized)

```bash
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor
cp .env.example .env

# Optionally add your LLM API key to .env now:
# echo "OPENAI_API_KEY=sk-..." >> .env

docker compose up -d
```

This starts four services: PostgreSQL (pgvector), Redis, the API, and the web frontend. First build takes a few minutes to download images and install dependencies; subsequent starts are fast.

Verify everything is healthy:

```bash
docker compose ps          # all services should show "healthy"
curl http://localhost:8000/api/health
```

Open **http://localhost:3000**.

### Option C: Dev Local Script (Docker + verification)

The `dev_local.sh` script wraps Docker Compose with health-check waiting and optional verification:

```bash
# Start the stack and wait for readiness
bash scripts/dev_local.sh up

# Start with a fresh build
bash scripts/dev_local.sh up --build

# Check status
bash scripts/dev_local.sh status

# View logs
bash scripts/dev_local.sh logs        # all services
bash scripts/dev_local.sh logs api    # single service

# Stop
bash scripts/dev_local.sh down

# Stop and delete all data (pgdata, redis, uploads)
bash scripts/dev_local.sh reset
```

---

## 2. Local Development Setup

Step-by-step setup for development without Docker.

### Prerequisites

| Tool | Version | macOS (brew) | Ubuntu/Debian (apt) | Fedora (dnf) | Windows |
|------|---------|-------------|---------------------|-------------|---------|
| Python | 3.11 (required; 3.14 breaks tiktoken) | `brew install python@3.11` | `sudo apt install python3.11 python3.11-venv` | `sudo dnf install python3.11` | [python.org](https://www.python.org/downloads/) |
| Node.js | 20+ | `brew install node` | [nodesource.com](https://nodesource.com/) | `sudo dnf install nodejs` | [nodejs.org](https://nodejs.org/) |
| PostgreSQL | 16+ | `brew install postgresql@16` | `sudo apt install postgresql` | `sudo dnf install postgresql-server` | [postgresql.org](https://www.postgresql.org/download/windows/) |
| pgvector | latest | `brew install pgvector` | See [pgvector install docs](https://github.com/pgvector/pgvector#installation) | See [pgvector install docs](https://github.com/pgvector/pgvector#installation) | [pgvector Windows](https://github.com/pgvector/pgvector#windows) |
| curl | any | pre-installed | `sudo apt install curl` | pre-installed | built into Windows 10+ |

### Step 1: Clone and configure

```bash
git clone https://github.com/zijinz456/OpenTutor.git
cd OpenTutor
cp .env.example .env
```

Edit `.env` to add an LLM API key (optional -- mock mode works without one):

```bash
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
```

### Step 2: Python environment

```bash
cd apps/api
python3.11 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements-full.txt
```

### Step 3: Database

```bash
# Start PostgreSQL
brew services start postgresql@16          # macOS
# sudo systemctl start postgresql          # Ubuntu / Fedora (systemd)
# sudo service postgresql start            # Ubuntu (SysV init)
# Start-Service postgresql-x64-16          # Windows (PowerShell, run as admin)

# Create database and user
createdb opentutor
psql -d opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If you need a dedicated user (the default `.env` uses `opentutor:opentutor_dev`):

```bash
psql -U postgres -c "CREATE USER opentutor WITH PASSWORD 'opentutor_dev';"
psql -U postgres -c "CREATE DATABASE opentutor OWNER opentutor;"
psql -U postgres -d opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Step 4: Run migrations

```bash
cd apps/api
source .venv/bin/activate
alembic upgrade head
```

### Step 5: Frontend dependencies

```bash
cd apps/web
npm install
```

### Step 6: Start servers

Open two terminal windows:

**Terminal 1 -- API:**
```bash
cd apps/api
source .venv/bin/activate         # Windows: .venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 -- Web:**
```bash
cd apps/web
npm run dev
```

Open **http://localhost:3000**. The API is at **http://localhost:8000/api**.

> Redis is optional for local development. It is only required when `APP_RUN_SCHEDULER=true` or `APP_RUN_ACTIVITY_ENGINE=true` (both default to `false`).

---

## 3. Docker Deployment

### Architecture

```
docker compose up
```

starts four containers:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `db` | `pgvector/pgvector:pg17` | 5432 | PostgreSQL with pgvector |
| `redis` | `redis:7-alpine` | 6379 | Background task queue (optional) |
| `api` | Built from `apps/api/Dockerfile` | 8000 | FastAPI backend |
| `web` | Built from `apps/web/Dockerfile` | 3000 | Next.js frontend |

### Startup sequence

1. `db` and `redis` start first and expose health checks.
2. `api` waits for both to be healthy, runs `alembic upgrade head`, then starts uvicorn.
3. `web` waits for `api` to be healthy, then serves the Next.js app.

### Environment variables

All environment variables are passed from your `.env` file (or shell environment) into the `api` container via the `docker-compose.yml`. The most important ones:

```bash
# .env
OPENAI_API_KEY=sk-...            # or any LLM provider key
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
```

For Ollama running on the host machine, use `host.docker.internal` so the container can reach it:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### Named volumes

| Volume | Purpose |
|--------|---------|
| `pgdata` | PostgreSQL data directory |
| `redisdata` | Redis persistence |
| `uploads` | Uploaded course materials |

To reset all data:

```bash
docker compose down -v
```

### Rebuilding

```bash
# Rebuild after code changes
docker compose up -d --build

# Force rebuild without cache
docker compose build --no-cache
docker compose up -d
```

---

## 4. Environment Variables Reference

All variables are defined in `apps/api/config.py` (via pydantic-settings) and documented in `.env.example`.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | `development` or `production` |
| `DATABASE_URL` | `postgresql+asyncpg://opentutor:opentutor_dev@localhost:5432/opentutor` | Async PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (needed for scheduler/activity engine) |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated allowed origins, or `*` for all |

### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openai` | Primary provider: `openai`, `anthropic`, `deepseek`, `ollama`, `openrouter`, `gemini`, `groq`, `vllm`, `lmstudio`, `textgenwebui`, `custom` |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for the chosen provider |
| `LLM_REQUIRED` | `false` | If `true`, disables mock fallback -- AI endpoints fail without a configured provider |
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `ANTHROPIC_API_KEY` | (empty) | Anthropic API key |
| `DEEPSEEK_API_KEY` | (empty) | DeepSeek API key |
| `OPENROUTER_API_KEY` | (empty) | OpenRouter API key |
| `GEMINI_API_KEY` | (empty) | Google Gemini API key |
| `GROQ_API_KEY` | (empty) | Groq API key |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `VLLM_BASE_URL` | `http://localhost:8000/v1` | vLLM server URL |
| `LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio server URL |
| `TEXTGENWEBUI_BASE_URL` | `http://localhost:5000/v1` | Text Generation WebUI server URL |
| `CUSTOM_LLM_API_KEY` | (empty) | API key for a generic OpenAI-compatible endpoint |
| `CUSTOM_LLM_BASE_URL` | (empty) | Base URL for a generic OpenAI-compatible endpoint |
| `CUSTOM_LLM_MODEL` | (empty) | Model name for custom endpoint |

### LLM Model Routing (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL_LARGE` | (empty) | Model for heavyweight agents (teaching, planning) |
| `LLM_MODEL_SMALL` | (empty) | Model for lightweight agents (preference, scene) |
| `LLM_MODEL_FAST` | (empty) | 3-tier: greetings, preferences |
| `LLM_MODEL_STANDARD` | (empty) | 3-tier: teaching, exercises |
| `LLM_MODEL_FRONTIER` | (empty) | 3-tier: planning, code execution, assessment |

### LiteLLM (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_LITELLM` | `false` | Enable LiteLLM universal adapter (requires `pip install litellm`) |
| `LITELLM_MODEL` | (empty) | LiteLLM model string, e.g. `openai/gpt-4o` |
| `LITELLM_API_BASE` | (empty) | Custom LiteLLM proxy URL |
| `LITELLM_API_KEY` | (empty) | API key for LiteLLM proxy |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `false` | Enable JWT authentication. Keep `false` for local single-user use. |
| `DEPLOYMENT_MODE` | `single_user` | `single_user` or `multi_user` |
| `JWT_SECRET_KEY` | `change-me-in-production` | JWT signing secret. Must be 32+ characters when auth is enabled. |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |

### File Upload

| Variable | Default | Description |
|----------|---------|-------------|
| `UPLOAD_DIR` | `./uploads` | Directory for uploaded course materials |
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum upload file size |
| `SCRAPE_FIXTURE_DIR` | (empty) | Directory for scrape test fixtures |

### Runtime Bootstrap

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_AUTO_CREATE_TABLES` | `false` (Docker) / `true` (`.env.example`) | Auto-create DB tables on startup via SQLAlchemy |
| `APP_AUTO_SEED_SYSTEM` | `false` (Docker) / `true` (`.env.example`) | Seed built-in templates and preset scenes on first startup |
| `APP_RUN_SCHEDULER` | `false` | Enable APScheduler background jobs |
| `APP_RUN_ACTIVITY_ENGINE` | `false` | Enable durable task execution engine (requires Redis) |

### Code Sandbox

| Variable | Default | Description |
|----------|---------|-------------|
| `CODE_SANDBOX_BACKEND` | `auto` (`.env.example`) / `container` (Docker) | `auto`, `container`, or `process` |
| `CODE_SANDBOX_RUNTIME` | `docker` | `docker` or `podman` |
| `CODE_SANDBOX_IMAGE` | `python:3.11-alpine` | Docker image for code execution sandbox |
| `CODE_SANDBOX_TIMEOUT_SECONDS` | `5` | Maximum execution time per sandbox run |
| `ALLOW_INSECURE_PROCESS_SANDBOX` | `false` | Allow process-based sandbox (dev only, no isolation) |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_MODE` | `simple` | `simple` (fixed RPM) or `cost_aware` (GCRA with per-endpoint costs) |
| `RATE_LIMIT_COST_BUDGET` | `500` | Cost units per minute per IP (cost_aware mode only) |
| `TRUST_PROXY_HEADERS` | `false` | Trust `X-Forwarded-For` header. Only enable behind a reverse proxy. |

### Swarm / Parallel Execution

| Variable | Default | Description |
|----------|---------|-------------|
| `SWARM_ENABLED` | `true` | Enable parallel agent execution |
| `SWARM_MAX_CONCURRENCY` | `4` | Maximum concurrent agent tasks |
| `SWARM_TIMEOUT_SECONDS` | `30.0` | Timeout per swarm task |
| `SWARM_TOKEN_BUDGET` | `50000` | Token budget per swarm round |
| `PARALLEL_CONTEXT_LOADING` | `true` | Load agent context in parallel |
| `ACTIVITY_ENGINE_MAX_CONCURRENCY` | `3` | Maximum concurrent activity engine tasks |

### Push Notifications (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `PUSH_NOTIFICATIONS_ENABLED` | `false` | Enable Web Push notifications |
| `VAPID_PRIVATE_KEY` | (empty) | VAPID private key for push |
| `VAPID_PUBLIC_KEY` | (empty) | VAPID public key for push |
| `VAPID_CLAIMS_EMAIL` | (empty) | Contact email for VAPID claims |

### Multi-Channel Messaging (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `CHANNELS_ENABLED` | (empty) | Comma-separated: `whatsapp,imessage,telegram,discord` |
| `CHANNEL_AUTO_CREATE_USERS` | `true` | Auto-create user accounts for messaging channel users |
| `CHANNEL_DEFAULT_SCENE` | `study_session` | Default scene for channel conversations |

Channel-specific variables (WhatsApp, iMessage/BlueBubbles, Telegram, Discord) are documented in `.env.example`.

---

## 5. Database

### PostgreSQL + pgvector

OpenTutor requires PostgreSQL 16+ with the [pgvector](https://github.com/pgvector/pgvector) extension for vector similarity search (used for RAG and knowledge graph features).

**Docker:** The `pgvector/pgvector:pg17` image includes pgvector pre-installed. No extra steps needed.

**Manual install (macOS):**

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
```

**Manual install (Ubuntu):**

```bash
sudo apt install postgresql-16
# Install pgvector from source or apt (see https://github.com/pgvector/pgvector#linux)
```

**Create the database:**

```bash
createdb opentutor
psql -d opentutor -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Alembic Migrations

The API uses Alembic for database schema management. Migration files live in `apps/api/alembic/versions/`.

```bash
cd apps/api
source .venv/bin/activate   # if running outside Docker (Windows: .venv\Scripts\activate)

# Apply all migrations
alembic upgrade head

# Check current migration state
alembic current

# View migration history
alembic history --verbose

# Generate a new migration after model changes
alembic revision --autogenerate -m "description of change"
```

**Docker:** The API container runs `alembic upgrade head` automatically on startup. You can also run migrations manually:

```bash
docker compose exec api alembic upgrade head
```

**Using the dev_local.sh helper:**

```bash
bash scripts/dev_local.sh migrate-host
```

### Auto-create tables

If you prefer not to use Alembic during development, set `APP_AUTO_CREATE_TABLES=true` in `.env`. This runs `Base.metadata.create_all()` on startup to create any missing tables. Alembic is still the recommended approach for production and for tracking schema changes.

### Backup and Restore

**Backup:**

```bash
# Local PostgreSQL
pg_dump -Fc opentutor > opentutor_backup_$(date +%Y%m%d).dump

# Docker
docker compose exec db pg_dump -U opentutor -Fc opentutor > opentutor_backup_$(date +%Y%m%d).dump
```

**Restore:**

```bash
# Local PostgreSQL
pg_restore -d opentutor --clean --if-exists opentutor_backup_20260302.dump

# Docker (copy dump into container first)
docker cp opentutor_backup_20260302.dump opentutor-db:/tmp/
docker compose exec db pg_restore -U opentutor -d opentutor --clean --if-exists /tmp/opentutor_backup_20260302.dump
```

**Backup uploads directory:**

```bash
# Local
tar czf uploads_backup_$(date +%Y%m%d).tar.gz apps/api/uploads/

# Docker
docker cp opentutor-api:/app/uploads ./uploads_backup/
```

### Stamping an existing database

If the database tables exist but Alembic's `alembic_version` table is missing (e.g., tables were created via `APP_AUTO_CREATE_TABLES=true`), stamp the current revision so Alembic knows the schema is up to date:

```bash
cd apps/api
alembic stamp head
```

---

## 6. LLM Provider Configuration

OpenTutor supports multiple LLM providers. The app works without any provider configured -- it falls back to mock responses. Add a provider for real AI tutoring.

### Cloud Providers

Set one or more API keys in `.env`. The first configured key becomes available as a fallback if the primary provider goes down (circuit breaker pattern).

#### OpenAI

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini        # or gpt-4o, gpt-4-turbo, o3-mini
OPENAI_API_KEY=sk-...
```

#### Anthropic

```bash
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514   # or claude-haiku, etc.
ANTHROPIC_API_KEY=sk-ant-...
```

#### DeepSeek

```bash
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...
```

#### OpenRouter

```bash
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY=sk-or-...
```

#### Google Gemini

```bash
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
GEMINI_API_KEY=...
```

#### Groq

```bash
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=gsk_...
```

### Local Providers (free, no API key)

#### Ollama (recommended for local)

1. Install Ollama: https://ollama.com
2. Pull a model:

```bash
ollama pull qwen2.5
# or a smaller model for limited hardware:
ollama pull qwen2.5:1.5b
```

3. Configure `.env`:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5
OLLAMA_BASE_URL=http://localhost:11434
```

For Docker deployments, use `host.docker.internal` so the API container can reach Ollama on your host:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

> The quickstart script auto-detects a running Ollama instance and configures it automatically.

#### LM Studio

1. Download LM Studio: https://lmstudio.ai
2. Load a model and start the local server.
3. Configure `.env`:

```bash
LLM_PROVIDER=lmstudio
LLM_MODEL=default
LMSTUDIO_BASE_URL=http://localhost:1234/v1
```

#### vLLM

```bash
LLM_PROVIDER=vllm
LLM_MODEL=your-model-name
VLLM_BASE_URL=http://localhost:8000/v1
```

#### Text Generation WebUI

```bash
LLM_PROVIDER=textgenwebui
LLM_MODEL=default
TEXTGENWEBUI_BASE_URL=http://localhost:5000/v1
```

### Generic OpenAI-Compatible Endpoint

For any server that exposes an OpenAI-compatible API:

```bash
LLM_PROVIDER=custom
CUSTOM_LLM_BASE_URL=http://your-server:port/v1
CUSTOM_LLM_MODEL=your-model
CUSTOM_LLM_API_KEY=your-key    # if required
```

### LiteLLM (universal adapter)

LiteLLM provides access to 100+ LLM backends through a unified interface:

```bash
pip install litellm   # in your API venv

USE_LITELLM=true
LITELLM_MODEL=openai/gpt-4o
# LITELLM_API_BASE=   # optional proxy URL
# LITELLM_API_KEY=    # optional proxy API key
```

### Multi-Model Routing

OpenTutor's 6 specialist agents can use different models based on task complexity:

**2-tier routing:**

```bash
LLM_MODEL_LARGE=gpt-4o           # teaching, planning agents
LLM_MODEL_SMALL=gpt-4o-mini      # preference, scene agents
```

**3-tier routing (overrides 2-tier when set):**

```bash
LLM_MODEL_FAST=gpt-4o-mini       # greetings, preferences
LLM_MODEL_STANDARD=gpt-4o-mini   # teaching, exercises
LLM_MODEL_FRONTIER=gpt-4o        # planning, assessment, code execution
```

### Runtime LLM Configuration

You can change LLM settings at runtime without restarting the server via the preferences API:

```bash
# Get current config
curl http://localhost:8000/api/preferences/runtime/llm

# Update provider/model
curl -X PUT http://localhost:8000/api/preferences/runtime/llm \
  -H "Content-Type: application/json" \
  -d '{"provider": "ollama", "model": "qwen2.5"}'

# Test a connection
curl -X POST http://localhost:8000/api/preferences/runtime/llm/test \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai"}'
```

Changes persist to `.env` and take effect immediately.

### Provider Fallback

If you configure multiple API keys, OpenTutor uses a circuit breaker pattern: if the primary provider fails 3 times consecutively, it automatically falls back to the next healthy provider. The circuit resets after 120 seconds.

---

## 7. TLS/SSL

OpenTutor itself does not handle TLS. For HTTPS, place a reverse proxy in front of it.

### Caddy (simplest option)

Caddy automatically provisions Let's Encrypt certificates.

1. Install Caddy: https://caddyserver.com/docs/install

2. Create a `Caddyfile`:

```
tutor.example.com {
    reverse_proxy /api/* localhost:8000
    reverse_proxy /* localhost:3000
}
```

3. Run: `caddy run`

Caddy will automatically obtain and renew TLS certificates.

### nginx

1. Install nginx and certbot:

```bash
# Ubuntu
sudo apt install nginx certbot python3-certbot-nginx
```

2. Create `/etc/nginx/sites-available/opentutor`:

```nginx
server {
    listen 80;
    server_name tutor.example.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE (streaming chat)
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

3. Enable and get certificates:

```bash
sudo ln -s /etc/nginx/sites-available/opentutor /etc/nginx/sites-enabled/
sudo certbot --nginx -d tutor.example.com
sudo systemctl reload nginx
```

### When using a reverse proxy

Update these environment variables:

```bash
CORS_ORIGINS=https://tutor.example.com
TRUST_PROXY_HEADERS=true   # so rate limiting uses the real client IP
```

If the frontend is served through the proxy, set the API URL at build time:

```bash
NEXT_PUBLIC_API_URL=https://tutor.example.com/api
```

---

## 8. Monitoring

### Health Check Endpoint

```bash
curl http://localhost:8000/api/health
```

Returns a JSON payload with detailed system status:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "connected",
  "schema": "ready",
  "migration_required": false,
  "migration_status": "up_to_date",
  "llm_providers": ["openai"],
  "llm_primary": "openai",
  "llm_required": false,
  "llm_available": true,
  "llm_status": "ready",
  "llm_provider_health": {"openai": true},
  "deployment_mode": "single_user",
  "code_sandbox_backend": "auto",
  "code_sandbox_runtime": "docker",
  "code_sandbox_runtime_available": true
}
```

Key fields to monitor:
- `status`: `ok` or `degraded`
- `database`: `connected` or `unreachable`
- `schema`: `ready`, `missing`, or a migration status string
- `llm_status`: `ready`, `mock_fallback`, `configuration_required`, or `degraded`
- `migration_required`: `true` means you need to run `alembic upgrade head`

### Docker Health Checks

All four Docker services have built-in health checks:

```bash
docker compose ps   # STATUS column shows health
```

- **db**: `pg_isready -U opentutor` every 5s
- **redis**: `redis-cli ping` every 5s
- **api**: `curl http://127.0.0.1:8000/api/health` every 10s
- **web**: depends on api being healthy

### Log Configuration

The API uses Python's standard `logging` module. Set log level via environment or Python config:

```bash
# View Docker logs
docker compose logs -f api          # follow API logs
docker compose logs -f --tail=100   # last 100 lines, all services

# Dev local helper
bash scripts/dev_local.sh logs
bash scripts/dev_local.sh logs api
```

### Preflight Check

Before running tests or verification, check that all prerequisites are met:

```bash
bash scripts/dev_local.sh preflight
```

This checks: Docker, curl, npm, Python 3.11, upload fixtures, API and web reachability, LLM credentials.

### Verification Suite

Run the full verification suite against a running stack:

```bash
# Basic verification (mock LLM, representative E2E test)
bash scripts/dev_local.sh verify

# Full E2E suite
bash scripts/dev_local.sh verify --all-e2e

# Include real LLM provider tests
bash scripts/dev_local.sh verify --with-real-llm
```

Reports are written to `tmp/verification-summary.md` and `tmp/verification-summary.json`.

---

## 9. Troubleshooting

See [troubleshooting.md](troubleshooting.md) for detailed solutions. Here is a summary of the most common issues.

### "Port already in use"

Another service is using port 5432, 6379, 8000, or 3000.

```bash
# Find what's using the port
lsof -i :5432                              # macOS / Linux
# Get-NetTCPConnection -LocalPort 5432     # Windows (PowerShell)

# Stop the conflicting service
brew services stop postgresql@16           # macOS
# sudo systemctl stop postgresql           # Linux
# Stop-Service postgresql-x64-16           # Windows (PowerShell, run as admin)
```

Or change the port mapping in `docker-compose.yml` (e.g., `"5433:5432"`).

### API container keeps restarting

```bash
docker compose logs api --tail 50
```

Common causes: database not ready yet (wait 30s), broken Alembic migration.

### "extension vector does not exist"

pgvector is not installed. Docker users should not see this (the image includes it). Manual install:

```bash
# macOS
brew install pgvector

# Ubuntu: build from source
# See https://github.com/pgvector/pgvector#linux
```

### Mock/placeholder AI responses

No LLM provider is configured. Add an API key to `.env` and restart:

```bash
echo "OPENAI_API_KEY=sk-..." >> .env
docker compose restart api   # or restart uvicorn manually
```

Or use Ollama for free local inference (see [LLM Provider Configuration](#6-llm-provider-configuration)).

### Ollama "connection refused" from Docker

The API container cannot reach Ollama on `localhost`. Use the Docker host address:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### Python 3.11 required

OpenTutor requires Python 3.11 specifically. Python 3.14 breaks `tiktoken`.

```bash
# macOS
brew install python@3.11
python3.11 -m venv apps/api/.venv

# pyenv
pyenv install 3.11
pyenv local 3.11
```

### Database migration errors

```bash
cd apps/api

# Check current state
alembic current

# Re-run migrations
alembic upgrade head

# If tables exist but alembic_version is missing
alembic stamp head
```

### "Failed to fetch" in browser

The frontend cannot reach the API. Verify:

1. API is running: `curl http://localhost:8000/api/health`
2. CORS is configured: `CORS_ORIGINS` in `.env` includes `http://localhost:3000`
3. If using non-default ports, set `NEXT_PUBLIC_API_URL` accordingly

### Slow chat responses

- **Cloud LLM**: Try a smaller model (`gpt-4o-mini` instead of `gpt-4o`).
- **Ollama**: Needs 16 GB+ RAM. Try smaller models like `qwen2.5:1.5b`.
- **DeepSeek**: Can be slow during peak hours.

### Full reset

To start completely fresh:

```bash
# Docker
docker compose down -v   # removes all data volumes

# Or using the helper
bash scripts/dev_local.sh reset
```

For more detailed troubleshooting, see [troubleshooting.md](troubleshooting.md).
