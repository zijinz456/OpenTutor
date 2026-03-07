# OpenTutor: From Prototype to Disruptive — Implementation Plan

## Status Quo Diagnosis (based on code audit)

| System | Claimed | Actual Code | Completion |
|--------|---------|-------------|------------|
| LOOM Knowledge Graph | Graph DB + decay + cross-course reasoning | SQLite JSON + EMA mastery + LLM extraction, no decay, no cross-course | 50% |
| LECTOR Semantic Review | Smart spaced repetition | Real FSRS-4.5 impl + BKT with pyBKT EM trainer + FIRe propagation | 60% |
| Cognitive Load | Behavioral signal analysis | 6 signals (fatigue, session length, errors, brevity, help-seeking, quiz perf) + layout simplification | 45% |
| AI Tutor | Teaching strategy engine | LLM-extracted teaching strategies + structured error classification + Bloom's taxonomy | 40% |
| Block System | Adaptive workspace | 12 block types, feature-unlock conditions, cognitive load hide priority | 90% |

**Key finding**: The critique underestimates your codebase. You have real FSRS, real BKT with EM training, FIRe prerequisite propagation, and structured error classification. These are NOT "simple wrappers". But they're disconnected — the pieces don't talk to each other yet.

---

## The Strategic Bet: Don't go wide. Go deep on ONE axis.

The critique says "10x better on one core function". I agree. Your best candidate:

### **"The system that knows what you DON'T know — and proves it's right."**

This is the intersection of LOOM + LECTOR + Cognitive Load, unified through the Block system. No competitor does all three:
1. Detect knowledge gaps (LOOM prerequisite walk + error classification)
2. Schedule optimal reviews (FSRS + confusion pair detection)
3. Adapt in real-time (cognitive load → layout simplification → difficulty adjustment)

The Block system is the **delivery mechanism** — it's how the student *experiences* this intelligence.

---

## Phase 1: Close the Feedback Loops (Week 1-2)

The biggest problem isn't missing features — it's that existing systems don't feed into each other.

### 1.1 Wire LOOM → LECTOR (Knowledge Graph drives Review)

**Current**: LOOM extracts concepts, LECTOR schedules flashcards. They don't know about each other.

**Target**: When FSRS schedules a card, it checks prerequisite mastery first. If prerequisites are weak, it schedules THOSE instead.

**File**: `apps/api/services/spaced_repetition/flashcards.py`

```python
# BEFORE: select due cards by date only
# AFTER: prerequisite-aware card selection

async def select_next_review_batch(db, user_id, course_id, batch_size=10):
    """Select review cards, prioritizing unmastered prerequisites."""
    from services.loom import check_prerequisite_gaps

    # 1. Get due cards from FSRS
    due_cards = await get_due_cards(db, user_id, course_id)

    # 2. For each card, check if its concept has unmastered prerequisites
    gaps = await check_prerequisite_gaps(db, user_id, course_id)
    gap_concepts = {g["concept"].lower() for g in gaps}

    # 3. Partition: prerequisite cards first, then regular due cards
    prereq_cards = [c for c in due_cards if any(
        kp.lower() in gap_concepts for kp in (c.knowledge_points or [])
    )]
    regular_cards = [c for c in due_cards if c not in prereq_cards]

    # 4. Interleave: 60% prereq, 40% regular (prevents boring prerequisite loops)
    batch = _interleave(prereq_cards, regular_cards, ratio=0.6, total=batch_size)
    return batch
```

### 1.2 Wire Error Classification → LOOM (Errors build the graph)

**Current**: `classifier.py` classifies errors as {conceptual, procedural, computational, reading, careless}. Result is stored but never used to update the knowledge graph.

**Target**: Conceptual errors automatically create `confused_with` edges in LOOM.

**File**: `apps/api/routers/wrong_answers.py` (after error is classified)

```python
# After classify_error() returns a result:
if classification["category"] == "conceptual":
    # Create a confusion edge in LOOM
    await store_graph_entities(db, user_id, course_id, {
        "entities": [
            {"name": classification["related_concept"], "type": "Concept", "description": ""},
        ],
        "relationships": [
            {
                "source": question_concept,
                "relation": "confused_with",
                "target": classification["related_concept"],
            }
        ],
    })
```

### 1.3 Wire Cognitive Load → FSRS (Load adjusts difficulty)

**Current**: Cognitive load score generates a prompt fragment for the tutor. It doesn't affect practice difficulty.

**Target**: High cognitive load → FSRS presents easier cards (higher stability = more confident knowledge).

**File**: `apps/api/services/cognitive_load.py`

```python
def adjust_review_difficulty(cognitive_load_score: float, cards: list) -> list:
    """Reorder cards based on cognitive load — easier cards first when loaded."""
    if cognitive_load_score < 0.5:
        return cards  # Normal difficulty ordering

    # Sort by stability descending (most stable = easiest recall)
    # Under high load, let student build confidence with easy wins
    return sorted(cards, key=lambda c: c.stability, reverse=True)
```

---

## Phase 2: Make LOOM Real (Week 2-3)

### 2.1 Knowledge Decay Model

**Current**: `mastery_score` uses EMA (exponential moving average) — no time component. A concept mastered 6 months ago shows the same score as one mastered yesterday.

**Target**: Integrate FSRS retrievability into the mastery graph.

**File**: `apps/api/services/loom.py` — modify `get_mastery_graph()`

```python
# In get_mastery_graph(), replace raw mastery_score with time-decayed score:
from services.spaced_repetition.fsrs import _retrievability

for node in nodes:
    m = masteries.get(node.id)
    if m and m.last_practiced_at and m.stability_days > 0:
        elapsed = (now - m.last_practiced_at).total_seconds() / 86400
        retrievability = _retrievability(elapsed, m.stability_days)
        effective_mastery = m.mastery_score * retrievability
    else:
        effective_mastery = m.mastery_score if m else 0.0

    graph_nodes.append({
        ...
        "mastery": round(effective_mastery, 3),
        "retrievability": round(retrievability, 3) if m else 0.0,
        "raw_mastery": round(m.mastery_score, 3) if m else 0.0,
        ...
    })
```

**Impact**: The knowledge graph now shows "what you ACTUALLY remember right now", not "what you once knew". This is the single most important change for making LOOM feel intelligent.

### 2.2 Cross-Course Concept Linking

**Current**: Each course has isolated concepts. "Linear Algebra" and "Machine Learning" don't know that "eigenvalue" appears in both.

**Target**: When concepts from different courses share the same name (or high embedding similarity), create cross-course `reinforces` edges.

**File**: New function in `apps/api/services/loom.py`

```python
async def link_cross_course_concepts(db, user_id, similarity_threshold=0.85):
    """Find and link identical/similar concepts across courses."""
    # 1. Get all KnowledgeNodes for this user's courses
    # 2. Group by normalized name (case-insensitive, stripped)
    # 3. For same-name concepts in different courses: create "reinforces" edge
    # 4. For remaining: compute embedding similarity, link above threshold
    # 5. When mastery updates in one course, apply FIRe propagation cross-course
```

### 2.3 "Next to Study" Recommender (upgrade from naive)

**Current**: `next_to_study = weak_concepts[0]` — literally the first weak concept.

**Target**: Topological sort already exists in `generate_learning_path()`. Wire it into `get_mastery_graph()`.

```python
# Replace:
next_to_study = weak_concepts[0]

# With:
learning_path = await generate_learning_path(db, course_id, user_id)
next_to_study = learning_path[0]["name"] if learning_path else None
```

---

## Phase 3: Make Cognitive Load Actually Adaptive (Week 3-4)

### 3.1 Answer Timing Signal

**Current**: No timing data captured.

**Target**: Capture time-to-answer for quiz questions. Long hesitation = uncertainty signal.

**Frontend** (`apps/web/src/components/sections/practice/quiz-view.tsx`):
```typescript
// Track time when question is displayed
const [questionStartTime, setQuestionStartTime] = useState<number>(0);

// On answer submit:
const answerTimeMs = Date.now() - questionStartTime;
await api.submitAnswer({ ...answer, answer_time_ms: answerTimeMs });
```

**Backend** (`apps/api/schemas/quiz.py`):
```python
class AnswerSubmission(BaseModel):
    answer_time_ms: int | None = None  # Add this field
```

**Cognitive Load** (`apps/api/services/cognitive_load.py`):
```python
# Signal 7: Answer timing (requires last N answer times)
if recent_answer_times:
    median_time = statistics.median(recent_answer_times)
    # Normalize: >60s median = high signal, <15s = low signal
    timing_signal = min(max((median_time - 15000) / 45000, 0), 1.0)
    signals["answer_hesitation"] = timing_signal
    load += timing_signal * settings.cognitive_load_weight_timing
```

### 3.2 Feedback Loop Validation

**Current**: Cognitive load adjusts prompts, but we never check if the adjustment helped.

**Target**: Track pre/post cognitive load around adjustments. If load stays high after 3 consecutive adjustments, escalate.

```python
async def track_adaptation_effectiveness(db, user_id, course_id):
    """Check if cognitive load adaptations are actually helping."""
    # Get last 5 cognitive load measurements
    # If load trend is: high → still high → still high
    # Then current strategy isn't working → escalate:
    #   - Suggest topic change
    #   - Suggest break
    #   - Switch to easier content (Bloom's remember/understand only)
```

---

## Phase 4: Teaching Strategy Engine (Week 4-5)

### 4.1 Socratic Mode (Beyond Prompt Engineering)

**Current**: Teaching strategy is "prompt fragment injection". The tutor doesn't have a state machine.

**Target**: A finite-state teaching strategy that tracks where the student is in understanding.

**File**: New `apps/api/services/agent/socratic_engine.py`

```python
"""Socratic questioning engine — stateful pedagogical interaction.

States:
  PROBE    → Ask what the student thinks (open-ended)
  CLARIFY  → Student gave partial/vague answer → narrow the question
  CONFRONT → Student has misconception → present counterexample
  SCAFFOLD → Student is stuck → give hint, not answer
  CONFIRM  → Student got it → verify with transfer question

Transitions based on:
  - Error classification (conceptual → CONFRONT, procedural → SCAFFOLD)
  - Cognitive load (high → skip PROBE, go to SCAFFOLD)
  - Mastery level (low → more SCAFFOLD, high → more PROBE)
"""

class SocraticState(Enum):
    PROBE = "probe"
    CLARIFY = "clarify"
    CONFRONT = "confront"
    SCAFFOLD = "scaffold"
    CONFIRM = "confirm"

class SocraticEngine:
    def __init__(self, mastery: float, cognitive_load: float, error_type: str | None):
        self.state = self._initial_state(mastery, cognitive_load)
        self.error_type = error_type
        self.turns_in_state = 0

    def _initial_state(self, mastery, load) -> SocraticState:
        if load > 0.7:
            return SocraticState.SCAFFOLD  # Don't challenge overloaded students
        if mastery < 0.3:
            return SocraticState.SCAFFOLD  # New to concept
        if mastery > 0.7:
            return SocraticState.PROBE     # Challenge strong students
        return SocraticState.CLARIFY       # Middle ground

    def transition(self, student_response_quality: str) -> SocraticState:
        """Transition based on student response quality."""
        # quality: "correct", "partial", "wrong", "confused", "no_response"
        transitions = {
            (SocraticState.PROBE, "correct"): SocraticState.CONFIRM,
            (SocraticState.PROBE, "partial"): SocraticState.CLARIFY,
            (SocraticState.PROBE, "wrong"): SocraticState.CONFRONT,
            (SocraticState.PROBE, "confused"): SocraticState.SCAFFOLD,
            (SocraticState.CLARIFY, "correct"): SocraticState.CONFIRM,
            (SocraticState.CLARIFY, "partial"): SocraticState.SCAFFOLD,
            (SocraticState.CLARIFY, "wrong"): SocraticState.CONFRONT,
            (SocraticState.CONFRONT, "correct"): SocraticState.CONFIRM,
            (SocraticState.CONFRONT, "wrong"): SocraticState.SCAFFOLD,
            (SocraticState.SCAFFOLD, "correct"): SocraticState.PROBE,  # Level up
            (SocraticState.SCAFFOLD, "wrong"): SocraticState.SCAFFOLD,
            (SocraticState.CONFIRM, "correct"): SocraticState.PROBE,   # Move on
            (SocraticState.CONFIRM, "wrong"): SocraticState.CLARIFY,   # False positive
        }
        self.state = transitions.get(
            (self.state, student_response_quality),
            SocraticState.SCAFFOLD  # Safe default
        )
        self.turns_in_state += 1
        return self.state

    def get_prompt_directive(self) -> str:
        """Generate teaching instruction for the LLM based on current state."""
        directives = {
            SocraticState.PROBE: (
                "Ask the student an open-ended question about this concept. "
                "Do NOT give the answer. Let them reason. "
                "Example: 'What do you think happens when...?'"
            ),
            SocraticState.CLARIFY: (
                "The student's understanding is vague. Ask a more specific question "
                "to pinpoint what they do and don't understand. "
                "Example: 'When you say X, do you mean A or B?'"
            ),
            SocraticState.CONFRONT: (
                "The student has a misconception. Present a counterexample "
                "that challenges their current understanding. "
                "Do NOT say 'you're wrong'. Let the counterexample create cognitive conflict. "
                "Example: 'If that were true, what would happen in this case...?'"
            ),
            SocraticState.SCAFFOLD: (
                "The student needs help. Give ONE small hint that moves them forward "
                "without giving the full answer. Break the problem into a smaller step. "
                "Example: 'Let's start with just the first part. What is X?'"
            ),
            SocraticState.CONFIRM: (
                "The student seems to understand. Verify with a transfer question — "
                "ask them to apply the same concept in a slightly different context. "
                "Example: 'Good! Now what if we change X to Y?'"
            ),
        }
        return directives[self.state]
```

### 4.2 Teaching Effectiveness Tracking

**Current**: Teaching strategies are extracted but never validated.

**Target**: Track which strategies led to mastery improvement.

```python
# In teaching_strategies.py, add effectiveness scoring:
async def score_strategy_effectiveness(db, user_id, course_id):
    """Compare mastery before/after applying each strategy type."""
    strategies = await get_teaching_strategies(db, user_id, course_id)
    for strategy in strategies:
        topic = strategy.get("topic", "")
        extracted_at = strategy.get("extracted_at")
        # Get mastery delta for this topic after strategy was applied
        # If mastery improved: boost confidence
        # If mastery stayed flat: reduce confidence
        # Prune strategies with confidence < 0.2 after 30 days
```

---

## Phase 5: Block System as Intelligence Surface (Week 5-6)

### 5.1 Agent-Driven Layout Recommendations

**Current**: Blocks are manually arranged. Cognitive load can suggest hiding blocks.

**Target**: The agent proactively suggests block layouts based on learning state.

```typescript
// Example agent suggestion events:
// "You've been reviewing for 30 minutes. I've moved the Knowledge Graph
//  to the top — notice the red nodes? Those are concepts decaying fastest."

// "You got 3 confusion-pair errors in a row. I've added the Wrong Answers
//  block next to your Quiz so you can see the pattern."

// "Great progress on Chapter 3! I've unlocked the Forecast block —
//  you now have enough data for grade predictions."
```

### 5.2 Confusion Pair Detection → Review Block

**Current**: Wrong answers are listed but not analyzed for patterns.

**Target**: When LOOM detects `confused_with` edges, the Review block shows side-by-side comparison cards.

```python
async def get_confusion_pairs(db, user_id, course_id) -> list[dict]:
    """Find concept pairs the student frequently confuses."""
    # Query LOOM for confused_with edges
    # Return: [{"concept_a": "Derivative", "concept_b": "Integral",
    #           "confusion_count": 5, "comparison_prompt": "..."}]
    # Frontend renders these as split-screen comparison flashcards
```

---

## Implementation Priority Matrix

| Change | Effort | Impact | Do First? |
|--------|--------|--------|-----------|
| 2.1 Knowledge decay (FSRS retrievability in mastery graph) | Small | **Huge** | YES |
| 1.1 Wire LOOM→LECTOR (prereq-aware review) | Medium | **Huge** | YES |
| 1.2 Wire errors→LOOM (confusion edges) | Small | High | YES |
| 2.3 Fix next_to_study (use topological sort) | Tiny | Medium | YES |
| 3.1 Answer timing signal | Medium | High | Week 2 |
| 1.3 Cognitive load → FSRS difficulty | Small | Medium | Week 2 |
| 4.1 Socratic state machine | Large | **Huge** | Week 3 |
| 2.2 Cross-course linking | Medium | Medium | Week 4 |
| 5.2 Confusion pair cards | Medium | High | Week 4 |
| 3.2 Adaptation feedback loop | Medium | Medium | Week 5 |
| 4.2 Teaching effectiveness tracking | Medium | Medium | Week 5 |
| 5.1 Agent-driven layout | Large | High | Week 6 |

---

## The Narrative Shift

**Before** (README sells vaporware):
> "LOOM Knowledge Graph with deep ontological reasoning"

**After** (README sells what's real):
> "OpenTutor knows what you've forgotten. Its knowledge graph decays in real-time
> using FSRS-4.5 retrievability curves. When you fail a quiz question, the system
> traces the error to its prerequisite root cause and schedules targeted review.
> Under cognitive overload, the workspace simplifies itself — hiding advanced
> analytics and surfacing only what matters right now."

This is honest, specific, and genuinely differentiated. No other open-source learning tool connects spaced repetition, knowledge graphs, error classification, and adaptive UI into a single feedback loop.

---

## What NOT to Build

- **Neo4j/graph database**: SQLite with the current edge table is fine for single-user. Don't add infrastructure complexity until you have 100+ users.
- **A/B testing framework**: You have one user. Track before/after instead.
- **Real typing speed analysis**: Browser keyboard events are noisy and privacy-invasive. Answer timing is a better signal.
- **Complex behavioral analytics**: The 6 signals you have are enough. Focus on making the feedback loop work, not adding more sensors.
