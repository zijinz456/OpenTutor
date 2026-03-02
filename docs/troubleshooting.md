# Troubleshooting

Common issues when setting up OpenTutor and how to fix them.

If your machine uses the legacy `docker-compose` binary instead of the `docker compose`
plugin, you can substitute that command in the examples below. The repo-local
`bash scripts/dev_local.sh ...` wrappers now support either form automatically.

---

## Docker Setup Issues

### `docker compose up` fails with "port already in use"

Another service is using port 5432 (PostgreSQL), 6379 (Redis), 8000 (API), or 3000 (Web).

```bash
# Find what's using the port (example: 5432)
lsof -i :5432                              # macOS / Linux
# ss -tlnp | grep 5432                     # Linux alternative
# Get-NetTCPConnection -LocalPort 5432     # Windows (PowerShell)
# netstat -ano | findstr :5432             # Windows (Command Prompt)

# Option 1: Stop the conflicting service
brew services stop postgresql@17           # macOS
# sudo systemctl stop postgresql           # Linux (systemd)
# Stop-Service postgresql-x64-17           # Windows (PowerShell, run as admin)

# Option 2: Change the port mapping in docker-compose.yml
# e.g., "5433:5432" to expose PostgreSQL on 5433 instead
```

### API container keeps restarting

Check the logs:

```bash
docker compose logs api --tail 50
```

**Common causes:**
- Database not ready yet — wait 30 seconds and check again. The API depends on `db` being healthy.
- Missing Alembic migration — the API runs `alembic upgrade head` on startup. If a migration file is missing or broken, it will fail.

### Web container shows "ECONNREFUSED" or blank page

The web container depends on the API being healthy. Check API status first:

```bash
docker compose ps         # All services should show "healthy"
curl http://localhost:8000/api/health   # Should return JSON
```

If the API isn't healthy yet, wait 30–60 seconds. On first build, image downloads take time.

### `docker compose build` is very slow

First build downloads base images and installs dependencies. Subsequent builds use Docker cache and are much faster. If you want to force a rebuild:

```bash
docker compose build --no-cache
```

---

## Database Issues

### "connection refused" to PostgreSQL

```bash
# Docker setup — check if db container is running
docker compose ps db

# Manual setup — check if PostgreSQL is running
pg_isready -h localhost -p 5432

# Start PostgreSQL
brew services start postgresql@17          # macOS
# sudo systemctl start postgresql          # Linux (systemd)
# sudo service postgresql start            # Linux (SysV init)
# Start-Service postgresql-x64-17          # Windows (PowerShell, run as admin)
```

### "database opentutor does not exist"

```bash
# Docker setup — db is auto-created by the container. Try:
docker compose down -v && docker compose up -d   # Warning: this deletes data

# Manual setup — create the database manually:
createdb -U opentutor opentutor
# Or if using the default superuser:
psql -U postgres -c "CREATE DATABASE opentutor OWNER opentutor;"
```

### "extension vector does not exist"

pgvector is not installed. See [pgvector-install.md](pgvector-install.md) for installation instructions.

If using Docker, this should not happen — the `pgvector/pgvector:pg17` image includes the extension.

### Alembic migration errors

```bash
# Check current migration state
cd apps/api
python -m alembic current

# Try upgrading again
python -m alembic upgrade head

# If tables already exist but alembic_version is missing, stamp the current schema
# after confirming the database matches the latest migrations.
python -m alembic stamp head
```

### API health says schema is missing or migration is required

If `GET /api/health` returns `"schema": "missing"` or `"migration_required": true`, the
database is reachable but the tables are either missing or not tracked by Alembic yet.

```bash
# Preferred repo-local command
bash scripts/dev_local.sh migrate-host

# Equivalent manual command
cd apps/api
python -m alembic upgrade head
```

If health reports `"migration_status": "version_table_missing"`, the schema exists but the
`alembic_version` table does not. In that case, verify the schema is current and then run:

```bash
cd apps/api
python -m alembic stamp head
```

You can also run:

```bash
bash scripts/dev_local.sh verify-host
```

This now fails with a direct migration hint instead of a generic stack error.

---

## LLM / AI Issues

### AI features return "mock" or placeholder responses

No LLM provider is configured. Add at least one API key to `.env`:

```bash
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
# or use Ollama (free): see README "Using Ollama" section
```

Then restart the API:

```bash
# Docker
docker compose restart api

# Manual
# Stop and re-run: uvicorn main:app --reload
```

### "No LLM provider configured" error in logs

Same as above — add an API key or configure Ollama. If you set `LLM_REQUIRED=true`, the API will log an error but continue running with degraded AI features.

### Ollama: "connection refused" or timeout

```bash
# Check if Ollama is running
curl http://localhost:11434/api/version

# If not running, start it
ollama serve

# Check available models
ollama list

# Docker: make sure you're using the right URL
# In .env: OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### Chat responses are slow

- **Cloud LLM:** Normal for large models (GPT-4o, Claude Opus). Try switching to a smaller model (gpt-4o-mini, claude-haiku).
- **Ollama:** Depends on your hardware. 16 GB+ RAM recommended. Try smaller models like `qwen2.5:1.5b`.
- **DeepSeek:** Their API can be slow during peak hours.

---

## Frontend Issues

### Blank page at localhost:3000

```bash
# Docker — check web container
docker compose logs web --tail 20

# Manual — check if dev server is running
cd apps/web && npm run dev

# Check if API is reachable from the frontend
curl http://localhost:8000/api/health
```

### "Failed to fetch" errors in browser console

The frontend can't reach the API. Check:

1. API is running on port 8000: `curl http://localhost:8000/api/health`
2. CORS is configured: check `CORS_ORIGINS` in `.env` includes `http://localhost:3000`
3. If using different ports, update `NEXT_PUBLIC_API_URL` in your `.env`

### npm install fails

```bash
# Clear cache and retry
rm -rf apps/web/node_modules apps/web/.next
cd apps/web && npm install

# If you see Python/node-gyp errors, you may need:
# macOS: xcode-select --install
# Ubuntu: sudo apt install build-essential
```

---

## Python / Backend Issues

### "Python 3.11 required" error

OpenTutor requires Python 3.11 specifically (3.12+ may work but 3.14 breaks tiktoken).

```bash
# macOS
brew install python@3.11
# Use the specific version:
python3.11 -m venv apps/api/.venv

# Ubuntu
sudo apt install python3.11 python3.11-venv

# pyenv (any platform)
pyenv install 3.11
pyenv local 3.11
```

### pip install fails on psycopg / asyncpg

These packages need PostgreSQL client libraries:

```bash
# macOS
brew install postgresql@17

# Ubuntu
sudo apt install libpq-dev

# Windows — ensure PostgreSQL bin directory is in your PATH
# Typically: C:\Program Files\PostgreSQL\16\bin
```

---

## Windows-Specific Issues

### "python3" or "python3.11" not recognized

Windows uses `python` (not `python3`) and the `py` launcher:

```powershell
# Check available Python versions
py --list

# Use Python 3.11 specifically
py -3.11 --version

# Create venv with specific version
py -3.11 -m venv apps\api\.venv
```

### PowerShell execution policy blocks quickstart.ps1

```powershell
# Allow scripts for current session only
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Or run directly with bypass
powershell -ExecutionPolicy Bypass -File scripts\quickstart.ps1
```

### PostgreSQL service won't start

```powershell
# Check service status
Get-Service postgresql*

# Start the service (run PowerShell as Administrator)
Start-Service postgresql-x64-16

# Or use pg_ctl directly
pg_ctl -D "C:\Program Files\PostgreSQL\16\data" start
```

### Docker Desktop: "docker.sock" not found

Docker Desktop on Windows uses a named pipe instead of a Unix socket. Set in `.env`:

```
DOCKER_SOCK=//./pipe/docker_engine
```

Or avoid the issue entirely by using process-based sandbox:

```
CODE_SANDBOX_BACKEND=process
```

### npm install fails with node-gyp errors

Install the Windows build tools:

```powershell
# Run PowerShell as Administrator
npm install --global windows-build-tools
# Or install Visual Studio Build Tools from https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

---

## Still Stuck?

1. Check the full logs: `docker compose logs` or `docker compose logs api`
2. Run the preflight check: `bash scripts/dev_local.sh preflight`
3. Open an issue at [github.com/zijinz456/OpenTutor/issues](https://github.com/zijinz456/OpenTutor/issues)
