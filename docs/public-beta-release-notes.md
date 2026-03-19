# OpenTutor Public Beta Release Notes

Current channel: **Local Single-User Public Beta**

## Scope

- Target: technically literate learners running OpenTutor locally
- Supported first-class platforms: macOS + Linux
- Windows: community-supported
- Non-goal for this channel: multi-user SaaS/classroom deployment

## What's Included

- Local-first adaptive learning workspace
- Chat tutoring with source-grounded responses
- Notes/quiz/flashcards/progress/plan blocks
- FSRS-based review workflows
- Optional graph-assisted LOOM/LECTOR flows (experimental)

## Experimental Features

- `LOOM` knowledge graph extraction and mastery linkages
- `LECTOR` semantic review ordering and recommendation overlays
- Advanced autonomous adaptation flows powered by behavioral signals

These features are available but may change quickly. Behavior may vary across content quality and LLM setup.

## Known Limitations (Beta)

- Mobile experience is incomplete for some workspace layouts
- Runtime quality/latency depends on local model/provider/hardware
- Cloud deployment paths exist, but this beta is validated primarily for local single-user workflows

## Validation Gates For This Beta

- Backend regression suite passes
- Frontend lint + tests + production build pass
- SQLite local integration and API smoke gates pass in CI
- Browser E2E suite passes in CI
- Coverage gate: `--cov-fail-under=45`

## Rollback Policy

- Any confirmed `P0` issue that cannot be hotfixed within 2 hours triggers rollback
- Rollback target: previous stable git tag
- Helper script: `bash scripts/rollback_to_tag.sh <stable-tag>`

## Fast Debug Links

- Troubleshooting: [docs/troubleshooting.md](troubleshooting.md)
- Local mode guardrails: [docs/local-single-user.md](local-single-user.md)
- Release closeout runbook: [docs/release-closeout-runbook.md](release-closeout-runbook.md)
- Bug severity & SLA: [docs/bug-triage-sla.md](bug-triage-sla.md)
