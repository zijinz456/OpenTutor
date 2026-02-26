# OpenTutor — 逆向工程产品与技术规格书
## Reverse-Engineered Product & Technical Specification

> 生成日期: 2026-02-27
> 分析范围: main 分支全部代码 (2 commits, ~12,110 LOC, 110+ 源文件)

---

## 1. 问题陈述 (Problem Statement)

### 用户痛点
学生每次使用 ChatGPT 学习时面临三大问题:
1. **重复放 prompt** — 每次都要重新描述学习偏好和格式要求
2. **没有记忆** — AI 不记得你喜欢表格还是思维导图、详细还是简洁
3. **自己找资料太麻烦** — 需要手动从 Canvas/Blackboard 下载并整理学习材料

### 产品定位
> "给我任何学习材料，我帮你变成一个属于你的、越用越懂你的个性化学习网站"

OpenTutor 是一个自托管的开源个性化学习 Agent。上传 PDF/PPTX/DOCX/URL，自动创建包含 AI 笔记、测验、闪卡和对话助手的三面板学习界面 —— 一切都会随着使用逐渐适应你的偏好。

### 核心差异化
| 竞品 | 边界 | OpenTutor 跨越了什么 |
|------|------|---------------------|
| ChatGPT | 只对话、无记忆、只输出文字 | 输出的是一个完整学习网站 |
| NotebookLM | 理解文档但只能聊天 | 把文档变成交互式学习空间 |
| Canvas/Blackboard | 只是资料仓库 | AI 自动整理+重构+个性化呈现 |
| Quizlet/Anki | 只做闪卡、需手动输入 | 自动从任何材料生成，和笔记/问答一体化 |

---

## 2. 解决方案概览 (Solution Overview)

### 高层架构
```
┌──────────────────────────────────────────────────────────┐
│  Frontend — Next.js 16 + shadcn/ui + Tailwind CSS 4      │
│  (React 19, Zustand 5, react-resizable-panels 4)         │
│                        ↕ REST API + SSE                   │
│  Backend — Python FastAPI                                 │
│  ├── 11 Routers (API 端点)                                │
│  ├── 14 Services (业务逻辑)                               │
│  └── 14 ORM Models (数据层)                               │
│                        ↕                                  │
│  Data — PostgreSQL + pgvector │ Redis                     │
└──────────────────────────────────────────────────────────┘
```

### 设计属性
- **透明**: 偏好可在设置中查看和覆盖，非黑盒
- **渐进**: 从简单选项到自然语言到自动行为学习，三步走
- **懒加载**: 信号提取默认不提取（~95% 返回 NONE），避免噪音
- **有界**: Circuit breaker + 退避策略防止 LLM 级联失败
- **本地优先**: Docker 自部署，数据不离开用户机器

---

## 3. 产品需求 (Product Requirements)

### 3.1 用户可见行为

| # | 需求 | 状态 | 实现位置 |
|---|------|------|----------|
| R1 | 上传 PDF/PPTX/DOCX/HTML/TXT/MD 并自动解析为内容树 | ✅ | `routers/upload.py` + `services/ingestion/pipeline.py` |
| R2 | 输入 URL 自动抓取内容并解析 | ✅ | `routers/upload.py` + `services/parser/url.py` |
| R3 | 三面板学习界面（笔记 + 测验 + 对话） | ✅ | `app/course/[id]/page.tsx` |
| R4 | AI 笔记面板，支持 Mermaid 图 + KaTeX 数学公式 | ✅ | `components/course/notes-panel.tsx` + `markdown-renderer.tsx` |
| R5 | 交互式测验面板（7 种题型） | ✅ | `components/course/quiz-panel.tsx` |
| R6 | SSE 流式 AI 对话，带课程内容 RAG | ✅ | `components/chat/chat-panel.tsx` + `routers/chat.py` |
| R7 | 5 步偏好引导（语言/模式/详细度/布局/示例） | ✅ | `app/onboarding/page.tsx` |
| R8 | 自然语言偏好微调（"换成表格"） | ✅ | `components/course/nl-tuning-fab.tsx` |
| R9 | 行为自动学习偏好 | ✅ | `services/preference/extractor.py` |
| R10 | FSRS 间隔重复闪卡 | ✅ | `services/spaced_repetition/fsrs.py` |
| R11 | 知识图谱可视化 | ✅ | `components/course/knowledge-graph.tsx` |
| R12 | 学习进度追踪（课程→章节→知识点） | ✅ | `services/progress/tracker.py` |
| R13 | Canvas LMS 集成 | ✅ | `routers/canvas.py` + `services/browser/automation.py` |
| R14 | 中英双语界面 | ✅ | `lib/i18n.ts` (100+ 翻译键) |
| R15 | 键盘快捷键切换布局 (Cmd+0/1/2/3) | ✅ | `app/course/[id]/page.tsx` |

### 3.2 支持的工作流

| 工作流 | 描述 | 端点 |
|--------|------|------|
| WF-1 学期初始化 | 创建课程 + 偏好预设 + 学习计划 | `POST /api/workflows/semester-init` |
| WF-2 每周准备 | 截止日期 + 进度 → 本周计划 | `GET /api/workflows/weekly-prep` |
| WF-3 作业分析 | 分析作业要求 → 方法指南 | `POST /api/workflows/assignment-analysis` |
| WF-4 学习会话 | 上下文加载 → 搜索 → 生成 → 信号提取 | `POST /api/chat/` (核心聊天) |
| WF-5 错题复习 | 聚类错题 → 针对性复习 | `GET /api/workflows/wrong-answer-review` |
| WF-6 考前准备 | 评估准备度 → 天级计划 | `POST /api/workflows/exam-prep` |

### 3.3 范围边界

**包含**:
- 单用户本地部署模式
- PDF/PPTX/DOCX/HTML/TXT/MD 文件解析
- URL 抓取（3 层级联: httpx → Scrapling → Playwright）
- 4 个 LLM 提供商（OpenAI/Anthropic/DeepSeek/Ollama）
- 7 层偏好级联（temporary → course_scene → course → global_scene → global → template → system_default）

**不包含**:
- 多用户认证（Phase 1）
- 实时协作
- 移动端原生应用
- 云部署服务

---

## 4. 架构 (Architecture)

### 4.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Next.js 16)                       │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Onboard  │  │Dashboard │  │  /new    │  │ Settings │           │
│  │/onboarding│  │   /     │  │ Creation │  │/settings │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │              │              │              │                 │
│  ┌────┴──────────────┴──────────────┴──────────────┴─────┐         │
│  │              Course Workspace /course/[id]             │         │
│  │  ┌──────────┬──────────┬──────────┬───────────┐       │         │
│  │  │ActivityBar│PDF Viewer│AI Notes │Quiz/Cards │Chat  │         │
│  │  │(sidebar) │(Panel 1)│(Panel 2)│(Panel 3)  │(P4)  │         │
│  │  └──────────┴──────────┴──────────┴───────────┘       │         │
│  │  StatusBar | Breadcrumbs | NL Tuning FAB               │         │
│  └───────────────────────────────────────────────────────┘         │
│                                                                     │
│  State: Zustand (CourseStore + ChatStore)                           │
│  API Client: fetch + SSE generator                                  │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ REST + SSE
┌─────────────────────────┴───────────────────────────────────────────┐
│                        BACKEND (FastAPI)                             │
│                                                                     │
│  ┌─── Routers (11) ────────────────────────────────────────────┐   │
│  │ /content/upload  /chat  /courses  /preferences  /quiz       │   │
│  │ /notes  /workflows  /progress  /flashcards  /canvas         │   │
│  │ /notifications                                               │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                              │                                      │
│  ┌─── Services (14) ────────┴──────────────────────────────────┐   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │ Preference │  │  Memory    │  │   Search   │            │   │
│  │  │  Engine    │  │ Pipeline   │  │  (Hybrid)  │            │   │
│  │  │ 7-layer    │  │ EverMemOS  │  │ RRF Fusion │            │   │
│  │  │ cascade    │  │ 3-stage    │  │ K+V+Tree   │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │ Ingestion  │  │    LLM     │  │  Workflow   │            │   │
│  │  │ Pipeline   │  │   Router   │  │  (6 pipes)  │            │   │
│  │  │ 7-step     │  │ + Circuit  │  │ LangGraph   │            │   │
│  │  │ classify   │  │  Breaker   │  │ StateGraph  │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │  Spaced    │  │  Browser   │  │  Progress   │            │   │
│  │  │ Repetition │  │ Automation │  │  Tracker    │            │   │
│  │  │ FSRS-4.5   │  │ 3-layer    │  │ Mastery     │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐            │   │
│  │  │ Knowledge  │  │ Templates  │  │ Scheduler   │            │   │
│  │  │   Graph    │  │ (5 built-  │  │ APScheduler │            │   │
│  │  │ D3-compat  │  │   in)      │  │ 3 jobs      │            │   │
│  │  └────────────┘  └────────────┘  └────────────┘            │   │
│  │                                                              │   │
│  │  Parsers: PDF (Marker) │ URL (trafilatura) │ Quiz │ Notes  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── Models (14 ORM tables) ──────────────────────────────────┐   │
│  │ User, Course, CourseContentTree, UserPreference,             │   │
│  │ PreferenceSignal, PracticeProblem, PracticeResult,           │   │
│  │ ConversationMemory(pgvector), IngestionJob, StudySession,    │   │
│  │ Assignment, WrongAnswer, LearningProgress, LearningTemplate  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────────────────┐
│                        DATA LAYER                                    │
│  PostgreSQL + pgvector (14 tables, 1536-dim embeddings)              │
│  Redis (caching, rate limiting)                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 数据生命周期

```
                     上传文件 / 输入 URL
                           │
                           ▼
              ┌──────────────────────┐
              │  7-Step Ingestion    │
              │  SHA-256 去重        │
              │  MIME 检测           │
              │  内容提取            │
              │  LLM 分类            │
              │  模糊匹配课程        │
              │  存储 + 分发         │
              └──────────┬───────────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
    CourseContentTree  Assignment  PracticeProblem
    (层级内容树)      (作业)       (测验题)
           │
           ▼
    ┌──────────────┐    ┌──────────────┐
    │ Hybrid Search│◄───│ User Message │
    │ K + V + Tree │    └──────┬───────┘
    │ RRF Fusion   │           │
    └──────┬───────┘    ┌──────┴───────┐
           │            │ Preferences  │
           ▼            │ 7-layer      │
    ┌──────────────┐    │ cascade      │
    │ LLM Router   │◄───┴──────────────┘
    │ + Memory     │
    │ + RAG context│
    └──────┬───────┘
           │
           ▼
    SSE 流式响应 ──────────────┐
           │                   │
           ▼                   ▼
    前端面板渲染          异步后处理
                    ┌─────────┴─────────┐
                    ▼                   ▼
            Signal Extractor    Memory Encoder
            (偏好信号提取)      (对话记忆编码)
                    │                   │
                    ▼                   ▼
            PreferenceSignal    ConversationMemory
            (累积 → 晋升)      (pgvector embedding)
```

---

## 5. 技术设计 (Technical Design)

### 5.1 偏好系统 — 7 层级联 (Git Config Pattern)

**核心创新**: 仿照 Git 的配置级联（system → global → local），实现 7 层偏好覆盖。

```
优先级 (高 → 低):
1. temporary    — 本次会话临时偏好 (最高优先级)
2. course_scene — 课程+场景特定 (Phase 1)
3. course       — 课程级偏好
4. global_scene — 全局+场景特定 (Phase 1)
5. global       — 全局用户偏好
6. template     — 学习模板预设
7. system_default — 系统默认值 (最低优先级)
```

**偏好维度** (7 个):
| 维度 | 可选值 | 默认 |
|------|--------|------|
| `note_format` | bullet_point, table, mind_map, step_by_step, summary | bullet_point |
| `detail_level` | concise, balanced, detailed | balanced |
| `language` | en, zh, auto | en |
| `layout_preset` | balanced, notesFocused, quizFocused, chatFocused, fullNotes | balanced |
| `explanation_style` | formal, conversational, socratic, example_heavy, step_by_step | step_by_step |
| `quiz_difficulty` | easy, adaptive, hard | adaptive |
| `visual_preference` | auto, text_heavy, diagram_heavy, mixed | auto |

**信号提取流程** (openakita Compiler Pattern):
```
对话完成后 (异步):
  1. LLM 分析 user_message + assistant_response
  2. 默认不提取 (~95% 返回 NONE)
  3. 如有信号 → 创建 PreferenceSignal
  4. 计算置信度:
     confidence = base_score × frequency × recency × consistency
     - 显式表达 base=0.7, 修改行为=0.5, 行为推断=0.3
     - frequency = min(count/5, 1.0)
     - recency = exp(-days/90)
  5. 置信度 ≥ 0.4 → 晋升为 UserPreference
```

### 5.2 记忆系统 — EverMemOS 3 阶段

```
Stage 1: ENCODE (编码)
  对话 → LLM 摘要 → OpenAI embedding (1536-dim) → ConversationMemory

Stage 2: CONSOLIDATE (巩固)
  词重叠聚类 (threshold=0.7)
  指数衰减: importance × exp(-days/90)
  去重合并

Stage 3: RETRIEVE (检索)
  用户消息 → embedding → pgvector 余弦距离
  最小相似度 0.3
  Top-K 注入 system prompt
```

### 5.3 LLM 路由 — Provider Registry + Circuit Breaker

```
支持提供商:
  ├── OpenAI (gpt-4, gpt-4o-mini, gpt-3.5-turbo)
  ├── Anthropic (claude-3)
  ├── DeepSeek
  └── Ollama (本地模型)

Circuit Breaker:
  - 3 次连续失败 → 断路器打开
  - 渐进冷却: [5s, 10s, 20s, 60s]
  - 120s 后自动重置

Fallback Chain:
  Primary → Backup1 → Backup2 → Error
```

### 5.4 混合搜索 — RRF Fusion

```
3 路检索:
  ├── Keyword Search: 多词 BM25-lite, level boost
  ├── Vector Search: pgvector 余弦相似度
  └── Tree Search: PageIndex 层级导航

RRF 融合排名:
  score = Σ 1/(60 + rank_i) for each retriever
```

### 5.5 FSRS 间隔重复

从零实现 FSRS-4.5 算法（比 Anki 的 SM-2 精确 30%+）:
- 17 个权重参数（来自研究论文）
- 评分: 1=Again, 2=Hard, 3=Good, 4=Easy
- 状态机: new → learning → review → relearning
- 调度: `max(1, round(stability))` 天
- Card 参数: difficulty (1-10), stability (天), retrievability

### 5.6 内容摄入 — 7 步管道

```
Step 0: SHA-256 去重
Step 1: MIME 类型检测 (python-magic / 扩展名)
Step 2: 内容提取
  ├── PDF → Marker → Markdown
  ├── PPTX → python-pptx → 文本
  ├── DOCX → python-docx → 文本
  ├── HTML → trafilatura → 文本
  └── TXT/MD → 直接读取
Step 3: LLM 分类 (lecture_slides, textbook, assignment, exam_schedule, syllabus, notes, other)
Step 4: 模糊课程匹配 (thefuzz, 70% 阈值)
Step 5: 内容树构建 (PageIndex stack-based heading parser)
Step 6: 分发 (content_tree, assignments)
```

### 5.7 浏览器自动化 — 3 层级联

```
Layer 1: httpx (简单 HTTP, 最快)
    ↓ 失败
Layer 2: Scrapling (反 anti-bot, JS 渲染)
    ↓ 失败
Layer 3: Playwright (完整浏览器, session 持久化)
```

### 5.8 工作流引擎 — LangGraph StateGraph

WF-4 (学习会话) 和 WF-2 (每周准备) 使用 LangGraph StateGraph:
```python
# WF-4 Study Session
load_context → search_content → generate_response → extract_signals

# WF-2 Weekly Prep
load_deadlines → load_stats → generate_plan
```

### 5.9 自然语言界面控制 — CopilotKit Pattern

LLM 在响应中嵌入 `[ACTION:...]` 标记，前端解析后执行:
```
[ACTION:set_layout_preset:notesFocused]    → 扩大笔记面板
[ACTION:set_preference:note_format:table]  → 切换笔记格式为表格
```

### 5.10 前端状态管理

**CourseStore (Zustand)**:
```
courses[], activeCourse, contentTree[], loading, error
fetchCourses(), setActiveCourse(), addCourse(), removeCourse(), fetchContentTree()
```

**ChatStore (Zustand)**:
```
messages[], isStreaming, error, onAction callback
sendMessage() — SSE 流式迭代, 解析 content/action events
```

---

## 6. 新文件清单 (New Files)

### 后端 (apps/api/) — 75 文件

| 文件路径 | 用途 |
|----------|------|
| `main.py` | FastAPI 应用入口, 11 个路由挂载, 生命周期管理 |
| `config.py` | Pydantic Settings 配置 (DB, LLM, Upload) |
| `database.py` | SQLAlchemy async engine + session factory |
| `models/__init__.py` | 14 个 ORM 模型注册 |
| `models/user.py` | 用户模型 (单用户模式) |
| `models/course.py` | 课程模型 + 关联关系 |
| `models/content.py` | 课程内容树 (层级 PageIndex 结构) |
| `models/preference.py` | 用户偏好 + 偏好信号 |
| `models/practice.py` | 练习题 + 做题结果 |
| `models/memory.py` | 对话记忆 + pgvector 嵌入 |
| `models/ingestion.py` | 摄入任务, 学习会话, 作业, 错题 |
| `models/progress.py` | 学习进度 + 学习模板 |
| `routers/__init__.py` | 路由模块初始化 |
| `routers/upload.py` | 文件上传 + URL 抓取端点 |
| `routers/chat.py` | SSE 流式聊天 + RAG + 偏好注入 |
| `routers/courses.py` | 课程 CRUD + 内容树查询 |
| `routers/preferences.py` | 偏好管理 + 级联解析 |
| `routers/quiz.py` | 测验提取 + 答案提交 |
| `routers/notes.py` | AI 笔记重构 |
| `routers/workflows.py` | 6 个学习工作流端点 |
| `routers/progress.py` | 进度追踪 + 模板管理 + 知识图谱 |
| `routers/flashcards.py` | FSRS 闪卡生成 + 复习 |
| `routers/canvas.py` | Canvas LMS 登录 + 同步 |
| `routers/notifications.py` | 通知列表 + 已读标记 |
| `schemas/course.py` | 课程请求/响应 Pydantic 模型 |
| `schemas/preference.py` | 偏好请求/响应模型 |
| `schemas/chat.py` | 聊天请求/响应模型 |
| `services/llm/router.py` | LLM 提供商注册 + Circuit Breaker |
| `services/parser/pdf.py` | PDF → Markdown → 内容树 (PageIndex) |
| `services/parser/url.py` | URL 抓取 (trafilatura) |
| `services/parser/quiz.py` | LLM 题目提取 (7 种题型) |
| `services/parser/notes.py` | LLM 笔记重构 (5 种格式) |
| `services/preference/engine.py` | 7 层偏好级联解析器 |
| `services/preference/extractor.py` | 偏好信号提取 (5 维度, 4 信号类型) |
| `services/preference/confidence.py` | 置信度计算 + 信号晋升 |
| `services/preference/scene.py` | 场景检测 (7 种学习场景, regex) |
| `services/preference/prompt.py` | 偏好 → 自然语言 system prompt |
| `services/memory/pipeline.py` | EverMemOS 3 阶段记忆管道 |
| `services/ingestion/pipeline.py` | 7 步内容摄入管道 |
| `services/search/hybrid.py` | RRF 混合搜索 (关键词+向量+树) |
| `services/knowledge/graph.py` | 知识图谱构建 (D3 格式) |
| `services/progress/tracker.py` | 学习进度追踪 + 掌握度计算 |
| `services/scheduler/engine.py` | APScheduler 3 个后台任务 |
| `services/spaced_repetition/fsrs.py` | FSRS-4.5 算法实现 |
| `services/spaced_repetition/flashcards.py` | 闪卡生成 + 复习处理 |
| `services/templates/system.py` | 5 个内置学习模板 |
| `services/browser/automation.py` | 3 层浏览器级联 + Canvas 登录 |
| `services/workflow/graph.py` | LangGraph StateGraph 工作流引擎 |
| `services/workflow/semester_init.py` | WF-1 学期初始化 |
| `services/workflow/weekly_prep.py` | WF-2 每周准备 |
| `services/workflow/assignment_analysis.py` | WF-3 作业分析 |
| `services/workflow/study_session.py` | WF-4 学习会话 |
| `services/workflow/wrong_answer_review.py` | WF-5 错题复习 |
| `services/workflow/exam_prep.py` | WF-6 考前准备 |

### 前端 (apps/web/) — 35+ 文件

| 文件路径 | 用途 |
|----------|------|
| `src/app/layout.tsx` | 根布局 (metadata + Sonner toast) |
| `src/app/page.tsx` | 首页仪表盘 (课程卡片网格, 自动引导跳转) |
| `src/app/course/[id]/page.tsx` | 课程工作区 (4 面板可调布局 + 键盘快捷键) |
| `src/app/onboarding/page.tsx` | 5 步偏好引导 (分屏设计) |
| `src/app/new/page.tsx` | 4 步项目创建流程 (上传+解析+功能选择) |
| `src/app/settings/page.tsx` | 设置页 (语言切换 + 模板应用) |
| `src/components/course/notes-panel.tsx` | 笔记面板 (TOC 导航 + Markdown 渲染) |
| `src/components/course/quiz-panel.tsx` | 测验面板 (交互式答题 + 颜色反馈) |
| `src/components/course/flashcard-panel.tsx` | 闪卡面板 (翻转动画 + FSRS 评分) |
| `src/components/course/progress-panel.tsx` | 进度面板 (分段进度条 + 统计卡) |
| `src/components/course/knowledge-graph.tsx` | 知识图谱 (Canvas 2D 力导向图) |
| `src/components/course/markdown-renderer.tsx` | Markdown 渲染器 (KaTeX + Mermaid) |
| `src/components/course/upload-dialog.tsx` | 上传对话框 (文件 + URL 两种模式) |
| `src/components/course/pdf-viewer.tsx` | PDF 查看器 (占位符, Phase 1) |
| `src/components/course/nl-tuning-fab.tsx` | 自然语言调优浮动按钮 |
| `src/components/chat/chat-panel.tsx` | 对话面板 (SSE 流式 + 消息气泡) |
| `src/components/preference/onboarding-wizard.tsx` | 偏好引导向导组件 |
| `src/components/preference/preference-confirm-dialog.tsx` | 偏好确认对话框 |
| `src/components/workspace/activity-bar.tsx` | 左侧活动栏 (VS Code 风格) |
| `src/components/workspace/status-bar.tsx` | 底部状态栏 |
| `src/components/workspace/breadcrumbs.tsx` | 面包屑导航 |
| `src/components/ui/*.tsx` | 11 个 shadcn/ui 基础组件 |
| `src/store/course.ts` | Zustand 课程状态管理 |
| `src/store/chat.ts` | Zustand 聊天状态管理 |
| `src/lib/api.ts` | REST API 客户端 + SSE 流解析 |
| `src/lib/quiz-api.ts` | 测验 API 客户端 |
| `src/lib/i18n.ts` | 国际化 (6 语言, 100+ 键) |
| `src/lib/utils.ts` | Tailwind 类名合并工具 |
| `src/app/globals.css` | OKLCH 色彩系统 + 设计 token |

---

## 7. API 端点汇总 (All Endpoints)

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/content/upload` | POST | 上传文件 (PDF/PPTX/DOCX/HTML/TXT/MD) |
| `/api/content/url` | POST | 抓取 URL 并摄入 |
| `/api/content/jobs/{course_id}` | GET | 查看摄入任务列表 |
| `/api/chat/` | POST | SSE 流式聊天 (RAG + 偏好) |
| `/api/courses/` | GET | 列出所有课程 |
| `/api/courses/` | POST | 创建新课程 |
| `/api/courses/{id}` | GET | 获取课程详情 |
| `/api/courses/{id}` | DELETE | 删除课程 (级联) |
| `/api/courses/{id}/content-tree` | GET | 获取课程内容树 |
| `/api/preferences/` | GET | 查看用户偏好 |
| `/api/preferences/` | POST | 创建/更新偏好 (Upsert) |
| `/api/preferences/resolve` | GET | 级联解析有效偏好 |
| `/api/quiz/extract` | POST | 从内容提取测验题 |
| `/api/quiz/{course_id}` | GET | 列出课程所有题目 |
| `/api/quiz/submit` | POST | 提交答案获取反馈 |
| `/api/notes/restructure` | POST | AI 笔记重构 |
| `/api/workflows/semester-init` | POST | WF-1 学期初始化 |
| `/api/workflows/weekly-prep` | GET | WF-2 每周准备 |
| `/api/workflows/assignment-analysis` | POST | WF-3 作业分析 |
| `/api/workflows/wrong-answer-review` | GET | WF-5 错题复习 |
| `/api/workflows/wrong-answer-review/mark` | POST | 标记错题已复习 |
| `/api/workflows/exam-prep` | POST | WF-6 考前准备 |
| `/api/progress/courses/{id}` | GET | 学习进度概览 |
| `/api/progress/templates` | GET | 列出学习模板 |
| `/api/progress/templates/apply` | POST | 应用学习模板 |
| `/api/progress/templates/seed` | POST | 种子内置模板 |
| `/api/progress/courses/{id}/knowledge-graph` | GET | 知识图谱数据 |
| `/api/flashcards/generate` | POST | 生成 FSRS 闪卡 |
| `/api/flashcards/review` | POST | 复习闪卡 (FSRS 评分) |
| `/api/canvas/login` | POST | Canvas LMS 浏览器登录 |
| `/api/canvas/sync` | POST | 同步 Canvas 课程/作业 |
| `/api/notifications/` | GET | 获取通知列表 |
| `/api/notifications/{id}/read` | POST | 标记通知已读 |

---

## 8. 数据模型 (14 Tables)

```
User ──────────────────────────────────────┐
  │                                         │
  ├── Course ─────────────────────────────┐ │
  │     ├── CourseContentTree (self-ref)   │ │
  │     ├── PracticeProblem               │ │
  │     │     └── PracticeResult          │ │
  │     ├── Assignment                    │ │
  │     ├── LearningProgress              │ │
  │     └── IngestionJob                  │ │
  │                                       │ │
  ├── UserPreference                      │ │
  ├── PreferenceSignal                    │ │
  ├── ConversationMemory (pgvector 1536d) │ │
  ├── StudySession                        │ │
  ├── WrongAnswer                         │ │
  └── (references) LearningTemplate       │ │
                                          │ │
LearningTemplate (standalone, 5 built-in) ┘ ┘
```

### 关键表说明

| 表名 | 字段数 | 关键特性 |
|------|--------|----------|
| `users` | 3 | 单用户模式, Phase 0 |
| `courses` | 6 | JSONB metadata_, 级联删除 |
| `course_content_tree` | 10 | self-referential (parent_id), PageIndex 层级 |
| `user_preferences` | 9 | 3-7 层 scope, confidence 置信度 |
| `preference_signals` | 7 | 4 种信号类型, JSONB context |
| `practice_problems` | 8 | 7 种题型, JSONB options |
| `practice_results` | 5 | 对错判定, AI 解释 |
| `conversation_memories` | 9 | Vector(1536) embedding, importance 衰减 |
| `ingestion_jobs` | 15 | SHA-256 去重, 7-step 状态机 |
| `study_sessions` | 9 | 消息/做题/信号计数 |
| `assignments` | 8 | Canvas/手动来源, 截止日期 |
| `wrong_answers` | 8 | review_count, mastered flag |
| `learning_progress` | 12 | mastery_score, FSRS ease_factor |
| `learning_templates` | 7 | JSONB preferences, is_builtin |

---

## 9. 前端路由与 UI 架构

### 路由表

| 路由 | 页面 | 描述 |
|------|------|------|
| `/` | Dashboard | 课程卡片网格, 首次引导跳转 |
| `/onboarding` | Onboarding | 5 步偏好设置 (分屏) |
| `/new` | New Project | 4 步创建流程 (模式→上传→解析→功能) |
| `/course/[id]` | Workspace | 4 面板学习工作区 |
| `/settings` | Settings | 语言切换 + 模板管理 |

### 课程工作区布局

```
┌───────────────────────────────────────────────────────────────┐
│ Breadcrumbs: Course > Chapter > Section                       │
├────┬──────────┬──────────┬─────────────────┬──────────────────┤
│    │          │          │  Tab: Quiz      │                  │
│ A  │  PDF     │  AI      │  Tab: Flashcard │    Chat         │
│ c  │  Viewer  │  Notes   │  Tab: Progress  │    Panel        │
│ t  │  (25%)   │  (25%)   │  Tab: KG        │    (25%)        │
│ i  │          │          │     (25%)       │                  │
│ v  │          │          │                 │                  │
│ i  │          │          │                 │                  │
│ t  │          │          │                 │                  │
│ y  │          │          │                 │                  │
│    │          │          │                 │                  │
│ B  │          │          │                 │                  │
│ a  │          │          │                 │                  │
│ r  │          │          │                 │                  │
├────┴──────────┴──────────┴─────────────────┴──────────────────┤
│ Hidden Panels Restore Bar (collapsed panels shown here)       │
├───────────────────────────────────────────────────────────────┤
│ Status Bar: Course Name │ Chapter │ Practice │ Study Time     │
└───────────────────────────────────────────────────────────────┘
                                                ┌─────────────┐
                                                │ NL Tuning   │
                                                │ FAB Button  │
                                                └─────────────┘
```

**布局预设** (Cmd+0/1/2/3):
| 快捷键 | 预设 | PDF | Notes | Quiz | Chat |
|--------|------|-----|-------|------|------|
| Cmd+0 | balanced | 25% | 25% | 25% | 25% |
| Cmd+1 | notesFocused | 15% | 45% | 20% | 20% |
| Cmd+2 | quizFocused | 15% | 15% | 50% | 20% |
| Cmd+3 | chatFocused | 15% | 15% | 15% | 55% |

---

## 10. 借鉴的设计模式

| 来源项目 | 模式 | 在 OpenTutor 中的应用 |
|----------|------|----------------------|
| EverMemOS | 3 阶段记忆管道 | `services/memory/pipeline.py` |
| PageIndex | 基于标题的 Markdown 树解析 | `services/parser/pdf.py` |
| openakita | 双轨 LLM + "默认不提取" | `services/preference/extractor.py` |
| openakita | Compiler 模式轻量提取 | 信号提取异步后处理 |
| nanobot | Provider Registry 关键词注册 | `services/llm/router.py` |
| spaceforge | FSRS 闪卡 UI 模式 | `components/course/flashcard-panel.tsx` |
| CopilotKit | NL → UI 控制 via ACTION 标记 | `routers/chat.py` [ACTION:...] |
| Marker | PDF → Markdown 转换 | `services/parser/pdf.py` |
| Git | 配置级联 (system→global→local) | `services/preference/engine.py` |

---

## 11. 技术栈总结

### 后端依赖
| 类别 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.115.6 |
| 服务器 | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy (async) | 2.0.36 |
| 数据库 | PostgreSQL + pgvector | 0.3.6 |
| 缓存 | Redis | 5.2.1 |
| LLM | OpenAI + Anthropic | 1.65.2 / 0.46.0 |
| 工作流 | LangGraph | ≥0.2.0 |
| 调度 | APScheduler | ≥3.10.0 |
| PDF | Marker (optional) + trafilatura | 2.0.0 |
| 浏览器 | Scrapling + Playwright | ≥0.2 / ≥1.49.0 |
| Canvas | canvasapi | ≥3.3.0 |

### 前端依赖
| 类别 | 技术 | 版本 |
|------|------|------|
| 框架 | Next.js | 16.1.6 |
| UI | React | 19.2.3 |
| 状态 | Zustand | 5.0.11 |
| 样式 | Tailwind CSS | 4 |
| 组件库 | Radix UI + shadcn | latest |
| 面板 | react-resizable-panels | 4.6.5 |
| Markdown | react-markdown + KaTeX + Mermaid | latest |
| 通知 | Sonner | 2.0.7 |
| 图标 | lucide-react | 0.575.0 |

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 服务不可用 | 核心功能瘫痪 | Circuit Breaker + 多提供商 Fallback |
| pgvector 性能瓶颈 | 记忆检索变慢 | 最小相似度阈值 + Top-K 限制 |
| PDF 解析质量差 | 内容树残缺 | Marker (高质量) fallback PyPDF2 |
| 偏好信号噪音 | 错误偏好覆盖 | "默认不提取" (~95% NONE) + 置信度阈值 |
| 单用户模式安全性 | 无认证保护 | 仅限本地部署, Phase 1 加认证 |
| 大文件上传 | 内存溢出 | 50MB 上限 + SHA-256 去重 |
| Canvas session 过期 | 同步中断 | Session 持久化 + 过期提醒通知 |
| react-resizable-panels v4 API 变更 | 布局控制异常 | 已适配 v4 API (useGroupRef, orientation) |

---

## 13. 统计摘要

| 指标 | 数值 |
|------|------|
| 总代码行数 | ~12,110 LOC |
| 提交次数 | 2 (Phase 0-A, Phase 0-B+C) |
| 后端源文件 | ~75 |
| 前端源文件 | ~35 |
| ORM 数据表 | 14 |
| API 端点 | 34 |
| API 路由模块 | 11 |
| 服务模块 | 14 |
| 学习工作流 | 6 |
| 偏好维度 | 7 |
| 偏好级联层 | 7 |
| 题目类型 | 7 |
| LLM 提供商 | 4 |
| 内置学习模板 | 5 |
| i18n 语言 | 6 |
| i18n 翻译键 | 100+ |
| 前端路由 | 6 |
| 前端面板 | 4 (可调大小) |
| 布局预设 | 5 |
