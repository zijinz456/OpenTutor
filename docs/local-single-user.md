# Local Single-User Deployment

OpenTutor is intended to run locally in the same style as OpenClaw:

- `AUTH_ENABLED=false`
- `DEPLOYMENT_MODE=single_user`
- no end-user sign-in UI
- one local owner profile auto-bound on the backend

For the current local beta target, a "ready" stack also means:

- the schema is ready
- a real LLM provider is reachable (`llm_status=ready`)
- sandbox availability is optional, but code execution features stay disabled without Docker or Podman

## What this means

- You do not need `login/register/refresh` to use the app locally.
- The backend resolves a local owner user automatically.
- Frontend requests should work without browser auth state.
- If you later experiment with JWT auth, treat that as a separate deployment mode, not the default workflow.

## Required config

Your `.env` should keep these values:

```env
AUTH_ENABLED=false
DEPLOYMENT_MODE=single_user
```

## Fast sanity check

Run this before debugging strange request/auth behavior:

```bash
bash scripts/check_local_mode.sh
```

It verifies:

- `.env` is still configured for local mode
- the running API reports `single_user`
- the running API reports `auth_enabled=false`

## Recommended startup flow

```bash
cp .env.example .env
bash scripts/check_local_mode.sh --skip-api
bash scripts/quickstart.sh
```

The local stack is SQLite-only by default. Keep `DATABASE_URL` as a SQLite URL, for example `sqlite+aiosqlite:///~/.opentutor/data.db`.

Or with Docker:

```bash
cp .env.example .env
bash scripts/check_local_mode.sh --skip-api
bash scripts/dev_local.sh up --build
```

If `8000` or `3001` is already in use, publish the Docker stack on alternate ports:

```bash
API_PORT=38000 WEB_PORT=33000 bash scripts/dev_local.sh up --build
API_PORT=38000 WEB_PORT=33000 bash scripts/dev_local.sh beta-check
```

## Local beta gate

Run this before calling a build "ready" for the technical-user local beta:

```bash
bash scripts/dev_local.sh beta-check
```

It fails if:

- local single-user mode drifted
- the running stack cannot reach a real LLM provider
- the API/database runtime is unreachable

When Docker is running, the script resolves the compose-published API and web ports automatically before it runs checks.

For release-candidate parity with CI test gates, also run:

```bash
bash scripts/dev_local.sh verify-host --ci-parity
```

Current beta-phase coverage gate is `35`. The next target after this stabilization cycle is `45+`.

For final release closeout, run `scripts/quickstart.sh` on a clean machine and verify all health checks pass.

## Common mistakes

### `AUTH_ENABLED=true`

This switches the backend into JWT mode. The current local product flow does not expose a full login UI, so this usually creates confusing 401s.

### `DEPLOYMENT_MODE=multi_user`

This changes ownership and request resolution semantics. For local development, it adds complexity without solving a real problem.

### Debugging request failures without checking deployment mode first

If auth/deployment flags drift, the symptoms often look unrelated:

- uploads fail with 401/403
- chat or voice stops working
- settings pages partially load

Run `bash scripts/check_local_mode.sh` first.
The Docker-based local stack now installs the lighter core Python dependency set
by default. If you need the full integration/tooling surface inside containers,
set `API_PYTHON_REQUIREMENTS=requirements-full.txt` before running
`bash scripts/dev_local.sh up --build`.

For host-run local inference backends, the Docker API container uses
`host.docker.internal` automatically. Override with
`DOCKER_OLLAMA_BASE_URL`, `DOCKER_LMSTUDIO_BASE_URL`,
`DOCKER_VLLM_BASE_URL`, or `DOCKER_TEXTGENWEBUI_BASE_URL` if needed.
