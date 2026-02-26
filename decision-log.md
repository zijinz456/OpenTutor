# Decision Log

All autonomous decisions made during the build process.

## Decision 1: Monorepo structure
- **Date:** 2026-02-26
- **Decision:** Use `apps/web` and `apps/api` monorepo structure per spec
- **Rationale:** Spec Section 7 explicitly defines this structure
- **Alternative:** Separate repos — rejected, spec says monorepo

## Decision 2: Single-user mode
- **Date:** 2026-02-26
- **Decision:** No authentication system, single local user
- **Rationale:** Spec explicitly says "单用户模式（本地部署）", Phase 0 does not include multi-user auth
- **Alternative:** JWT auth — rejected per spec

## Decision 3: SQLAlchemy + Alembic for ORM
- **Date:** 2026-02-26
- **Decision:** Use SQLAlchemy 2.0 async + Alembic migrations
- **Rationale:** Industry standard for FastAPI + PostgreSQL, spec mentions Alembic directory
- **Alternative:** Raw SQL — too verbose; Tortoise ORM — less ecosystem support

## Decision 4: MVP preference cascade = 3 layers
- **Date:** 2026-02-26
- **Decision:** Phase 0 uses 3-layer cascade (temporary → course → global → default)
- **Rationale:** Spec Phase 0 explicitly says "MVP 先 3 层"
- **Alternative:** Full 7-layer — deferred to Phase 1 per spec

## Decision 5: LLM provider via environment variables
- **Date:** 2026-02-26
- **Decision:** Use environment variable to switch LLM provider (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
- **Rationale:** Spec says "LLM统一接口(环境变量切换)" for Phase 0-A
- **Alternative:** LiteLLM — deferred to Phase 1 per spec
