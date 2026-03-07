# OpenTutor PRD: Your AI-Powered Personal Learning Website

**Version:** 1.0
**Date:** 2026-03-07
**Status:** Draft

---

## 1. Product Positioning

**One-liner:** Your AI private learning website — locally deployed, agent-driven, fully yours.

**Core thesis:** Every learner deserves a personal learning website that adapts to them, not a generic SaaS dashboard they rent. OpenTutor runs locally, ingests any course material (PDFs, slides, Canvas LMS), and builds an AI-powered learning space that evolves with you.

**Three pillars:**

| Pillar | Description |
|--------|-------------|
| Personal Website | Block-based pages with full-page routes for each content type. Content is the protagonist, not chat. |
| Autonomous Agent | 3-tier autonomy model. Agent proactively modifies your website — adds review reminders, reorders layout before exams, surfaces insights. |
| Chat as Control Panel | Users can adjust anything via conversation, but the Agent also operates independently in the background. |

**Differentiation from competitors:**
- **vs. Hyperknow:** Same core logic (agent-based learning), but OpenTutor is locally deployed, open-source, and gives users full data ownership. No subscription lock-in.
- **vs. Knowt/Quizlet:** Beyond flashcards. OpenTutor builds a knowledge graph (LOOM), does semantic spaced repetition (LECTOR), and provides an autonomous agent — not just content generation.
- **vs. Anki:** Anki is a flashcard tool. OpenTutor is a complete learning environment with notes, practice, knowledge graphs, study plans, and an AI tutor.

---

## 2. Competitive Analysis

### 2.1 Primary Competitor: Hyperknow

**What they do well:**
- Learner's Persona — persistent memory of learning preferences and behavior patterns
- Agent autonomy — AI proactively adjusts learning path
- Clean, modern UI focused on the learning experience
- Smart course analysis on upload

**What we do better:**
- Local deployment — full data privacy, no subscription
- LOOM knowledge graph — semantic concept relationships, not just flat flashcards
- LECTOR spaced repetition — retrievability-based review scheduling with stability tracking
- Canvas LMS deep integration — automatic course extraction
- Open-source — extensible by community

**Gaps to close:**
- Learner's Persona → implement via Agent memory (learning preferences, behavior patterns, difficulty preferences)
- Polished onboarding → setup flow with template selection
- Progressive complexity → unlock features as user engagement deepens

### 2.2 Secondary Competitors

| Competitor | Users | Strength | Our Advantage |
|-----------|-------|----------|---------------|
| Knowt | 5M+ | AI flashcards, "Kai" voice assistant, freemium model | Deeper knowledge modeling (LOOM graph vs flat cards) |
| Quizlet | 60M+ | Market dominance, social features | Agent autonomy, local deployment, no ads |
| Anki | 10M+ | Proven SRS algorithm, plugin ecosystem | Complete learning environment, not just flashcards |
| Notion + AI | — | Flexible workspace | Purpose-built for learning, not general-purpose |

---

## 3. Learning Modes

Each course can operate in one of four modes. The mode determines page layout, navigation structure, Plan content, and Agent behavior.

### 3.1 Mode Definitions

#### Course Following (跟课模式)
**Scenario:** Student enrolled in a course with regular lectures, assignments, deadlines.
**Page layout:** Timeline-driven. Upcoming deadlines prominent. Notes organized by lecture/week.
**Navigation:** Week/module based sidebar.
**Plan structure:** Syllabus timeline — deadlines, readings, assignments mapped to calendar.
**Agent behavior:** Tracks lecture schedule, reminds about upcoming deadlines, suggests pre-reading before lectures, generates practice after each lecture.

#### Self-Paced (自学模式)
**Scenario:** Learning a topic independently from textbooks, MOOCs, or collected materials.
**Page layout:** Content-exploration driven. Knowledge graph prominent. Notes organized by topic cluster.
**Navigation:** Topic/concept based, not chronological.
**Plan structure:** Learning path — concept dependency graph converted to suggested study order.
**Agent behavior:** Identifies knowledge gaps via LOOM, suggests next topic based on prerequisite mastery, adapts difficulty based on practice performance.

#### Exam Prep (备考模式)
**Scenario:** Exam approaching. Need to review, practice, identify weak spots.
**Page layout:** Practice-heavy. Wrong answers and weak concepts prominent. Timed practice available.
**Navigation:** Priority-sorted by weakness/urgency.
**Plan structure:** Countdown plan — days until exam, daily review targets, concept coverage checklist.
**Agent behavior:** Aggressive review scheduling, focuses on weak areas, generates exam-style practice, tracks coverage of all testable concepts.

#### Maintenance (维护模式)
**Scenario:** Course completed or exam passed. Want to retain knowledge long-term.
**Page layout:** Minimal. Review cards and knowledge graph only.
**Navigation:** Simplified — review and graph only.
**Plan structure:** LECTOR-driven — only surfaces concepts at risk of fading.
**Agent behavior:** Minimal intervention. Only triggers when LECTOR detects significant retrievability drop. Sends periodic digest ("3 concepts fading this week").

### 3.2 Mode Transitions

Modes can be:
- **Manually selected** by the user when creating/editing a course (Tier 3)
- **Suggested by Agent** based on behavioral signals (Tier 2):
  - Course Following → Exam Prep: deadline approaching + error rate increasing
  - Exam Prep → Maintenance: exam deadline passed
  - Self-Paced → Maintenance: all concepts mastered above threshold
  - Any → Any: user explicitly requests via chat or settings

---

## 4. Information Architecture

### Level 0: Command Center (Home Page `/`)

Cross-course overview. Not just a course list — an active learning dashboard.

**Sections:**
- **Today's Digest** — AI-generated daily summary: what you learned yesterday, what to focus on today, weekly knowledge growth curve
- **Urgent Reviews** — Aggregated LECTOR reviews across all courses, sorted by urgency (overdue > urgent > warning)
- **Upcoming Deadlines** — Cross-course deadline timeline (from Plan data)
- **Agent Insights** — Cross-course agent notifications (Tier 2 suggestions awaiting approval)
- **Your Spaces** — Course cards with mode badges, last activity, progress indicators

**Design:** Cards-based layout. Each section is collapsible. Mobile: vertical stack. Desktop: 2-column grid.

### Level 1: Course Home (`/course/[id]`)

Mode-specific landing page. Layout determined by learning mode.

**Common elements (all modes):**
- Course header with name, mode badge, quick actions
- Block grid with mode-appropriate default blocks
- Chat FAB (bottom-right) opening Chat Drawer

**Mode-specific layouts:**

| Mode | Primary Blocks | Secondary Blocks |
|------|---------------|-----------------|
| Course Following | chapter_list(full), notes(large), plan(medium) | quiz(medium), progress(small) |
| Self-Paced | knowledge_graph(large), notes(large) | quiz(medium), flashcards(medium), progress(small) |
| Exam Prep | quiz(large), wrong_answers(large) | flashcards(medium), review(medium), progress(small) |
| Maintenance | review(large), knowledge_graph(medium) | progress(small) |

### Level 2: Full-Page Routes

Each block type can expand into a full-page experience:

| Route | Content |
|-------|---------|
| `/course/[id]/notes` | Full notes viewer/editor with chapter navigation |
| `/course/[id]/practice` | Quiz, flashcards, timed practice modes |
| `/course/[id]/graph` | Full-screen interactive knowledge graph (LOOM) |
| `/course/[id]/plan` | Study plan with calendar view, deadline tracking |
| `/course/[id]/review` | Immersive LECTOR review session (card-by-card) |
| `/course/[id]/profile` | Course settings, mode selection, Agent preferences |

### Level 2.5: Unit Aggregate View (`/course/[id]/unit/[nodeId]`)

Deep-dive into a single knowledge unit/concept:

**Sections:**
- **Notes** — All notes related to this concept
- **Practice** — Quiz questions and flashcards for this concept
- **Knowledge Graph** — Subgraph showing this concept's relationships (prerequisites, related concepts)
- **Error Analysis** — Historical wrong answers for this concept, patterns
- **Mastery Timeline** — LECTOR tracking: retrievability over time, review history

This view answers: "Everything I need to know about concept X, in one place."

---

## 5. Block System

### 5.1 Block Types

| Type | Description | Default Size | Available in Modes |
|------|-------------|-------------|-------------------|
| `chapter_list` | Content tree / module navigation | full | all |
| `notes` | AI-generated notes with multiple formats | large | all |
| `quiz` | Adaptive practice questions | medium/large | all |
| `flashcards` | Spaced repetition flashcards | medium/large | all |
| `progress` | Learning analytics and stats | small | all |
| `knowledge_graph` | LOOM interactive concept map | medium/large | all |
| `review` | LECTOR review session entry point | medium | all |
| `plan` | Study plan / deadline tracker | medium | all |
| `wrong_answers` | Error analysis and weak spots | medium | exam_prep, self_paced |
| `forecast` | Mastery prediction / exam readiness | medium | exam_prep |
| `agent_insight` | Agent-generated insight with CTA | varies | all (agent-created only) |

### 5.2 Block Instance Schema

```typescript
interface BlockInstance {
  id: string;
  type: BlockType;
  position: number;
  size: "small" | "medium" | "large" | "full";
  config: Record<string, unknown>;
  visible: boolean;
  source: "template" | "user" | "agent";
  agentMeta?: {
    reason: string;
    dismissible: boolean;
    expiresAt?: string;
    needsApproval?: boolean;
    approvalCta?: string;
  };
}
```

### 5.3 Templates

5 predefined templates map to default block layouts:

| Template | Target User | Key Blocks |
|----------|------------|------------|
| STEM Student | Science/engineering students | notes(step_by_step), quiz(adaptive), knowledge_graph |
| Humanities Scholar | Literature/history students | notes(summary), review, progress |
| Visual Learner | Visual-spatial learners | knowledge_graph(large), notes(mind_map), quiz |
| Quick Reviewer | Exam crammers | quiz(hard, large), flashcards, wrong_answers |
| Blank Canvas | Power users | Empty — build your own |

Templates are selected during onboarding (setup flow) and can be changed later.

---

## 6. Agent Autonomy Model

### 6.1 Three Tiers

#### Tier 1: Fully Autonomous (Agent acts without asking)
- Memory evolution — remember learning preferences, behavior patterns, difficulty preferences
- Add Insight reminder blocks — "3 concepts fading" (user can dismiss)
- Micro-reorder blocks — move most relevant block to top (e.g., quiz before exam)
- Update knowledge graph — LOOM automatically tracks concept mastery
- Record learning rhythm — track visit times, session duration, sticking points

#### Tier 2: Suggest + Confirm (Agent proposes, user approves/rejects)
- **Important operations** → Insight Block on the page with embedded [Approve] [Reject] buttons
- **Small adjustments** → Confirmation message in Chat drawer
- Specific operations: add new block, switch template/layout, generate new content (notes/practice), modify study plan, switch learning mode

#### Tier 3: User Must Initiate
- Delete blocks or content
- Modify user-created notes
- Change LLM/system configuration
- Export/share data
- Delete courses/spaces

### 6.2 Agent Memory Scope

**Tracks:**
- Learning preferences (note format, explanation style, difficulty preference)
- Behavior patterns (study times, session duration, concept sticking points)
- Cross-course patterns (which subjects studied together, time allocation)

**Does NOT track:**
- Emotional state detection
- Long-term career goals
- Social/collaborative behavior

### 6.3 Agent Triggers (Frontend, No Backend Changes Required)

| Trigger | Data Source (Existing API) | Agent Behavior | Tier |
|---------|--------------------------|----------------|------|
| LECTOR detects concept decay | `GET /api/progress/courses/{id}/review-session` | Auto-add review insight block | 1 |
| User opens course | `GET /api/chat/greeting/{id}` | Parse greeting, generate insight blocks | 1 |
| Ingestion completes | Poll ingestion jobs | Refresh chapter_list, suggest adding notes block | 1/2 |
| User gets 3+ wrong answers in a row | Local tracking of practice results | Reorder blocks, surface wrong_answers | 1 |
| Deadline approaching | Plan data | Switch to exam prep mode suggestion | 2 |
| Learning rhythm detected | Local visit time tracking | Adjust recommendation timing | 1 |

---

## 7. Plan Functionality

Plan is a cross-cutting dimension, not just a block. It appears as:
- A block on the course home page (compact view)
- A full-page route `/course/[id]/plan` (detailed view)
- Aggregated on the Level 0 home page (cross-course deadlines)

### 7.1 Mode-Specific Plan Structures

| Mode | Plan Content | View |
|------|-------------|------|
| Course Following | Syllabus timeline: lecture dates, assignment deadlines, reading schedule | Calendar/Gantt view |
| Self-Paced | Learning path: concept dependency order, suggested daily targets | Kanban/checklist view |
| Exam Prep | Countdown: days remaining, daily review targets, concept coverage % | Countdown + checklist |
| Maintenance | LECTOR schedule: concepts due for review this week | Simple list |

### 7.2 Plan Data Sources
- **User-created deadlines** — manually added via Plan page or chat
- **Canvas LMS sync** — auto-imported from Canvas assignments/due dates (existing integration)
- **LECTOR predictions** — review scheduling based on retrievability decay
- **Agent suggestions** — AI-generated study recommendations based on progress

---

## 8. Cross-Course Intelligence

### 8.1 Cross-Course Knowledge Linking
LOOM knowledge graphs should not be course silos. The system detects concept overlap across courses:
- Accounting "NPV" and Finance "Discounted Cash Flow" are the same concept
- Reviewing one strengthens the other
- Level 0 home page shows "knowledge network density" metric

### 8.2 Cross-Course LECTOR Reviews
The home page aggregates LECTOR reviews from all courses:
- Sorted by urgency (overdue > urgent > warning)
- Grouped by course with visual indicators
- One-click entry into immersive review mode for any course

### 8.3 Learning Mode Auto-Evolution
Agent monitors behavioral signals across courses and suggests mode transitions (Tier 2):
- Deadline proximity + rising error rate → suggest Exam Prep
- Exam deadline passed → suggest Maintenance
- All concepts above mastery threshold → suggest Maintenance

---

## 9. Progressive Complexity

New users should not be overwhelmed. Features unlock gradually:

| Feature | Unlock Condition |
|---------|-----------------|
| Notes + Practice | Always available (default) |
| Knowledge Graph | After uploading 3+ source documents |
| Plan | After setting first deadline or enabling Course Following mode |
| Forecast | After accumulating 50+ practice attempts |
| Wrong Answers | After first incorrect answer |
| Agent Insights | After 3+ learning sessions |
| Cross-Course Linking | After creating 2+ courses |

Agent introduces new features via Tier 2 Insight Blocks: "You now have enough data for a knowledge graph. Want to add it to your space?" [Add] [Not now]

---

## 10. Setup / Onboarding Flow

### Steps:
1. **LLM Configuration** — Provider, model, API key. Auto-skip if already configured.
2. **Content Upload** — Files, URLs, or Canvas LMS integration.
3. **Template Selection** — Choose from 5 templates or blank canvas. Visual preview with block type badges.
4. **Discovery** — Ingestion runs, AI probe analyzes content, user can enter workspace early.

### Template Selection UI:
- 5 cards in a grid (+ blank canvas option)
- Each card: name, description, list of included block types as badges
- Active selection: brand-colored ring
- "Continue" button disabled until selection made

---

## 11. Immersive Review Mode (`/course/[id]/review`)

LECTOR-driven full-screen review experience:

- Fetches review session via `getReviewSession(courseId, limit)`
- Card-by-card presentation: concept label, urgency badge, mastery %, stability days
- "Show Details" reveals: retrievability %, cluster, last reviewed date
- 4 rating buttons: Again (red), Hard (amber), Good (green), Easy (blue)
- Progress bar: reviewed / total
- Navigation: prev/next arrows, card counter
- Completion screen: summary stats, "Back to course" CTA

---

## 12. Color System

Replace grayscale (all chroma=0) with warm academic palette:

### Light Mode (oklch)
| Token | Value | Description |
|-------|-------|-------------|
| `--background` | `oklch(0.98 0.005 80)` | Warm white |
| `--card` | `oklch(0.99 0.003 80)` | Slightly warm |
| `--muted` | `oklch(0.96 0.005 80)` | Warm gray |
| `--brand` | `oklch(0.30 0.08 250)` | Deep blue |
| `--success` | `oklch(0.55 0.15 150)` | Emerald |
| `--warning` | `oklch(0.72 0.15 80)` | Amber |
| `--destructive` | `oklch(0.55 0.20 25)` | Coral |
| `--info` | `oklch(0.55 0.10 250)` | Blue |

### Dark Mode
Same hues, adjusted lightness. Maintain oklch format throughout.

---

## 13. Technical Architecture

### Frontend Stack
- Next.js 16, React 19, Tailwind 4
- Zustand for state management (workspace store, course store, chat store)
- SSE streaming for chat responses
- localStorage for block layout persistence (per course)

### Backend (Existing, No Changes Required for Phase 1)
- FastAPI (Python 3.11), SQLite (aiosqlite) + SQLAlchemy async
- Multi-provider LLM router with circuit breaker
- LOOM knowledge graph engine
- LECTOR semantic spaced repetition
- 3-Agent orchestration system (Planner, Executor, Reviewer)
- 7-step ingestion pipeline
- Canvas LMS deep integration

### Key API Endpoints Used
| Endpoint | Used By |
|----------|---------|
| `GET /api/health` | Runtime status, LLM availability |
| `GET /api/progress/courses/{id}/review-session` | LECTOR review data, Agent trigger |
| `POST /api/chat/stream` | Chat with SSE streaming, action markers |
| `GET /api/chat/greeting/{id}` | AI proactive greeting |
| `GET /api/courses/{id}/content-tree` | Chapter/module navigation |
| `GET /api/ingestion/jobs` | Ingestion progress tracking |

---

## 14. Implementation Roadmap

### Phase 1: Foundation (Current — In Progress)
- [x] Block type system (`types.ts`, `registry.ts`, `templates.ts`)
- [x] Workspace store extension (block CRUD, agent methods)
- [x] Block rendering (block-grid, block-wrapper, block-palette)
- [x] 11 block wrapper components
- [x] Course page integration with BlockGrid
- [x] Setup template selection step
- [x] Immersive review page
- [x] Dashboard rename (Courses → Learning Spaces)
- [ ] Color system overhaul

### Phase 2: Learning Modes
- [ ] Mode selection in course creation / profile
- [ ] Mode-specific default layouts
- [ ] Mode badge on course cards
- [ ] Agent mode transition suggestions (Tier 2)

### Phase 3: Full-Page Routes
- [ ] `/course/[id]/notes` — full notes viewer
- [ ] `/course/[id]/practice` — full practice environment
- [ ] `/course/[id]/graph` — full-screen knowledge graph
- [ ] `/course/[id]/plan` — study plan with calendar
- [ ] `/course/[id]/profile` — course settings + mode selection

### Phase 4: Unit Aggregate View
- [ ] `/course/[id]/unit/[nodeId]` — per-concept deep dive
- [ ] Combine notes, practice, graph subview, error analysis, mastery timeline

### Phase 5: Cross-Course Intelligence
- [ ] Cross-course knowledge linking (LOOM graph merging)
- [ ] Level 0 home page redesign (Today's Digest, aggregated reviews, deadlines)
- [ ] Cross-course LECTOR review aggregation
- [ ] Learning mode auto-evolution

### Phase 6: Progressive Complexity
- [ ] Feature unlock conditions
- [ ] Agent-driven feature introduction (Tier 2 insight blocks)
- [ ] Learning rhythm engine (visit time tracking, optimal study window detection)

### Phase 7: Advanced Agent
- [ ] Learner's Persona (persistent cross-session memory)
- [ ] Daily learning digest generation
- [ ] Browser notification for optimal study windows
- [ ] Exam readiness forecast

---

## 15. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Setup completion rate | >80% | Users who finish onboarding / users who start |
| Daily active usage | >60% of users return within 3 days | localStorage timestamp tracking |
| LECTOR review completion | >50% of due reviews completed | Review session data |
| Agent insight engagement | >30% of Tier 2 suggestions approved | Approval/dismiss tracking |
| Block customization | >40% of users modify default template | Block CRUD events |
| Cross-course usage | >50% of multi-course users engage with Level 0 | Page view tracking |

---

## 16. Non-Goals (Explicit Exclusions)

- Language learning specific features (removed from scope)
- Social/collaborative features (single-user local deployment)
- Mobile native app (web-responsive only)
- Emotional state detection
- Long-term career planning
- Content creation tools (not a note-taking app — AI generates content from uploaded material)
- Real-time collaboration
- Marketplace for templates or content
