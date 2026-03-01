# OpenTutor Full Execution Plan

> Revised based on a deep code audit. Investigation revealed some "missing" features were actually already implemented (FSRS algorithm, MotivationAgent).
> This plan only targets **issues that truly need modification**.

---

## Phase 0: Make It Run Stably

### 0.1 LLM Call Timeout [H4]
**Problem**: OpenAIClient and AnthropicClient have no request timeout; requests hang indefinitely when LLM is unresponsive
**File**: `apps/api/services/llm/router.py`
**Changes**:
- OpenAIClient.__init__(): Add `timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10)`
- AnthropicClient.__init__(): Add `timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10)`
- stream_chat/chat/chat_with_tools: Confirm timeout is inherited from client level

### 0.2 Chat Markdown Rendering [H7]
**Problem**: chat-panel.tsx line 76 uses `whitespace-pre-wrap` to display plain text, does not render Markdown
**File**: `apps/web/src/components/chat/chat-panel.tsx`
**Changes**:
- Reuse the existing `MarkdownRenderer` component (`apps/web/src/components/course/markdown-renderer.tsx`)
- Replace `<div className="whitespace-pre-wrap">{message.content}</div>` with `<MarkdownRenderer content={message.content} />`
- Add chat-specific style tweaks (smaller font size, tighter spacing)

### 0.3 Unify Tool Result Truncation [H2]
**Problem**: base.py defines MAX_TOOL_RESULT_CHARS=8000, react_loop.py defines _TOOL_RESULT_CONTEXT_CHARS=4000
**File**: `apps/api/services/agent/tools/base.py:22`, `apps/api/services/agent/tools/react_loop.py:32`
**Changes**:
- Remove the local constant in react_loop.py
- Unify on base.py's MAX_TOOL_RESULT_CHARS (change to 6000 to balance information vs. context overhead)
- react_loop.py imports from base

### 0.4 Version Alignment
**Problem**: docker-compose.yml uses pg16, CI uses pg17; README says Python 3.12+, actually requires 3.11
**File**: `docker-compose.yml:5`, `README.md:70`
**Changes**:
- docker-compose.yml: `pgvector/pgvector:pg16` -> `pgvector/pgvector:pg17`
- README.md: `Python 3.12+` -> `Python 3.11` (note tiktoken compatibility)

### 0.5 Context Loading Parallelization [H1]
**Problem**: orchestrator.py load_context() runs three steps sequentially (preferences -> memories -> content), but comments claim parallel execution
**File**: `apps/api/services/agent/orchestrator.py`
**Changes**:
- Parallelize the three loading steps using independent db sessions or asyncio.gather()
- Note: Each step needs independent error handling; one failure should not block the others

### 0.6 Frontend Error Boundary [H5]
**File**: `apps/web/src/components/error-boundary.tsx` (new file)
**Changes**:
- Create React Error Boundary component
- Wrap main content area in layout.tsx
- Wrap each panel in course/[id]/page.tsx

### 0.7 Scene Detection Deduplication [H3]
**Problem**: load_context() and SceneAgent each have their own scene detection logic
**File**: `apps/api/services/agent/orchestrator.py`, `apps/api/services/agent/scene_agent.py`
**Changes**:
- Extract `detect_scene()` as a standalone function in scene_agent.py
- orchestrator.py's load_context() calls the scene_agent function directly

### 0.8 Fatigue Detection Improvement
**Problem**: orchestrator.py hardcodes 4 regex patterns with false positive risk
**File**: `apps/api/services/agent/orchestrator.py`
**Changes**:
- Add more signal patterns (English, emoji)
- Add "positive signal" decay (reduce fatigue score when "I understand" / "got it" is detected)
- Extract thresholds and patterns to configuration

---

## Phase 1: Core Educational Capability Completion

### 1.1 Connect FSRS to LearningProgress [B1+D5]
**Current state**: FSRS algorithm is fully implemented (`services/spaced_repetition/fsrs.py`), but LearningProgress model
is missing complete FSRS fields (only has ease_factor, interval_days, next_review_at; missing difficulty, stability, reps, lapses, state)
**File**: `apps/api/models/progress.py`, `apps/api/services/progress/tracker.py`
**Changes**:
- Add missing fields to LearningProgress: difficulty, stability, reps, lapses, last_review, fsrs_state
- Add Alembic migration for new columns
- tracker.py's `update_quiz_result()` calls FSRS `review_card()` to update scheduling
- Ensure next_review_at is correctly updated after each answer submission

### 1.2 Diagnostic Pair Generation System [B3]
**Current state**: ReviewAgent reads diagnostic pair data (diagnosis, original_layer, clean_status),
PracticeProblem has parent_problem_id + is_diagnostic fields, but no generation code exists
**File**: New file `apps/api/services/diagnosis/pair_generator.py`
**Changes**:
- Create `generate_diagnostic_pair(problem_id)`: Generate simplified "clean" version of incorrectly answered questions
- Simplification strategy: Preserve core concept, remove distractors/traps, lower difficulty layer
- Compare results between original and simplified questions to infer error cause (fundamental_gap vs trap_vulnerability vs carelessness)
- In quiz submission flow, wrong answers automatically trigger diagnostic pair generation (async background)
- WrongAnswer.diagnosis field populated by comparison results

### 1.3 Knowledge State Tracking (Simplified BKT) [D6]
**Current state**: mastery_score = weighted decay of recent 20 results, no probabilistic model
**File**: New file `apps/api/services/learning_science/knowledge_tracer.py`
**Changes**:
- Implement simplified BKT (4-parameter model):
  - P(L0): Initial mastery probability (estimated from first-attempt accuracy)
  - P(T): Learning transition probability (estimated from consecutive correct count)
  - P(G): Guess probability (estimated from number of multiple-choice options, default 0.25)
  - P(S): Slip probability (estimated from frequency of wrong answers at high mastery)
- Calculate P(Ln) = P(Ln-1|evidence) as the true mastery probability
- Store in LearningProgress mastery_score (replacing simple ratio)
- Call in tracker.py update_quiz_result()

### 1.4 Adaptive Difficulty Selection [D7]
**Current state**: ExerciseAgent has 3 difficulty layers, but selection relies on LLM judgment
**File**: `apps/api/services/agent/exercise.py`, new file `apps/api/services/learning_science/difficulty_selector.py`
**Changes**:
- Implement BKT mastery-based difficulty selection algorithm:
  - P(L) < 0.4 -> Layer 1 (fundamental)
  - 0.4 <= P(L) < 0.7 -> Layer 2 (transfer)
  - P(L) >= 0.7 -> Layer 3 (trap)
- gap_type also participates in selection: fundamental_gap -> force Layer 1
- ExerciseAgent.build_system_prompt() injects recommended difficulty layer
- Preserve LLM flexibility (recommendation, not enforcement)

### 1.5 Forgetting Curve Prediction [D9]
**File**: Extend `apps/api/services/spaced_repetition/fsrs.py`
**Changes**:
- Leverage the existing `_retrievability()` function: R(t) = (1 + t/(9*S))^-1
- Add `predict_forgetting(progress_list)` -> returns estimated forgetting time for each knowledge point
- Add API endpoint `GET /api/progress/courses/{id}/forgetting-forecast`
- Add "Forgetting Forecast" view to the frontend Progress panel

---

## Phase 2: Agent Autonomy Enhancement

### 2.1 Multi-step Task Execution [D1]
**Current state**: AgentContext has TaskPhase but only handles single turns; AgentTask model exists but is underutilized
**File**: New file `apps/api/services/agent/task_planner.py`, modify orchestrator.py
**Changes**:
- Create TaskPlanner: Decompose complex requests into multi-step AgentTasks
  - "Help me prepare for the exam" -> [check progress, find weak points, generate exercises, schedule review]
  - Each step is associated with a specialist agent
- Extend orchestrate_stream(): Launch multi-step mode when complex intent is detected
- Add new SSE event type "plan_step" to inform the frontend of current execution step
- Frontend displays execution progress bar

### 2.2 Cross-Agent Collaboration (Delegation Protocol) [D2]
**File**: Modify `apps/api/services/agent/base.py`, `orchestrator.py`
**Changes**:
- Add `delegate(target_agent, sub_context)` method to BaseAgent
- Return sub-agent results as tool input for the current agent
- Typical chain: ExerciseAgent generates question -> user answers wrong -> ReviewAgent analyzes -> AssessmentAgent evaluates
- Track delegation chain via AgentContext.delegated_agent

### 2.3 Proactive Push Notification System [D3]
**Current state**: APScheduler + in-memory notification storage
**File**: New notification persistence model + WebSocket endpoint
**Changes**:
- Create Notification database model (replacing in-memory storage)
- Add WebSocket endpoint `/api/ws/notifications`
- Extend scheduler jobs:
  - `daily_suggestion_job()`: Push review reminders based on forgetting curve
  - `inactivity_alert_job()`: Push encouragement after N days of inactivity
  - `goal_progress_job()`: Study plan progress notifications
- Frontend: NotificationCenter component + toast notifications

### 2.4 ReAct Loop Deepening [D4]
**File**: `apps/api/services/agent/tools/react_loop.py`, `react_mixin.py`
**Changes**:
- Increase react_max_iterations default to 5
- Add observation-driven branching:
  - Tool returns empty/error -> try alternative tool
  - Result quality score < threshold -> auto-refine query
- Add education tools:
  - `check_prerequisites(topic)`: Check whether prerequisite knowledge is mastered
  - `suggest_related_topics(topic)`: Recommend related knowledge points
  - `get_forgetting_forecast(user_id, course_id)`: Get forgetting forecast

### 2.5 Evaluation Framework [D15]
**File**: New directory `apps/api/services/evaluation/`
**Changes**:
- Create offline eval framework:
  - `eval_routing.py`: Intent classification accuracy (golden intent -> actual intent)
  - `eval_retrieval.py`: RAG recall quality (golden docs -> retrieved docs)
  - `eval_response.py`: Response quality (LLM-as-judge: correctness, relevance, helpfulness)
- Create golden transcript fixtures
- Add CI eval step (optional, similar to llm-integration)
- Track metrics over time

---

## Phase 3: Product Experience Leap

### 3.1 Multimodal Input [D10]
**File**: New directory `apps/api/services/multimodal/`, modify chat router
**Changes**:
- Image input: Leverage GPT-4o / Claude vision capabilities
  - Frontend: Add image upload button to chat input
  - Backend: Chat request supports image attachments
  - LLM client: OpenAIClient/AnthropicClient support image_url message format
- Math formula OCR: Call vision model to recognize handwritten/photographed formulas
- Chart comprehension: Auto-analyze uploaded charts/diagrams

### 3.2 PWA + Offline Support [D12+D13]
**File**: `apps/web/public/manifest.json` (new file), service worker
**Changes**:
- Add Web App Manifest (icon, theme, display: standalone)
- Implement Service Worker: Cache static assets + course data
- Display cached notes/flashcards when offline
- App install prompt UI

### 3.3 Analytics Dashboard [D14]
**File**: `apps/web/src/app/analytics/page.tsx`
**Changes**:
- Learning trend line charts (daily study time, accuracy rate)
- Knowledge map heatmap (mastery level visualization)
- Forgetting prediction curves (based on FSRS retrievability)
- Error pattern analysis (category distribution pie chart)
- Use recharts or chart.js library

### 3.4 Memory System Upgrade [D16]
**File**: `apps/api/services/memory/pipeline.py`
**Changes**:
- Consolidation enhancement:
  - Similar memory merging (not just dedup, but semantic fusion)
  - Episodic memory: Chain fragmented memories from consecutive conversations into learning experiences
  - Build "learner profile" prompt section based on memories
- Memory visibility:
  - API: GET /api/memory/profile -> returns learner profile
  - Frontend: Add "Learner Profile" view/edit page in Settings

### 3.5 Learning Path Optimization [D8]
**File**: New file `apps/api/services/learning_science/path_optimizer.py`
**Changes**:
- Build DAG based on KnowledgePoint.dependencies
- Topological sort to determine learning order
- Add mastery weights: skip mastered items, prioritize weak ones
- Add time constraints: critical path analysis before deadlines
- PlanningAgent uses optimized path to generate plans

---

## Phase 4: Competitive Moat

### 4.1 Security Hardening [D18]
**Changes**:
- Add security headers via FastAPI middleware (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- Prompt injection detection: Input guard checks at orchestrator entry point
- Audit log: Record all API calls + agent decisions to audit table
- Rate limiting: Use slowapi or custom middleware

### 4.2 A/B Testing Framework [D17]
**Changes**:
- Experiment model: name, variants, allocation, metrics
- User grouping: Assign variant based on user_id hash
- Metric collection: mastery_score changes, session duration, accuracy changes
- Analysis endpoint: GET /api/experiments/{id}/results

### 4.3 Knowledge Graph Deepening
**Changes**:
- Reasoning capabilities based on KnowledgePoint + dependencies
- Frontend: Interactive force-directed graph (D3.js)
- Click nodes to display mastery level and recommended exercises
- Path recommendation: Optimal path from current position to target knowledge point

### 4.4 Collaborative Learning Foundation [D11]
**Changes**:
- Sharing functionality: Generate share links for notes/flashcards/study plans
- Teacher view: View student group progress (requires AUTH_ENABLED=true)
- Future: Real-time collaboration, group study

---

## Validation Strategy

After each Phase is completed:
1. Run existing tests: `pytest tests/test_api_unit_basics.py tests/test_services.py`
2. Run integration tests: `pytest tests/test_api_integration.py`
3. Check TypeScript compilation: `cd apps/web && npm run build`
4. Add corresponding tests for new features
5. Manually verify key user flows
