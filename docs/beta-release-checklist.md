# Beta Release Checklist (Local Single-User)

Use this checklist before marking a commit as a GitHub beta release candidate.
Automation runbook: `docs/release-closeout-runbook.md`

## 1) First-run and startup gates

- [x] `cp .env.example .env`
- [x] `bash scripts/check_local_mode.sh --env-file .env --skip-api`
- [x] `bash scripts/quickstart.sh` succeeds on a clean host
- [x] API and web are both reachable:
  - [x] `http://localhost:8000/api/health`
  - [x] `http://localhost:3001`

## 2) CI parity and regression gates

- [x] `bash scripts/dev_local.sh verify-host --ci-parity`
- [x] If stack is running locally, verify strict benchmark passes:
  - [x] `STRICT_BENCHMARK=1 bash scripts/run_regression_benchmark.sh`
- [x] Frontend quality gates:
  - [x] `cd apps/web && npm run lint`
  - [x] `cd apps/web && npm run build`

## 3) Coverage and quality policy (current beta phase)

- [x] Global pytest coverage gate is `--cov-fail-under=25`
- [ ] Next cycle target documented: raise coverage gate to `30+`
- [ ] Frontend: `cd apps/web && npx vitest run` passes
- [x] No `-o addopts=` override in CI "Run API unit tests" step
- [ ] `except Exception` count under 30 (`grep -rn "except Exception\|except:" apps/api --include="*.py" | wc -l`)
- [ ] No source file exceeds 400 lines

## 4) Known limitations must be explicit

- [ ] README includes host support matrix (macOS + Linux first-class, Windows not first-class in this cycle)
- [ ] README marks experimental capabilities (LOOM/LECTOR/advanced autonomous flows)
- [ ] Troubleshooting entry is linked from quickstart sections

## 5) Security checks

- [ ] `pre-commit run --all-files` passes (no leaked secrets)
- [ ] `grep -rn "sk-" . --include="*.env*"` returns zero matches
- [ ] Auth warning appears when `ENVIRONMENT=production` and `AUTH_ENABLED=false`

## 6) Final release call

- [x] Two clean-environment reruns completed (no local state reuse assumptions)
- [x] CI pipeline green on the release commit (5 stages: lint, backend tests, frontend tests, build, benchmark)
- [ ] Tag release notes with current known limitations and experimental features
- [ ] Performance benchmark passes: `python scripts/benchmark.py --threshold-ms 500`

## 7) Closeout automation commands

- [x] Round 1 rehearsal: `bash scripts/release_rehearsal_round.sh --round round-1`
- [x] Round 2 rehearsal: `bash scripts/release_rehearsal_round.sh --round round-2`
- [x] CI stability window (main): `bash scripts/check_ci_stability.sh --repo owner/repo --branch main --workflow ci.yml --windows 2`
- [ ] Optional GitHub workflow dispatch: `.github/workflows/release-readiness.yml`

### Latest closeout evidence (2026-03-10)

- Round 1 report: `tmp/release-rehearsal/round-1/summary.md` (Passed: 8, Failed: 0, Skipped: 0)
- Round 2 report: `tmp/release-rehearsal/round-2/summary.md` (Passed: 8, Failed: 0, Skipped: 0)
- CI update: `main` runs `#63` (`22901607317`) and `#64` (`22902121131`) both succeeded for `ci.yml` on `push`.
- CI stability command passed on 2026-03-10:
  - `bash scripts/check_ci_stability.sh --repo zijinz456/OpenTutor --branch main --workflow ci.yml --windows 2`
