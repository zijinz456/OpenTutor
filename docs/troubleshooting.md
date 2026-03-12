# Troubleshooting

Common issues when setting up OpenTutor and how to fix them.

If your machine uses the legacy `docker-compose` binary instead of the `docker compose`
plugin, you can substitute that command in the examples below. The repo-local
`bash scripts/dev_local.sh ...` wrappers now support either form automatically.

---

## Docker Setup Issues

### `docker compose up` fails with "port already in use"

Another service is using port 6379 (Redis), 8000 (API), or 3001 (Web).

```bash
# Find what's using a port (example: 3001)
lsof -i :3001                              # macOS / Linux
# ss -tlnp | grep 3001                     # Linux alternative
# Get-NetTCPConnection -LocalPort 3001     # Windows (PowerShell)
# netstat -ano | findstr :3001             # Windows (Command Prompt)
```

### API container keeps restarting

Check the logs:

```bash
docker compose logs api --tail 50
```

**Common causes:**
- SQLite file path permission issue (container cannot write database file).
- `.env` has a non-SQLite `DATABASE_URL`, but local mode expects SQLite.

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

## Database Issues (SQLite local mode)

### API health reports database not ready

For local mode, migration state is treated as ready by design. If `GET /api/health` still
shows database problems (for example `database: unreachable`):

```bash
# 1) Ensure local mode flags are correct
bash scripts/check_local_mode.sh --env-file .env --skip-api

# 2) Restart the stack
bash scripts/dev_local.sh down
bash scripts/dev_local.sh up --build
```

If you run host mode:

```bash
bash scripts/quickstart.sh
```

### SQLite path or permission issue

Check your configured DB path:

```bash
grep '^DATABASE_URL=' .env
```

It should be empty or start with `sqlite`, for example:

```env
DATABASE_URL=sqlite+aiosqlite:///~/.opentutor/data.db
```

If using Docker, the DB file is stored in the `sqlite_data` named volume.

### Unexpected non-SQLite database error in local mode

This usually means a stale non-SQLite `DATABASE_URL` is still configured.
Set it back to SQLite in `.env`, then restart the stack.

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

### Blank page at localhost:3001

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
2. CORS is configured: check `CORS_ORIGINS` in `.env` includes `http://localhost:3001`
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

### pip install fails on dependency build

OpenTutor local mode is SQLite-only. Usually this means a system build toolchain issue:

```bash
# macOS
xcode-select --install

# Ubuntu
sudo apt install build-essential python3-dev

# Windows
# Install "Microsoft C++ Build Tools" if wheels are unavailable
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

### SQLite file is locked or not writable (Windows)

```powershell
# Check current DB URL
Select-String -Path .env -Pattern '^DATABASE_URL='

# Ensure the parent directory exists and is writable
New-Item -ItemType Directory -Force -Path "$HOME\\.opentutor" | Out-Null
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
