# Local Single-User Deployment

OpenTutor is intended to run locally in the same style as OpenClaw:

- `AUTH_ENABLED=false`
- `DEPLOYMENT_MODE=single_user`
- no end-user sign-in UI
- one local owner profile auto-bound on the backend

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

Or with Docker:

```bash
cp .env.example .env
bash scripts/check_local_mode.sh --skip-api
bash scripts/dev_local.sh up --build
```

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
