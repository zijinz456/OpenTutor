# Bug Triage and SLA (Public Beta)

This SLA is for the **local single-user public beta** channel.

## Severity Levels

| Severity | Definition | Example |
|---|---|---|
| `P0` | Core learning flow blocked or data-loss/security risk | Chat hard-crash, startup unusable, destructive data corruption |
| `P1` | Major feature broken with no clean workaround | Upload or review pipeline consistently fails |
| `P2` | Partial degradation with workaround | Intermittent UI failure or non-critical API regression |
| `P3` | Minor bug or polish issue | Copy mismatch, visual alignment, low-impact edge case |

## Response Targets

| Severity | Triage Start | First Mitigation/Plan | Resolution Target |
|---|---|---|---|
| `P0` | within 4 hours | within 8 hours | hotfix or rollback within 24 hours |
| `P1` | within 1 business day | within 2 business days | fix in current beta cycle |
| `P2` | within 3 business days | within 5 business days | prioritize by impact and cluster |
| `P3` | weekly triage batch | backlog decision in weekly review | best-effort |

## Triage Rules

1. Every issue gets a severity label (`P0`-`P3`) and one owner.
2. Reproducible steps + environment are required before severity lock.
3. `P0` opens a hotfix branch immediately; if unresolved in 2 hours, rollback decision is mandatory.
4. `P1`+ require a linked regression test or explicit contract-update note in the fix PR.
5. Reopened bugs are escalated by one severity level by default.

## Issue Labels

- `bug`
- `needs-triage`
- `P0`, `P1`, `P2`, `P3`
- `regression` (if previously working)

## Daily Beta Triage Cadence

- 1x daily async triage pass for new issues
- 1x daily update to open `P0`/`P1` threads
- Weekly backlog review for `P2`/`P3`
