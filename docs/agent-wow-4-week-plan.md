# OpenTutor 4-Week Agent Wow Plan

This plan is the short-term execution path for turning OpenTutor from a strong
learning workbench into a talk-worthy agent. It deliberately narrows scope.

## Product Promise

By the end of week 4, a new learner should be able to:

1. upload or create a course
2. set one concrete goal
3. accept the agent's recommended next action
4. watch the agent queue and complete durable work
5. review a concrete outcome and immediately continue to the next step

If that loop is not obviously better than chat, nothing else matters.

## The Only Hero Flow

`goal -> next action -> queue -> execute -> review -> next action`

All product, API, and UI work in this sprint should strengthen that loop.

## Kill List

Do not spend the next 4 weeks on these unless they directly unblock the hero
flow:

- generic chat polish
- extra specialist agents without a visible user payoff
- new side panels that duplicate activity state
- broad multi-user/platform ambitions
- deeper customization of memory/preferences before the main loop feels alive

## Week 1: Make The Agent The Default Surface

Objective:
Make goal ownership and next-action queueing the first thing users notice on a
course page.

Deliverables:
- Ship a persistent "Agent Focus" surface on the course page.
- Make `next action` queueing one click from the main course view.
- Ensure missing DB schema fails with a direct migration hint instead of a
  generic API failure.
- Add a repo-native host migration command so first-run recovery is obvious.

Primary touch points:
- `apps/api/routers/goals.py`
- `apps/api/routers/tasks.py`
- `apps/api/services/activity/engine.py`
- `apps/web/src/app/course/[id]/page.tsx`
- `apps/web/src/components/course/activity-panel.tsx`
- `apps/web/src/components/course/agent-focus-strip.tsx`
- `scripts/dev_local.sh`

Exit gate:
- A new course can go from `goal created` to `durable task queued` without
  opening chat.
- `verify-host` points directly to migrations when schema is missing.

## Week 2: Close The Execution Loop

Objective:
Make queued work feel like the product, not a background implementation detail.

Deliverables:
- Group durable tasks into `Now`, `Waiting`, and `Completed` states in the
  activity cockpit.
- After task completion, always write back a concrete `review` payload:
  outcome, blockers, next recommended action, and linked goal update.
- Make the completion card immediately queueable into the next task.
- Add one browser flow that covers `goal -> queue -> complete -> queue follow-up`.

Primary touch points:
- `apps/api/services/activity/engine.py`
- `apps/api/services/activity/tasks.py`
- `apps/web/src/components/course/activity-panel.tsx`
- `tests/e2e/activity-tasks.spec.ts`

Exit gate:
- Completed work always produces a visible review artifact.
- At least one follow-up action can be queued from the completion UI with one
  click.

## Week 3: Add A Discussion-Worthy Rescue Mode

Objective:
Give the product one sharp use case that people will show to others.

Deliverables:
- Introduce a deadline-driven "Study Rescue" path when an assignment or exam is
  within 7 days.
- Turn rescue mode into a branded, visible entry point rather than a hidden
  workflow.
- Queue a multi-step plan that explicitly covers `what to do today`,
  `what can be skipped`, and `what is highest risk`.
- Add offline eval coverage for rescue recommendations and queue quality.

Primary touch points:
- `apps/api/routers/goals.py`
- `apps/api/services/spaced_repetition/forgetting_forecast.py`
- `apps/api/services/agent/task_planner.py`
- `apps/web/src/components/course/agent-focus-strip.tsx`
- `tests/test_eval_regressions.py`

Exit gate:
- A learner with a near-term deadline can get a credible rescue plan without
  typing a custom prompt.
- The product can explain why that rescue plan took priority.

## Week 4: Reduce Friction And Create Talkability

Objective:
Package the loop so people can run it, trust it, and share the result.

Deliverables:
- Keep the self-hosted beta path solid: preflight, migration, health, and
  verification must all point to the next fix directly.
- Decide on one mainstream distribution path:
  hosted preview for non-technical users, or a wrapped desktop build for local
  users. Do not position raw Docker as the mass-market answer.
- Add a shareable output surface: a review card, rescue plan summary, or
  progress snapshot that is worth posting or forwarding.
- Define a release scorecard for the hero flow.

Primary touch points:
- `README.md`
- `docs/troubleshooting.md`
- `scripts/dev_local.sh`
- `apps/web/src/components/course/*`
- `tests/test_api_integration.py`
- `tests/e2e/`

Exit gate:
- A technically literate user can get to a working local beta without guesswork.
- A non-technical observer can understand the agent's value from one screenshot
  or short demo clip.

## Metrics That Matter

Track these every week:

- percent of active courses with an explicit goal
- percent of next-action cards that get queued
- durable task completion rate
- follow-up queue rate after task completion
- rescue-mode acceptance rate
- time from course creation to first completed agent task

## Ship Rule

Call this sprint successful only if all of the following are true:

- the course page is visibly task-first when durable work exists
- the agent can recommend, queue, and complete the next action end-to-end
- rescue mode works for a near-term deadline
- local beta setup failures point to a direct fix instead of a generic crash
- at least one output artifact is shareable enough to create discussion
