# Architecture Decision Records (ADRs)

## ADR-001: FSRS-4.5 for Spaced Repetition

**Status:** Accepted
**Date:** 2026-01-15

**Context:** Need an evidence-based algorithm for flashcard scheduling that adapts to individual learners.

**Decision:** Use FSRS-4.5 (Free Spaced Repetition Scheduler) instead of SM-2 or Leitner.

**Rationale:**
- FSRS-4.5 has demonstrated 30%+ improvement in retention over SM-2 in Anki benchmarks
- Models memory stability and retrievability explicitly (not just ease factor)
- Parameters can be personalized per-user via gradient descent on review history
- Open-source algorithm with active research community

**Implementation:** `apps/api/services/spaced_repetition/fsrs.py` — pure Python implementation with 17 default parameters (FSRS-4.5 weights). `FSRSCard` stores `stability`, `difficulty`, `reps`, `lapses`, `state` (new/learning/review/relearning), and `last_review`. Rating scale: 1=Again, 2=Hard, 3=Good, 4=Easy.

**Core formulas:**
- Retrievability: `R(t) = (1 + t / (9 × S))^(-1)` where S = stability (days)
- Difficulty: clamped to [1, 10] with mean reversion toward initial difficulty
- Stability: rating-dependent update with hard_penalty (w[15]) and easy_bonus (w[16])

**Rejected alternatives:**
- SM-2 (Anki default): Static ease factor without explicit memory model
- Leitner boxes: No per-card stability tracking, crude difficulty adaptation

**Related modules:**
- `forgetting_forecast.py` — predicts when each concept drops below 90% retention
- `flashcards.py` — FSRS-backed flashcard CRUD and review session management

---

## ADR-002: BKT with EM for Knowledge Tracing

**Status:** Accepted
**Date:** 2026-01-20

**Context:** Need to estimate per-concept mastery probability from quiz interactions.

**Decision:** Use Bayesian Knowledge Tracing (BKT) with Expectation-Maximization for parameter fitting.

**Rationale:**
- BKT is the most validated knowledge tracing model in educational data mining
- EM fitting allows per-concept parameter personalization without labeled training data
- Simpler than deep learning approaches (DKT) while still effective for our scale
- Parameters (p_init, p_learn, p_slip, p_guess) are interpretable for debugging

**Implementation:** `apps/api/services/learning_science/knowledge_tracer.py` (BKT inference), `bkt_trainer.py` (EM parameter fitting via pyBKT). ConceptMastery model stores per-concept posterior probability.

**Two-layer architecture:**
- Layer 1 (always available): Heuristic parameter estimation from answer patterns — P(L0) from first-attempt correctness, P(T) from wrong→correct transitions, P(G) from question type (TF=0.5, MC=0.25, SA=0.05), P(S) from correct→wrong transitions
- Layer 2 (when ≥15 observations): EM-trained pyBKT parameters cached per-concept. `compute_mastery_adaptive()` transparently upgrades when trained params available

**Core update formula (Bayes rule + learning opportunity):**
```
if correct: p_l_post = p_l × (1 - p_s) / [p_l × (1 - p_s) + (1 - p_l) × p_g]
if wrong:   p_l_post = p_l × p_s / [p_l × p_s + (1 - p_l) × (1 - p_g)]
p_l_new = p_l_post + (1 - p_l_post) × p_t  # Learning opportunity
```

**Rejected alternative:** Deep Knowledge Tracing (DKT) — too complex for our scale, parameters not interpretable for debugging

**Related modules:**
- `difficulty_selector.py` — maps BKT P(L) to difficulty layer (1-3) using Vygotsky's ZPD
- `velocity_tracker.py` — learning speed metrics from mastery snapshot time series
- `completion_forecaster.py` — 3-point (optimistic/expected/pessimistic) completion date estimates

---

## ADR-003: LOOM — Layered Ontological Outcome Mapping

**Status:** Accepted
**Date:** 2026-02-01

**Context:** Need a knowledge graph structure that supports prerequisite tracking, mastery visualization, and intelligent tutoring decisions.

**Decision:** Build a course-specific knowledge graph (LOOM) with LLM-extracted concepts and edges.

**Rationale:**
- Static curriculum graph alone misses dynamic student understanding
- LLM extraction enables automatic graph construction from uploaded materials
- Graph structure supports prerequisite-aware learning path generation
- Edge types (prerequisite, related, confused_with, reinforces) enable multiple teaching strategies

**Implementation:**
- `apps/api/services/loom_extraction.py` — LLM-based concept extraction with Bloom's taxonomy levels (remember→evaluate)
- `apps/api/services/loom_graph.py` — graph queries, learning path generation (Kahn's topological sort), prerequisite gap detection, time-decayed mastery via FSRS retrievability
- `apps/api/services/loom_mastery.py` — mastery updates with FIRe (Fractional Implicit Repetitions): when concept A is practiced, prerequisite concepts receive fractional credit proportional to 1/(depth+1)
- `apps/api/models/knowledge_graph.py` — `KnowledgeNode`, `KnowledgeEdge` (prerequisite/related/confused_with/reinforces/part_of), `ConceptMastery`

**Key design patterns:**
- Cross-course concept linking: automatically creates `reinforces` edges between identical concepts across courses
- Per-user mastery: `ConceptMastery` tracks mastery_score, practice_count, correct_count, wrong_count, stability_days, next_review_at
- Time decay: applies `R(t) = (1 + t/(9×S))^-1` to mastery scores when computing effective mastery

**Rejected alternative:** Single monolithic concept bank — rejected for per-course extraction + cross-course linking for modularity

---

## ADR-004: LECTOR — Semantically-Ordered Review

**Status:** Accepted
**Date:** 2026-02-10

**Context:** Standard FSRS scheduling treats cards independently. Students benefit from reviewing related concepts together.

**Decision:** Layer a semantic ordering system (LECTOR) on top of FSRS that groups related cards by knowledge graph proximity.

**Rationale:**
- Interleaved practice of related concepts improves transfer (Rohrer & Taylor, 2007)
- LOOM graph provides concept relationships for grouping
- Falls back to standard FSRS ordering when graph data is sparse

**Implementation:**
- `apps/api/services/lector.py` — smart review session generation with multi-factor priority scoring
- `apps/api/services/lector_analytics.py` — review effectiveness metrics (coverage %, health score)
- `apps/api/services/lector_session.py` — session structuring: warm-up, interleaving, contrast pairs, peak-end effect

**Multi-factor priority scoring (6 factors):**
1. Low mastery (weight 0.5): `(threshold - mastery) × factor`
2. Never practiced (weight 0.3): boost for untouched concepts
3. Time decay (weight 0.3): `(days_since / stability - 1) × factor`
4. Prerequisite at risk (weight 0.2): boost if prerequisites are weak
5. Confusion pair boost (weight 0.1): review confused_with pairs together
6. FSRS overdue boost: compute R(t) and boost if overdue

**Review type classification:** Each item tagged as standard/contrast/prerequisite_first to guide UI presentation.

**Rejected alternative:** Standard FSRS ordering without concept grouping — treats cards as independent, misses interleaving benefits (Rohrer & Taylor, 2007)

---

## ADR-005: Block System for Adaptive UI

**Status:** Accepted
**Date:** 2026-02-20

**Context:** Different learners need different dashboard layouts based on their progress, learning mode, and detected difficulties.

**Decision:** Implement a block-based dashboard system where blocks can be added, removed, and reordered by both user and AI agent.

**Rationale:**
- Fixed layouts don't adapt to learning phase (e.g., new learner vs. exam prep)
- Block system enables feature-unlock progression (gamification)
- Agent can surface relevant blocks based on detected needs (e.g., wrong_answers block after consecutive failures)
- Each block is independently renderable and testable

**Block types (13):** `notes`, `quiz`, `flashcards`, `progress`, `knowledge_graph`, `review`, `plan`, `chapter_list`, `podcast`, `forecast`, `wrong_answers`, `agent_insight`

**Three-source model:** Blocks originate from user (manual add), template (mode selection), or agent (AI-suggested). Agent blocks can require explicit approval before activation (`needsApproval` flag).

**Learning mode templates:** Predefined layouts for `course_following`, `self_paced`, `exam_prep`, `maintenance` — each emphasizes different block types (e.g., exam_prep prioritizes quiz/review).

**Implementation:**
- `apps/web/src/lib/block-system/registry.ts` — lazy-loaded component registry via `React.lazy()`
- `apps/web/src/lib/block-system/templates.ts` — mode → layout builder functions
- `apps/web/src/lib/block-system/feature-unlock.ts` — feature unlock tracking and gating
- `apps/web/src/lib/block-system/types.ts` — `BlockType`, `BlockInstance`, `BlockSource`, `AgentBlockMeta`, `LearningMode`
- `apps/web/src/store/workspace-blocks.ts` — Zustand slice with `addBlock()`, `removeBlock()`, `reorderBlocks()`, 10-item history stack for undo
- `apps/web/src/components/blocks/block-grid.tsx` — responsive 1-3 column grid with roving tabindex (accessibility)
- `apps/web/src/components/blocks/block-wrapper.tsx` — individual block rendering with error boundary, agent approval UI

**Rejected alternative:** Fully draggable/resizable layout (react-grid-layout) — rejected for implementation complexity; CSS grid + predefined templates with block reordering provides sufficient flexibility.

---

## ADR-006: SQLite-First Local Mode

**Status:** Accepted
**Date:** 2026-01-10

**Context:** OpenTutor targets individual students who need a self-hosted tutoring system without infrastructure complexity.

**Decision:** Default to SQLite (via aiosqlite) with optional PostgreSQL for multi-user deployments.

**Rationale:**
- Zero-config setup for single users (just run the app)
- SQLite handles concurrent reads well; single-user write contention is minimal
- Same SQLAlchemy ORM code works for both backends
- StaticPool for SQLite eliminates connection overhead
- Production PostgreSQL path uses proper connection pooling (pool_size=10, max_overflow=20)

**Implementation:** `apps/api/database.py` — conditional engine configuration based on `DATABASE_URL` prefix. `config.py:Settings.database_url` defaults to `sqlite+aiosqlite:///./opentutor.db`.

---

## ADR-007: Multi-Provider LLM Router with Circuit Breaker

**Status:** Accepted
**Date:** 2026-02-05

**Context:** LLM availability varies; local models (LM Studio) crash under load; cloud providers have rate limits.

**Decision:** Implement a router that dispatches to multiple LLM providers with automatic failover and circuit breaker protection.

**Rationale:**
- Circuit breaker prevents cascading failures when a provider is down
- Supports local (LM Studio, Ollama) and cloud (OpenAI, Anthropic, DeepSeek) providers
- Provider selection based on task type (e.g., classification vs. generation)
- Graceful degradation: AI features show "blocked" state instead of crashing

**Implementation:** `apps/api/services/llm/router.py` — provider registry, circuit breaker with configurable thresholds, retry with exponential backoff. `apps/api/services/llm/circuit_breaker.py` — half-open/open/closed state machine.

---

## ADR-008: 8-Signal Cognitive Load Detection

**Status:** Accepted
**Date:** 2026-02-25

**Context:** Adaptive tutoring requires sensing when a student is overwhelmed to adjust difficulty and pacing.

**Decision:** Compute cognitive load as a weighted sum of 8 real-time signals from student interaction data.

**Signals:**
1. Message length trend (shorter = overloaded)
2. Question frequency (more questions = confusion)
3. Topic switching rate (rapid switching = scattered attention)
4. Error rate in recent practice
5. Session duration fatigue
6. Vocabulary complexity drop
7. Response latency increase
8. Help-seeking frequency

**Implementation:** `apps/api/services/cognitive_load.py` — async `compute_cognitive_load()` returns 0.0-1.0 score with individual signal breakdown. Used by tutor agent to adjust response complexity and suggest breaks.
