#!/usr/bin/env bash
# OpenTutor — One-line install script
# Usage: curl -sSL https://raw.githubusercontent.com/<org>/opentutor/main/scripts/install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/<org>/opentutor.git"
INSTALL_DIR="${OPENTUTOR_DIR:-$HOME/opentutor}"

info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m  %s\n" "$*"; }
fail()  { printf "\033[1;31m[FAIL]\033[0m  %s\n" "$*"; exit 1; }

# ── 1. Check prerequisites ──

info "Checking prerequisites..."

command -v git   >/dev/null 2>&1 || fail "git not found. Install: https://git-scm.com"
command -v curl  >/dev/null 2>&1 || fail "curl not found. Install via your package manager"
command -v docker >/dev/null 2>&1 || fail "Docker not found. Install: https://docs.docker.com/get-docker/"

if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    fail "docker compose not found. Install Docker Desktop or docker-compose."
fi

ok "Prerequisites OK (git, docker, $COMPOSE)"

# ── 2. Clone or update ──

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR..."
    cd "$INSTALL_DIR" && git pull --ff-only
else
    info "Cloning OpenTutor to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── 3. Generate .env if missing ──

if [ ! -f .env ]; then
    info "Creating default .env..."
    cat > .env <<'EOF'
# OpenTutor Configuration
# LLM provider: ollama (local), openai, anthropic, deepseek, lmstudio
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b

# Uncomment and set if using cloud providers:
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Auto-setup on first run
APP_AUTO_CREATE_TABLES=true
APP_AUTO_SEED_SYSTEM=true
APP_RUN_SCHEDULER=true
APP_RUN_ACTIVITY_ENGINE=true
EOF
    ok ".env created with defaults (local Ollama mode)"
else
    ok ".env already exists — keeping your configuration"
fi

# ── 4. Start services ──

info "Starting OpenTutor..."
$COMPOSE up -d --build

# ── 5. Wait for health ──

info "Waiting for API to be ready..."
for _ in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    ok "API is healthy"
else
    warn "API not ready yet — check logs with: docker compose logs api"
fi

# ── 6. Done ──

echo ""
ok "OpenTutor is running!"
echo ""
info "  Web UI:  http://localhost:3001"
info "  API:     http://localhost:8000/api"
info "  Docs:    http://localhost:8000/docs"
echo ""
info "A demo course has been auto-created for you."
info "Open http://localhost:3001 to start learning!"
echo ""
info "Useful commands:"
info "  Stop:    cd $INSTALL_DIR && $COMPOSE down"
info "  Logs:    cd $INSTALL_DIR && $COMPOSE logs -f"
info "  Update:  cd $INSTALL_DIR && git pull && $COMPOSE up -d --build"
