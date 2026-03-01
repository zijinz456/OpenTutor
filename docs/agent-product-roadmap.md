# OpenTutor Zenus Product Agent Roadmap

This roadmap covers the work that still separates OpenTutor Zenus from a strong,
durable learning agent. It is intentionally execution-oriented: each phase has
deliverables, repository touch points, exit criteria, and validation gates.

## North Star

OpenTutor Zenus should behave like a goal-holding study operator rather than a smart
chat tab. That means:

- it owns durable goals, milestones, and next actions
- it asks for approval before side effects
- it can execute, observe, recover, and resume work
- it exposes its reasoning boundary, provenance, and task state in the UI
- it runs safely for multiple users with isolated state and execution

## Workstreams

### 1. Durable Agency
- Goal records, milestones, approvals, resumable task runs, retries, and task outcomes.
- Primary surfaces:
  `apps/api/services/activity/engine.py`,
  `apps/api/services/agent/orchestrator.py`,
  `apps/api/models/agent_task.py`,
  `apps/web/src/components/course/activity-panel.tsx`

### 2. Agent Cockpit
- A dedicated control surface for task state, pending approvals, plan history,
  provenance, and next-best-action prompts.
- Primary surfaces:
  `apps/web/src/components/chat/chat-panel.tsx`,
  `apps/web/src/store/chat.ts`,
  `apps/web/src/components/course/activity-panel.tsx`

### 3. Long-Horizon Guidance
- Goal decomposition, recurring study loops, progress reviews, forgetting-risk
  interventions, and proactive suggestions.
- Primary surfaces:
  `apps/api/services/workflow/`,
  `apps/api/services/scheduler/engine.py`,
  `apps/api/services/progress/`,
  `apps/api/services/memory/`

### 4. Trust, Safety, and Isolation
- Explicit execution approvals, hardened code sandboxing, multi-tenant
  boundaries, and auditable side effects.
- Primary surfaces:
  `apps/api/services/agent/container_sandbox.py`,
  `apps/api/services/auth/`,
  `apps/api/middleware/security.py`

### 5. Evaluation and Release Control
- Agent-specific regression gates for task completion, grounding, approval
  correctness, long transcript stability, and recovery behavior.
- Primary surfaces:
  `apps/api/services/evaluation/`,
  `tests/test_eval_regressions.py`,
  `tests/e2e/`,
  `.github/workflows/ci.yml`

## Phase 1: Task System To Agent System

Target window: 1 to 2 weeks

Deliverables:
- Add explicit approval states to durable tasks: `pending_approval`,
  `approved`, `rejected`, `cancel_requested`, `cancelled`.
- Persist structured per-step outputs, not just summaries.
- Add retry metadata and resumable checkpoints for multi-step plans.
- Split task types into `read_only`, `content_mutation`, `notification`,
  `external_side_effect`.

Repository changes:
- Extend the agent task model and routers.
- Add approval endpoints and task resume/cancel flows.
- Move step progress rendering from passive display to actionable controls.

Exit criteria:
- A background task can pause for approval and resume without losing context.
- A failed multi-step task can retry a single step instead of restarting the
  whole plan.
- Users can inspect inputs, outputs, and errors for each step from the UI.

Validation:
- API integration coverage for approval, reject, cancel, resume, and retry.
- Browser flow that creates a plan, pauses for approval, then resumes to
  completion.

## Phase 2: Agent Cockpit And Goal Ownership

Target window: 2 to 4 weeks

Deliverables:
- New cockpit panel for active goals, agent timeline, approvals, and next
  actions.
- Goal model with owner, objective, success metric, deadline, confidence, and
  current milestone.
- Visible provenance badges on answers and task outputs:
  `course`, `memory`, `workflow`, `user_input`, `generated`.
- Replace the chat-first mental model with task-first status when background
  work is active.

Repository changes:
- Add goal persistence and goal-to-task relationships.
- Expand frontend state for active goals and approval queue.
- Add richer activity/event schemas for the UI.

Exit criteria:
- A user can create or accept a goal and see all active work aligned to it.
- The system can recommend the next action and explain why it matters.
- Provenance is visible everywhere the model produces non-trivial output.

Validation:
- Goal CRUD API coverage.
- Browser flow that creates a goal, launches a plan from it, and shows the
  linked task timeline and provenance.

## Phase 3: Long-Horizon Study Loops

Target window: 3 to 5 weeks

Deliverables:
- Recurring study reviews driven by deadlines, mastery gaps, and forgetting
  risk.
- Goal review loop: `plan -> execute -> reflect -> replan`.
- Explicit "today", "this week", and "blocked" queues for the agent.
- Memory and preference surfaces become editable user-facing profile objects.

Repository changes:
- Extend scheduler jobs to generate durable tasks instead of ephemeral nudges.
- Connect progress/memory services into plan refresh decisions.
- Add UI for weekly review summaries and intervention history.

Exit criteria:
- The agent can wake up, generate a justified study agenda, and persist it as
  tasks without a fresh chat prompt.
- Users can edit or dismiss learned preferences and memory-derived assumptions.

Validation:
- Offline evals for next-best-action ranking and forgetting-driven suggestions.
- End-to-end flow covering a weekly review with generated tasks.

## Phase 4: Safety And Multi-Tenant Hardening

Target window: 2 to 4 weeks

Deliverables:
- Default side-effecting tools require approval tokens or policy grants.
- Code execution runs only inside constrained containers with CPU, memory,
  filesystem, and network controls enforced.
- Course, memory, notification, and task access is fully scoped by tenant.
- Audit log for tool invocation, approval actor, and side effect outcome.

Repository changes:
- Harden sandbox runtime and policy checks.
- Expand auth and course-access enforcement.
- Add durable audit records for side-effecting task steps.

Exit criteria:
- No side-effecting tool can run without an approval or policy decision.
- Tenant A cannot observe or mutate tenant B state through API, tasks, or
  background engines.

Validation:
- Security-focused integration tests for authorization boundaries.
- Sandbox regression coverage for blocked network/filesystem writes.

## Phase 5: Release Gates For Agent Quality

Target window: continuous, start immediately after Phase 1

Deliverables:
- Golden task transcripts for representative study goals.
- Recovery evals: retry, degraded provider, partial failure, approval timeout.
- Grounding evals that score provenance correctness and unsupported claims.
- Release scorecard that combines offline evals, DB integration, and browser
  task completion.

Exit criteria:
- A regression in task completion, grounding, or approval behavior fails CI.
- Agent changes can be compared by score, not by anecdote.

## Immediate Backlog

P0 shipped foundation:
- Task approval state machine with `approve`, `reject`, `cancel`, `resume`, and `retry`
- Per-step artifact persistence for multi-step plans
- Browser activity-panel flow covering approval and resume controls

P1 shipped foundation:
- Goal model, migration, and course-scoped CRUD API
- Activity-panel cockpit section for active goals, linked tasks, and approval inbox
- Goal-to-task linkage so queued background work can align to an active objective
- Provenance badges wired into chat replies and activity task cards

P2 shipped foundation:
- Weekly scheduler now enqueues durable `weekly_prep` tasks instead of running an ephemeral workflow
- Scheduler-created weekly review tasks attach to a durable goal and refresh its `current_milestone` / `next_action` on success

P1 remaining:
- Goal-sourced next-best-action recommendations
- Timeline-level grouping of task runs under each goal

P2 items:
- Editable memory/preference profile
- Side-effect tool approval policy

## Operating Metrics

Track these from the start of Phase 1:

- task completion rate
- approval turnaround time
- step retry success rate
- unsupported-claim rate
- grounded answer rate
- weekly active goals per active learner
- proactive task acceptance rate

## Release Rule

Do not market OpenTutor as a strong agent until all of the following are true:

- durable approvals and resumable tasks ship
- cockpit UI replaces chat-only task visibility
- proactive weekly review loop ships
- side-effecting execution is approval-gated and sandboxed
- CI enforces agent quality and grounding thresholds
