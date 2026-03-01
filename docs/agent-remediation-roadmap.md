# OpenTutor Agent Remediation Roadmap

This document turns the current code audit into an execution plan. The goal is
to move OpenTutor from a strong AI-enhanced learning workspace to a more
coherent, durable agent system.

## 1. Runtime Unification

Problem:
- Chat and workflow entry points have not been using the same execution path.
- Tool calling, action markers, and reflection can diverge by endpoint.

Implementation:
- Force all entry points through the streaming-capable agent runtime.
- Normalize `[ACTION:*]` and tool status markers into structured state before
  persistence or workflow return values.
- Keep one shared token-accounting policy for direct-chat, ReAct function
  calling, and fallback text-mode tool use.

Success criteria:
- A workflow turn and a chat turn can use the same tools and produce the same
  cleaned assistant response for the same context.

## 2. Trustworthy Evidence Boundaries

Problem:
- Course retrieval, memory retrieval, and user history are distinct evidence
  types but are still easy to blur together.

Implementation:
- Keep content retrieval restricted to course materials only.
- Keep memory retrieval in its own pipeline and prompt section.
- Surface provenance in the UI: `course`, `memory`, `workflow`, `generated`.

Success criteria:
- Every answer can be explained by evidence type, not just by raw text.

## 3. Task Execution Layer

Problem:
- The system is still primarily response-oriented. It can suggest actions, but
  it does not yet manage durable tasks like a full agent.

Implementation:
- Introduce a task table with status, retries, approval state, result payload,
  and cancellation markers.
- Route long-running work such as plan generation, batch quiz generation,
  scrape/import, and review queues through durable tasks.
- Expose an activity timeline in the frontend rather than hiding everything in
  chat.

Success criteria:
- Users can see what the agent is doing, what is pending, and what completed or
  failed without staying inside a single chat stream.

## 4. Scene System Upgrade

Problem:
- Scenes are currently strong workspace presets, but not yet a real adaptive
  policy engine.

Implementation:
- Separate `UI layout preset`, `reasoning policy`, and `workflow policy`.
- Make scene recommendations depend on user goal, fatigue, deadlines, mastery,
  and recent failures.
- Add reversible scene suggestions with explicit rationale.

Success criteria:
- Scene changes affect strategy, not only tabs.

## 5. Safety and Sandboxing

Problem:
- Code execution is still app-level restricted execution, not a hardened
  sandbox.

Implementation:
- Move code execution into an isolated subprocess or container with hard CPU,
  memory, filesystem, and network limits.
- Add explicit execution approvals for side-effecting tools in future agent
  expansions.

Success criteria:
- Unsafe code execution is isolated from the API process and database process.

## 6. Evaluation and Regression Control

Problem:
- The codebase has good functional tests, but the agent itself lacks explicit
  evals for routing, retrieval quality, and intervention quality.

Implementation:
- Add offline eval fixtures for intent routing, scene switching, preference
  extraction, and evidence-grounded answering.
- Add golden transcripts for key learning flows.
- Track answer provenance, tool use, and failure reasons in structured logs.

Success criteria:
- Agent changes are judged by measurable quality, not just by "it feels better".

## 7. Product-Layer Changes Needed For A Strong Agent

Implementation themes:
- Add a task/activity panel instead of overloading chat.
- Show why a preference update or scene switch was suggested.
- Add plan ownership: goals, milestones, next best action, and review loops.
- Turn memory into a visible, editable learning profile rather than a hidden
  backend-only feature.

Success criteria:
- The user experiences sustained guidance, not just faster answers.
