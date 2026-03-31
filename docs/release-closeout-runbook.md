# Release Closeout Runbook (Local Single-User Beta)

Use this checklist before tagging a public beta release.

## 1. Preflight

- Sync latest `main`
- Ensure `.env` is in local single-user mode:
  - `AUTH_ENABLED=false`
  - `DEPLOYMENT_MODE=single_user`
- Ensure Python 3.11 and Node 20 are available

## 2. Automated Gates

Run from repository root:

```bash
.venv/bin/python -m pytest tests -q
cd apps/web && npm run lint && npx vitest run
```

Then run CI-parity host verification:

```bash
bash scripts/dev_local.sh verify-host --ci-parity
```

## 3. Browser Regression

Run Playwright E2E:

```bash
npx playwright test --project=chromium --ignore-snapshots
```

## 4. Smoke Flow (Manual)

- Create a course
- Upload one document
- Ask one grounded chat question
- Complete one quiz/flashcard interaction
- Open analytics/progress pages
- Export at least one artifact

## 5. Docs and Versioning

- Update `CHANGELOG.md`
- Verify README feature and setup sections are current
- Ensure release notes reference existing docs only

## 6. Tag and Publish

- Create annotated tag
- Push tag
- Publish GitHub release notes from `CHANGELOG.md`

## 7. Rollback Readiness

- Confirm previous stable tag exists
- Confirm rollback helper works:

```bash
bash scripts/rollback_to_tag.sh <stable-tag>
```
