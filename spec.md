# 个性化学习Agent - 完整项目规划文档

> 生成日期：2026-02-14
> 基于两份PDF设计文档 + 22个克隆项目分析 + 28个决策问题的确认结果

---

## 目录

1. [项目概述](#1-项目概述)
2. [已确认的所有决策](#2-已确认的所有决策)
3. [技术补充方案](#3-技术补充方案)
4. [克隆项目分析与使用映射](#4-克隆项目分析与使用映射)
5. [建议补充clone的项目](#5-建议补充clone的项目)
6. [技术架构设计](#6-技术架构设计)
7. [项目目录结构](#7-项目目录结构)
8. [分阶段实施计划](#8-分阶段实施计划)
9. [验证标准](#9-验证标准)
10. [自建组件拆解](#10-自建组件拆解)

---

## 1. 项目概述

### 核心问题
你有固定的学习方法，但每次用ChatGPT都要：
- **重复放prompt** → 需要预设工作流/prompt模板，一键执行
- **没有记忆偏好** → 需要黑盒偏好系统，记住学习方式
- **自己找资料太麻烦** → Agent要能自动从Canvas拉数据+整理
- **帮其他学生用AI** → 需要预配置的学习模板，新用户开箱即用

### 产品形态
类OpenClaw的自主学习Agent：
- **开源项目，本地部署**（参考OpenClaw）
- **本地运行 + Web界面**
- Agent能**自主执行任务**（拉Canvas数据、生成学习计划），但**不代替用户操作**
- 核心壁垒：黑盒偏好系统 + LMS集成 + 间隔重复 + 知识图谱

### 核心差异化
1. **黑盒偏好学习系统** - AI从行为中学习用户偏好，而非让用户填表
2. **多层记忆系统** - 长期偏好 → 课程级偏好 → 课程结构 → 学习进度 → 对话上下文
3. **LMS集成** - 接入Canvas等大学学习管理系统
4. **6大工作流** - 学期初始化、每周准备、作业分析、学习Session、错题复习、考前规划
5. **类OpenClaw架构** - 自主执行任务的Agent，不只是聊天

### 产品一句话定位

**给我任何学习材料，我帮你变成一个属于你的、越用越懂你的个性化学习网站**

具体来说：上传PDF/PPT 或 给一个URL → Agent自动抓取+解析 → 按你的偏好重构成交互式笔记+做题界面+AI问答 → 从行为中持续优化体验 → 自然语言微调整个界面

**不绑定任何平台**。Canvas/Blackboard/教授网站/在线教材——什么来源都行，核心是"内容→个性化学习空间"的转化。

### 与竞品的本质区别

| 竞品 | 它的边界 | 你跨越了什么 |
|------|---------|------------|
| ChatGPT | 只能对话，无记忆，只输出文字 | 输出的不是文字，是一个学习网站 |
| NotebookLM | 理解文档但只能聊天，被动封闭 | 把文档变成交互式学习空间（笔记+做题+问答） |
| Canvas/Blackboard | 只是放资料的仓库 | AI自动整理+重构+个性化呈现 |
| OpenClaw/Manus | 通用Agent，需学习配置 | 零门槛，从行为自动学习，自然语言微调 |
| Quizlet/Anki | 只做闪卡，需手动输入 | 自动从任何材料生成，和笔记/问答一体化 |
| Coursera/Khan | 固定课程，固定格式 | 任何材料都能变成你的个性化课程 |

### 三大核心面板

用户面对的产品体验由三个核心面板组成，工作流在后台驱动面板内容生成：

**核心面板1: 📝 AI笔记面板**

| 功能 | 说明 |
|------|------|
| PDF课件解析 | Marker将PDF转Markdown → PageIndex构建内容树 |
| AI笔记重构 | 根据用户偏好将课件内容重新组织（bullet point/思维导图/表格/步骤图等） |
| 自动可视化 | AI判断内容最适合的展示形式，用Mermaid/KaTeX/表格等自动渲染 |
| 章节导航 | 内容树导航，点击跳转到对应章节 |

**核心面板2: ✏️ 交互式做题面板**

| 功能 | 说明 |
|------|------|
| PDF题目提取 | AI从PDF中识别和拆分练习题（题目+选项/要求） |
| 交互式答题 | 一题一题展示，用户作答后提交 |
| 答案+AI解析 | 显示官方答案（如有）+ AI生成的解析（引用课件内容） |
| 做题记录 | 记录对错，供偏好系统学习薄弱点 |

**核心面板3: 💬 AI对话助手**

| 功能 | 说明 |
|------|------|
| 个性化对话 | 偏好注入System Prompt，按用户偏好风格回答 |
| 课件RAG | 引用具体课件章节回答问题（LLM树搜索） |
| 自动可视化回答 | 回答中自动生成思维导图/流程图/公式等 |
| 偏好信号提取 | 对话后异步提取偏好信号（双轨LLM，默认不提取） |

### 核心产品体验

```
任何学习材料
├── 上传 PDF/PPT/图片
├── 给一个URL（教授网站/课程页/在线教材）
└── (未来) Canvas/Blackboard扩展自动同步
    ↓
Agent 自动抓取 + 解析 + 重构
    ↓
┌─────────────────────────────────────┐
│  你的个性化学习网站（本地运行）        │
│                                     │
│  📝 笔记面板          💬 AI问答      │
│  AI按你的偏好重构     选中内容提问    │
│  任何材料的内容       引用原文回答    │
│  (思维导图/bullet/                   │
│   表格/步骤图...)                    │
│                                     │
│  ✏️ 做题面板                         │
│  自动从材料提取题目   一题题做       │
│  提交→看答案+AI解析                  │
│                                     │
│  🎨 自然语言微调                      │
│  "笔记换思维导图" / "做题放大"        │
└─────────────────────────────────────┘
    ↓
从使用行为中持续学习偏好 → 越用越懂你
```

### 偏好三步走（核心体验）

1. **Step 1: 简单选项初始化** — Onboarding选择输出格式/详细程度/语言等（2-3个问题）
2. **Step 2: 自然语言微调** — "太长了"/"换成思维导图"/"做题放大点"
3. **Step 3: 行为自动学习** — 从使用行为中自动提取偏好（复用openakita双轨提取）

三步在Phase 0都需要实现（Step 3 为简化版，完整版 Phase 1）。

### 布局系统

- 2-3套布局模板（经典三栏/笔记+问答/全屏做题等）
- 自然语言调整组件大小/位置/内容形式
- MVP先支持组件显示/隐藏和大小调整，不做拖拽

---

## 2. 已确认的所有决策

| 决策项 | 选择 | 原因 |
|--------|------|------|
| **前端** | Next.js + shadcn/ui + Vercel AI SDK（从零搭） | 学习Agent需要定制UI，fork lobe-chat改造量反而更大 |
| **后端** | Python FastAPI | langgraph/canvasapi都是Python生态 |
| **工作流引擎** | LangGraph | 状态化Agent workflow，已clone |
| **记忆系统** | EverMemOS 三阶段模式（PostgreSQL+pgvector 实现） | 编码→巩固→检索，自建偏好+对话记忆 |
| **数据库** | PostgreSQL + pgvector | PDF的SQL Schema直接用，pgvector做向量搜索 |
| **LMS** | Canvas（canvasapi库） | 用户当前使用的LMS |
| **LLM** | 多模型支持（OpenClaw思路），用户自配API Key | 开源项目需要灵活性 |
| **间隔重复** | FSRS算法 | 比Anki的SM-2精确度高30%+ |
| **文件解析** | Marker/docling（可配置深度） | MVP先文本+结构，后期加图片/公式 |
| **部署** | Docker本地部署（参考OpenClaw） | 开源项目，用户本地自部署 |
| **偏好确认** | 过程中静默调整→任务结束后总结→用户选择长期/短期/学科内 | 不打断学习流程 |
| **开发方式** | 用户 + AI (Claude) | AI辅助开发，架构要模块化清晰 |
| **笔记格式** | 用户可选（总结/闪卡/思维导图等） | 偏好系统学习常用格式 |
| **交互模式** | 用户可选+偏好学习（文本/代码/白板等） | MVP先纯文本，后期扩展 |
| **进度粒度** | 逐步细化（课程级→章节级→知识点级） | 渐进式精确 |
| **Agent边界** | 主动提醒 + 自动学习准备，不代替用户操作 | 安全的自主边界 |
| **商业模式** | 开源本地部署（参考OpenClaw） | 本地运行，不做云版 |
| **目标用户** | 开源项目，任何人可自部署 | 最大化影响力 |

---

## 3. PDF缺失部分的技术补充方案

### PDF1 缺失项

#### 1. 场景识别实现
建议方案：LLM分类 + 规则混合
- **第一层**：关键词/正则匹配（零成本）
  - "这道题"/"homework" → 作业场景
  - "考试"/"exam"/"quiz" → 考前场景
  - "复习"/"review" → 复习场景
  - "这周"/"this week" → 每周准备场景
- **第二层**：LLM few-shot分类（仅在第一层未命中时触发）
  - 用小模型（Haiku/4o-mini）分类到6种工作流场景
  - 成本极低：~$0.001/次分类

#### 2. 修改行为检测
建议方案：结构化diff而非编辑器事件
- 用户复制AI输出并修改后发回 → 用Python `difflib`检测改了什么
- 用户口头描述"太长了/换成表格" → 归类为显式表达信号
- MVP阶段：只处理显式表达 + 简单diff，不做复杂编辑器追踪

#### 3. 置信度计算公式
```
confidence = base_score × frequency_factor × recency_factor × consistency_factor

- base_score:
  - 显式表达 = 0.7
  - 修改行为 = 0.5
  - 行为模式 = 0.3

- frequency_factor: min(signal_count / 3, 1.0)
  # 3次相同信号达到满分

- recency_factor: exp(-days_since_last_signal / 90)
  # 90天半衰期

- consistency_factor: 1.0 - contradiction_rate
  # 矛盾信号越多越低
```

#### 3. 偏好衰减机制
- 指数衰减 + 重新确认
- 90天半衰期：`weight = exp(-age_days / 90)`
- 当weight降到0.3以下 → 标记为"待重新确认"
- 用户再次触发同类行为 → 重置衰减计时器

#### 4. 多语言NLP处理
- MVP阶段：不做复杂NLP，直接用LLM理解中英混合文本
- 偏好信号提取prompt：要求LLM输出结构化JSON（维度、值、置信度）
- 后期可引入langdetect分流不同语言的处理管道

#### 5. 两份PDF的集成规范
建议的API边界：
- **偏好系统对外暴露**：
  - `get_resolved_preferences(user_id, course_id, scene_type)` → 返回完整偏好JSON
- **产品框架调用**：
  - 在构建system prompt时调用上述API，注入偏好
- **偏好系统输入**：
  - `record_signal(user_id, signal_type, raw_data, context)` → 产品框架在每次对话后调用

### PDF2 缺失项

#### 6. 多LLM路由策略

| 任务 | 推荐模型 | 原因 |
|------|---------|------|
| 学习对话 | Claude Sonnet 4.5 / GPT-4o | 质量+速度平衡 |
| 偏好信号提取 | Claude Haiku / GPT-4o-mini | 结构化输出，低成本 |
| 文件结构化 | Claude Sonnet / GPT-4o | 需要理解能力 |
| 场景分类 | Haiku / 4o-mini | 简单分类任务 |
| 笔记生成 | Claude Sonnet / GPT-4o | 质量要求高 |

注：用户可通过环境变量自行配置，不绑定特定模型。

#### 7. 文件解析管道（更新：集成PageIndex树形索引）

```
PDF   → Marker → Markdown → PageIndex树形索引 → course_content_tree
                              ↓
                    自动提取: 目录检测 → 层级构建 → 验证修正 → 摘要生成
                              ↓
                    输出: {title, node_id, start_index, end_index, summary, children}

PPTX  → python-pptx → 文本+图片提取 → LLM结构化
HTML  → BeautifulSoup → 清洗文本 → LLM结构化
```

**PageIndex集成方案**：
- PDF教材先用Marker转Markdown，再用PageIndex的`md_to_tree()`构建层级树
- 或直接用PageIndex的`page_index()`处理原始PDF，自动检测目录并构建树
- 树节点直接映射到`course_content_tree`表的行
- 学生查询时用LLM推理式树搜索定位相关章节，而非向量相似度

#### 8. 三路径数据获取系统（v2 优化版）

学生的学习资料来源分散，需要统一入口把所有内容自动分析、归类。三条获取路径汇聚到统一分类流水线。

**Path 1: 手动上传 + 自动分类**
- 用户上传 PDF/PPT/截图/文档等任意文件
- 多模态 LLM (GPT-4o/Claude vision) 直接分析内容
- 自动分类到：**课程** + **文件类型** (lecture_slides / exam_schedule / assignment / syllabus / textbook / notes)
- 上传时可选指定课程 → 跳过课程分类，只分类 file_type，省 LLM 费用
- 用户可通过对话微调归类结果："这个应该归到 CS101"

**Path 2: Chrome 扩展 Canvas 自动提取**
- Manifest V3 Chrome 扩展，运行在 Canvas 页面
- 使用 Canvas REST API v1 + session cookies (`credentials: 'include'`) 提取
- **关键优化：Canvas 数据分流**
  - 结构化数据（作业/日历/公告）→ **直接入库**，不走 LLM 分类流水线
  - 课程文件（PDF/PPT）→ 课程已知，只分类 file_type（跳过课程分类）
- Canvas URL 检测：`*.edu/*`, `*.instructure.com/*`, `*.canvaslms.com/*`

**Path 3: 自然语言 → 浏览器自动化（三层降级链）**
- 用户在对话中说"帮我去教授网站抓 syllabus"或"去这个链接拿考试日期"
- **三层降级**（对比原设计两层）：
  1. httpx + readability（免费、毫秒级）— 大部分教授网站够用
  2. Firecrawl（付费、能绕反爬）— readability 失败时
  3. browser-use（重、但能处理 JS 渲染/登录）— 最后手段

**统一分类流水线（优化版 7 步）**
```
Step 0: 预处理
  ├── SHA-256 内容哈希去重（防止重复上传/重复同步）
  ├── 文件名正则预分析（"CS101_lecture_05.pdf" → 不调LLM直接归类）
  └── 用户/Canvas预指定课程 → 跳过课程分类

Step 1: MIME 检测（零成本）
Step 2: 内容提取（Marker/python-pptx/多模态LLM base64）
Step 3: LLM 分类（可跳过课程分类、可批量）
Step 4: 课程模糊匹配
Step 5: 存储到 ingestion_jobs 表
Step 6: 分发到业务表
  ├── exam_schedule → 提取日期 → 日历/assignments.due_date
  ├── textbook/lecture_slides → PageIndex 树索引 → course_content_tree
  ├── syllabus → 课程结构提取
  └── assignment → 作业信息入库
```

**前端交互优化**：分类进度通过 SSE 实时推送（复用 Vercel AI SDK 基础设施），非轮询。

**新增数据库表**：`ingestion_jobs` — 追踪所有数据获取任务，含 content_hash(去重)、course_preset(跳过标记)、dispatched(分发追踪)、用户修正记录。

**实施顺序**：
- Phase A: 统一分类流水线 + 文件上传（地基）
- Phase B: Chrome 扩展 Canvas 提取（含 Canvas 数据分流）
- Phase C: 浏览器自动化（三层降级链）
- Phase D: 对话式微调

**完整架构计划文件**：`~/.claude/plans/logical-gliding-ladybug.md`

#### 9. 监控方案
- **错误追踪**：Sentry（免费tier）
- **用户行为**：PostHog（开源，可自部署）
- **LLM调用日志**：Langfuse 或 LangSmith（免费tier够用）

#### 9. 测试策略
- **后端**：pytest（API测试 + 偏好引擎单元测试）
- **前端**：Vitest + React Testing Library
- **AI质量**：人工标注10-20个测试用例，对比有偏好/无偏好输出

---

## 4. 克隆项目分析与使用映射

### 已有项目完整分析

| 项目 | 技术栈 | 可用于 | 使用方式 | 何时用 |
|------|--------|--------|---------|--------|
| **EverMemOS** | Python, FastAPI | **记忆系统核心** | 照搬三阶段流水线模式，PostgreSQL+pgvector 实现 | **Phase 0** |
| **memU** | Python | 主动提醒设计参考 | 参考其24/7 proactive memory逻辑 | Phase 1 |
| **memvid** | Rust + Python/Node SDK | 课件内容快速检索（备选） | 备选：每门课打包成.mv2文件，超快检索 | Phase 2评估 |
| **lobe-chat** | Next.js, React | 前端UI设计参考 | 不fork，只参考UI设计和交互模式 | Phase 0-1 |
| **dify** | Python/Flask + React | RAG管道参考 | 参考其文档处理和RAG实现 | 架构参考 |
| **canvasapi** | Python | Canvas LMS集成 | 直接使用 (`pip install canvasapi`) | Phase 1 |
| **anki** | Python/Rust + Svelte | 间隔重复算法参考 | 参考FSRS算法在Anki中的实现 | Phase 2 |
| **langgraph** | Python | 工作流引擎 | 直接使用，每个WF一个StateGraph | Phase 0 |
| **MetaGPT** | Python | 多Agent架构参考 | 参考其Role-based Agent编排、SOP工作流架构 | 架构参考 |
| **nanobot** | Python | 轻量Agent架构参考 | 参考其简洁的多渠道Agent架构 | 架构参考 |
| **textbook_quality** | Python | 自动笔记生成参考 | 参考其内容生成管道 | Phase 1 |
| **browser-use** | Python | 浏览器自动化（P3） | Phase 3浏览器插件时参考 | Phase 3 |
| **PageIndex** | Python, OpenAI | 课程内容树形索引+推理式RAG | 借鉴树形文档索引构建、LLM推理式树搜索(替代向量检索)、多模式处理+验证修正 | **Phase 0-1** |
| **CanvasFlow** | JavaScript, OpenAI | Canvas数据提取+AI日程生成 | 参考AI结构化输出生成学习日程、工作量分析逻辑、Canvas DOM提取备用方案 | Phase 1 |
| **openakita** | Python | 信号提取+轻量调度器 | 借鉴双轨LLM调用(大模型对话/小模型提取)、"默认不提取"策略、asyncio调度器、Provider渐进冷却 | Phase 0 |
| **HelloAgents** | Python, OpenAI | Agent设计模式参考 | 参考"万物皆工具"统一接口、清晰的multi-agent教育代码 | 架构参考 |
| **hello-agents(教程)** | Python, 中文教程 | Agent完整学习路径 | 16章+社区项目，覆盖ReAct/Reflection/PlanAndSolve、记忆/RAG/多智能体协作、RL训练、评估 | 架构参考 |
| **nanobot** | Python | 超轻量Agent架构核心参考 | 4000行代码实现完整Agent：Provider Registry(2步添加新LLM)、Tool注册模式、多渠道网关、Cron集成 | **Phase 0** |
| **nanoclaw** | Node.js | 容器隔离+轻量设计参考 | 每用户容器隔离、per-group记忆(CLAUDE.md)、Skill可扩展架构、文件系统IPC | 架构参考 |
| **nanobrowser** | TypeScript | 多Agent浏览器自动化 | 三Agent协作(Planner/Navigator/Validator)、本地Chrome执行、可扩展LLM Provider | Phase 3 |
| **spaceforge** ⭐新增 | TypeScript, Obsidian | FSRS+AI闪卡生成核心参考 | 双算法(FSRS+SM-2)、6家AI Provider MCQ生成、事件日历、Pomodoro计时、完整复习历史追踪 | **Phase 2** |
| **LiteLLM** ⭐新增 | Python | LLM路由+熔断器+fallback | 统一接口调用100+ LLM，内置fallback链/负载均衡/渐进冷却/成本追踪，36k+ stars | **Phase 1** |
| **trafilatura** ⭐新增 | Python | URL内容抓取 | 高质量网页内容提取(优于readability)，支持元数据/正文/评论分离，自动去噪 | **Phase 0** |
| **Graphiti (Zep)** ⭐新增 | Python | 时序知识图谱记忆 | 20k+ stars，构建时序知识图谱，94.8%准确率(超MemGPT)，延迟降低90%，有LangGraph集成 | **Phase 1评估** |
| **MiroThinker** | Python | 深度研究Agent参考 | GAIA基准80.8%、MiroFlow框架、工具编排模式 | 架构参考 |
| **MetaGPT** | Python | 多Agent架构参考 | Role-based Agent编排、SOP驱动工作流 | 架构参考 |
| **smart-planner** | Python | 约束调度算法参考 | Google Calendar/Tasks集成、基于截止日期+预估时间+睡眠时间的约束调度 | Phase 1 |
| **canvas-assistant** | Python, Flask | 社交学习+日历集成 | Canvas作业→iCal导出、学习伙伴发现(共同课程匹配)、Flask后端 | Phase 1 |
| **quizperai** | JavaScript | 测验辅助模式参考 | Canvas测验提取+GPT-4答案生成+解释、Chrome扩展DOM自动化 | Phase 2 |
| **auto-mcgraw** | JavaScript | 多AI Provider作业辅助 | 多题型分类(MC/TF/填空)、三AI Provider路由(ChatGPT/Gemini/DeepSeek) | Phase 2 |
| **planit** | Python | 自动作业追踪 | Gradescope网页抓取、GitHub Actions自动化、日历生成 | Phase 1 |
| **notion-assignment-import** | JavaScript | LMS→外部工具集成 | Canvas→Notion属性映射、OAuth2流程、增量同步(delta检测) | Phase 1 |
| **smol-course** | Python | 模型微调参考 | DPO偏好对齐、评估框架、合成数据生成 | Phase 3 |

### 记忆系统方案（EverMemOS 三阶段模式 + PostgreSQL+pgvector）

**核心架构**：照搬 EverMemOS 三阶段流水线模式，但用 PostgreSQL+pgvector 实现（不引入 MongoDB/ES/Milvus）。

```
编码阶段（对话结束后）
├── 对话摘要提取 → 存入 conversation_memories 表
├── 偏好信号提取（openakita Compiler 双轨）→ 存入 preference_signals 表
└── 证据绑定：每条记忆追溯到 "日期|session_id"

巩固阶段（异步/定期）
├── 跨对话合并：相同偏好信号去重+强化
├── 置信度更新：frequency × recency × consistency
└── 衰减处理：exp(-days/90)，低于阈值标记待确认

检索阶段（对话开始时）
├── 课程内容：PageIndex 树形推理搜索（98.7%准确率）
├── 对话记忆：pgvector 向量检索
└── 偏好注入：cascade 解析 → System Prompt 注入
```

| 备选系统 | 核心能力 | 用途 | 阶段 |
|---------|---------|------|------|
| **memvid** | 单文件极速检索(0.025ms) | 备选：每课程一个.mv2文件 | Phase 2 评估 |
| **MemGPT/Letta** | LLM自管理记忆 | 备选：自管理长期记忆 | Phase 2 评估 |

### 课程内容检索方案（新增：PageIndex树形索引 vs 向量检索）

| 方案 | 核心机制 | 准确率 | 适用场景 | 阶段 |
|------|---------|--------|---------|------|
| **PageIndex树形索引** ⭐推荐 | PDF→树形结构索引→LLM推理导航→精确定位 | 98.7% (FinanceBench) | 教材/课件等有层级结构的文档，与course_content_tree天然匹配 | **Phase 0-1** |
| **pgvector向量检索** | 文本切块→向量化→余弦相似度搜索 | 一般70-85% | 非结构化对话记忆、模糊匹配 | Phase 0（对话记忆用） |
| **混合方案（推荐）** | 课程内容用PageIndex树搜索，对话记忆用向量检索 | 各取所长 | 完整系统 | Phase 0-1 |

**关键洞察**：你的`course_content_tree`表设计天然适合PageIndex的树形索引方式。教材有明确的章→节→知识点层级，用LLM推理导航比向量相似度更准确。向量检索更适合对话记忆这种非结构化内容。

---

## 5. 建议补充clone的项目

| 项目 | GitHub | 用途 | 优先级 |
|------|--------|------|--------|
| **Marker** | VikParuchuri/marker | PDF → Markdown高质量转换 | **P0 - MVP必须** |
| **py-fsrs** | open-spaced-repetition/py-fsrs | FSRS间隔重复算法Python版 | **P2 - 错题复习** |
| **MemGPT/Letta** | cpacker/MemGPT | 备选自管理长期记忆 | **P2 - 评估用** |
| **docling** | DS4SD/docling | IBM开源文档解析器（PDF/PPTX/DOCX/HTML） | P1 - 备选解析方案 |
| **Unstructured** | Unstructured-IO/unstructured | 通用文档解析管道 | P1 - 备选解析方案 |
| **spaceforge** ✅已clone | dralkh/spaceforge | FSRS+AI闪卡+日历+Pomodoro一体化 | **P2 - 间隔复习核心参考** |
| **rag-fusion** | Raudaschl/rag-fusion | RRF融合参考实现（多查询+RRF排名） | P0 - RRF实现参考 |

### Phase 0 新增依赖（pip install，不需clone）

| 库 | 安装 | 用途 | 阶段 |
|---|---|---|---|
| **trafilatura** | `pip install trafilatura` | URL网页内容高质量提取（优于readability，自动去噪+元数据分离） | **Phase 0-A** |
| **marker-pdf** | `pip install marker-pdf` | PDF → Markdown 高质量转换 | **Phase 0-A** |
| **pgvector** | `pip install pgvector` | pgvector 官方客户端 + EverMemOS 三阶段记忆流水线（encode→consolidate→retrieve） | **Phase 0-C** |
| **tenacity** | `pip install tenacity` | 标准Python重试库（指数退避+抖动） | Phase 0-A |
| **LiteLLM** | `pip install litellm` | LLM统一路由+内置fallback链+负载均衡+成本追踪（36k+ stars） | Phase 1 |
| **ranx** | `pip install ranx` | RRF融合排名算法库（含CombMNZ/BordaFuse等多种融合算法，学术级） | Phase 1 |
| **circuitbreaker** | `pip install circuitbreaker` | 轻量装饰器式熔断器（非LLM的外部服务容错） | Phase 1 |
| **canvasapi** | `pip install canvasapi` | Canvas LMS 数据拉取 | Phase 1 |
| **Graphiti** | `pip install graphiti-core[anthropic]` | Zep时序知识图谱记忆（20k+ stars，94.8%准确率） | Phase 1 评估 |

**执行命令**：
```bash
cd /Users/zijinzhang/Desktop/agent项目克隆代码
# 已clone的项目
git clone https://github.com/VikParuchuri/marker.git
git clone https://github.com/open-spaced-repetition/py-fsrs.git
git clone https://github.com/cpacker/MemGPT.git
# 新增参考项目
git clone https://github.com/Raudaschl/rag-fusion.git
```

---

## 6. 技术架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────┐
│                    用户界面层                         │
│  Next.js + shadcn/ui + Vercel AI SDK + Zustand      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │📝笔记面板 │ │✏️做题面板 │ │💬AI问答   │ ← 三核心面板│
│  │AI重构+    │ │题目提取+  │ │流式对话+  │            │
│  │Mermaid/   │ │交互答题+  │ │课件RAG+  │            │
│  │KaTeX渲染  │ │AI解析    │ │可视化回答 │            │
│  └──────────┘ └──────────┘ └──────────┘            │
│  ┌──────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │🎨布局系统     │ │ 偏好确认弹窗│ │ 课程/材料列表│  │
│  │模板+NL微调   │ │            │ │              │  │
│  └──────────────┘ └────────────┘ └──────────────┘  │
└───────────────────────┬─────────────────────────────┘
                        │ REST API + SSE
┌───────────────────────┴─────────────────────────────┐
│                    API层 (FastAPI)                    │
│  ┌──────┐ ┌────────┐ ┌────────┐ ┌──────┐ ┌───────┐ │
│  │Upload│ │ Courses│ │  Chat  │ │Prefs │ │Canvas │ │
│  └──────┘ └────────┘ └────────┘ └──────┘ └───────┘ │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────┴─────────────────────────────┐
│                    服务层                             │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐          │
│  ┌────────────┐ ┌──────────────┐ ┌──────────┐      │
│  │  偏好系统   │ │  记忆系统     │ │  工作流   │      │
│  │ (自建引擎)  │ │(EverMemOS模式)│ │(LangGraph)│      │
│  │            │ │              │ │          │      │
│  │ 7层解析    │ │ 对话上下文    │ │ WF-1~6   │      │
│  │ 信号检测   │ │ 偏好存储      │ │ 状态管理  │      │
│  │ (双轨提取) │ │ 混合检索+RRF  │ │ 条件分支  │      │
│  │ 置信度计算 │ │ 树搜索(课程)  │ │          │      │
│  │ Prompt注入 │ │ 向量(对话)    │ │          │      │
│  └────────────┘ └──────────────┘ └──────────┘      │
│  ┌────────────┐ ┌──────────────┐ ┌──────────┐      │
│  │  LLM统一接口│ │  文件解析     │ │内容输入   │      │
│  │ Claude/GPT │ │ Marker+      │ │PDF上传   │      │
│  │ DeepSeek.. │ │ PageIndex树索引│ │URL抓取   │      │
│  │ +熔断器容错 │ │ +题目提取    │ │(trafilatura)│    │
│  │ (LiteLLM)  │ │ +AI笔记重构  │ │Canvas API │      │
│  └────────────┘ └──────────────┘ └──────────┘      │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────┴─────────────────────────────┐
│                    数据层                             │
│  ┌──────────────┐  ┌─────────┐  ┌────────┐          │
│  │ PostgreSQL   │  │pgvector │  │ Redis  │          │
│  │ (结构化数据)  │  │(向量搜索)│  │ (缓存) │          │
│  │ 12+张表      │  │         │  │        │          │
│  └──────────────┘  └─────────┘  └────────┘          │
└─────────────────────────────────────────────────────┘
```

### 偏好系统架构（核心差异化）

```
用户对话
    │
    ▼
┌──────────────┐     ┌──────────────────┐
│ 信号检测模块  │────▶│ 偏好信号数据库     │
│ (对话结束后)  │     │ preference_signals│
└──────────────┘     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │ 置信度计算引擎    │
                     │ confidence.py     │
                     └────────┬─────────┘
                              │ 达到确认阈值？
                              ▼
                     ┌──────────────────┐
                     │ 偏好总结弹窗      │
                     │ (任务结束后显示)   │
                     └────────┬─────────┘
                              │ 用户选择：
                              │ 长期/短期/学科内
                              ▼
                     ┌──────────────────┐
                     │ 7层偏好数据库     │
                     │ user_preferences  │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │ 偏好解析引擎      │
                     │ engine.py         │
                     │ 7层cascade查询    │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │ System Prompt注入 │
                     │ prompt.py         │
                     └──────────────────┘
```

### 偏好7层解析流程

```
function resolvePreference(user_id, course_id, scene_type, dimension):

  1. 检查 临时偏好 (temporary) → 有则返回
  2. 检查 课程场景偏好 (course_scene: course_id + scene_type) → 有则返回
  3. 检查 课程偏好 (course: course_id) → 有则返回
  4. 检查 全局场景偏好 (global_scene: scene_type) → 有则返回
  5. 检查 全局偏好 (global) → 有则返回
  6. 检查 模板偏好 (template) → 有则返回
  7. 返回 系统默认偏好 (system_default)
```

---

## 7. 项目目录结构

```
personalized-learning-agent/
├── apps/
│   ├── extension/                  # Chrome扩展（Canvas数据提取）
│   │   ├── manifest.json           # Manifest V3
│   │   ├── background/
│   │   │   └── service-worker.js   # 后台同步调度
│   │   ├── content-scripts/
│   │   │   └── canvas.js           # Canvas API数据提取
│   │   ├── popup/
│   │   │   ├── popup.html          # 课程选择/同步控制UI
│   │   │   └── popup.js
│   │   └── utils/
│   │       ├── canvas-api.js       # Canvas REST API封装
│   │       └── canvas-detect.js    # Canvas URL检测
│   │
│   ├── web/                        # Next.js前端
│   │   ├── src/
│   │   │   ├── app/                # App Router pages
│   │   │   │   ├── dashboard/      # 课程列表/仪表盘
│   │   │   │   ├── course/[id]/    # 课程详情/学习视图
│   │   │   │   │   ├── content/    # 课程内容树
│   │   │   │   │   ├── progress/   # 学习进度
│   │   │   │   │   └── review/     # 错题复习
│   │   │   │   ├── chat/           # 学习对话
│   │   │   │   └── settings/       # 用户设置/偏好查看
│   │   │   ├── components/         # UI组件 (shadcn/ui)
│   │   │   │   ├── chat/           # 对话相关组件
│   │   │   │   ├── course/         # 课程相关组件
│   │   │   │   ├── preference/     # 偏好确认弹窗
│   │   │   │   └── ui/             # shadcn基础组件
│   │   │   ├── lib/                # 工具函数
│   │   │   │   ├── api.ts          # API客户端
│   │   │   │   └── utils.ts
│   │   │   └── store/              # Zustand状态管理
│   │   │       ├── course.ts
│   │   │       └── chat.ts
│   │   ├── public/
│   │   ├── package.json
│   │   ├── next.config.js
│   │   ├── tailwind.config.ts
│   │   └── tsconfig.json
│   │
│   └── api/                        # Python FastAPI后端
│       ├── main.py                 # FastAPI入口
│       ├── config.py               # 配置管理（环境变量）
│       ├── routers/                # API路由
│       │   ├── __init__.py
│       │   ├── courses.py          # 课程CRUD
│       │   ├── chat.py             # 对话API (SSE流式)
│       │   ├── preferences.py      # 偏好查看/确认API
│       │   ├── canvas.py           # Canvas集成API
│       │   ├── upload.py           # 文件上传API
│       │   ├── ingestion.py       # 数据获取统一路由（新增：upload/canvas-sync/scrape/refine）
│       │   └── review.py           # 错题复习API
│       ├── services/               # 业务逻辑层
│       │   ├── preference/         # 偏好系统（PDF1核心）
│       │   │   ├── __init__.py
│       │   │   ├── engine.py       # 7层偏好解析引擎
│       │   │   ├── signals.py      # 偏好信号检测（4类信号）
│       │   │   ├── confidence.py   # 置信度计算（公式）
│       │   │   ├── decay.py        # 偏好衰减（90天半衰期）
│       │   │   └── prompt.py       # System Prompt注入模板
│       │   ├── memory/             # 记忆层
│       │   │   ├── __init__.py
│       │   │   ├── encode.py        # 编码阶段：摘要提取+偏好信号提取
│       │   │   ├── consolidate.py  # 巩固阶段：去重+置信度更新+衰减
│       │   │   ├── retrieve.py     # 检索阶段：pgvector向量检索+偏好注入
│       │   │   └── context.py      # 对话上下文管理
│       │   ├── canvas/             # Canvas LMS集成
│       │   │   ├── __init__.py
│       │   │   └── sync.py         # canvasapi封装
│       │   ├── ingestion/           # 数据获取+分类（新增，v2优化版）
│       │   │   ├── __init__.py
│       │   │   ├── pipeline.py     # 7步统一分类流水线
│       │   │   ├── classifier.py   # 多模态LLM分类器（含批量模式）
│       │   │   ├── extractor.py    # 多格式内容提取
│       │   │   ├── dispatcher.py   # 分类后→业务表分发
│       │   │   ├── dedup.py        # SHA-256去重
│       │   │   ├── filename_analyzer.py  # 文件名正则预分析
│       │   │   ├── scraper.py      # 三层抓取: readability→firecrawl→browser-use
│       │   │   └── canvas_sync.py  # Canvas数据接收+分流
│       │   ├── parser/             # 文件解析
│       │   │   ├── __init__.py
│       │   │   ├── pdf.py          # Marker PDF解析
│       │   │   ├── pptx.py         # PPTX解析
│       │   │   └── html.py         # HTML解析
│       │   ├── llm/                # LLM统一接口
│       │   │   ├── __init__.py
│       │   │   ├── router.py       # 多模型路由
│       │   │   └── providers/      # 各模型Provider
│       │   │       ├── claude.py
│       │   │       ├── openai.py
│       │   │       ├── deepseek.py
│       │   │       └── ollama.py
│       │   ├── workflow/           # LangGraph工作流
│       │   │   ├── __init__.py
│       │   │   ├── semester_init.py  # WF-1 学期初始化
│       │   │   ├── weekly_prep.py    # WF-2 每周准备
│       │   │   ├── assignment.py     # WF-3 作业分析
│       │   │   ├── study_session.py  # WF-4 学习Session
│       │   │   ├── review.py         # WF-5 错题复习
│       │   │   └── exam_prep.py      # WF-6 考前规划
│       │   └── review/             # 间隔复习
│       │       ├── __init__.py
│       │       └── fsrs.py         # FSRS算法集成
│       ├── models/                 # SQLAlchemy ORM模型
│       │   ├── __init__.py
│       │   ├── user.py             # users表
│       │   ├── course.py           # courses, semesters表
│       │   ├── preference.py       # user_preferences, preference_signals表
│       │   ├── content.py          # course_content_tree表
│       │   ├── progress.py         # learning_progress表
│       │   ├── assignment.py       # assignments表
│       │   ├── wrong_answer.py     # wrong_answers表
│       │   ├── session.py          # study_sessions表
│       │   └── ingestion.py       # ingestion_jobs表（新增）
│       ├── schemas/                # Pydantic验证模型
│       │   ├── __init__.py
│       │   ├── user.py
│       │   ├── course.py
│       │   ├── preference.py
│       │   └── chat.py
│       ├── alembic/                # 数据库迁移
│       │   ├── env.py
│       │   └── versions/
│       ├── alembic.ini
│       ├── requirements.txt
│       └── Dockerfile
│
├── docker-compose.yml              # PostgreSQL + Redis + API
├── docker-compose.dev.yml          # 开发环境
├── .env.example                    # 环境变量模板
├── Makefile                        # 常用命令
├── LICENSE                         # Apache 2.0 或 MIT
└── README.md                       # 项目文档
```

---

## 8. 分阶段实施计划

### Phase 0: 核心MVP（目标：跑通闭环，自己先用起来）

**一句话目标**：上传 PDF → 三面板出内容 → 偏好被记住 → 自己能用来学习。

**用户故事**：
> 我把教授发的讲义PDF拖进去，又把课程网站的URL贴进去。几秒钟后，Agent自动把所有内容解析好了——讲义变成了清晰的思维导图+重点bullet point（因为它记住了我喜欢这种格式），练习题从PDF里自动拆出来变成一道道交互式题目。我一题一题做，提交后看官方答案和AI的解析。不懂的地方随时问AI，它引用我的课件内容精准回答。我说"把笔记那块换成表格对比"，布局立刻调整。越用它越懂我，下次打开已经按我最舒服的方式准备好了。

#### Phase 0 明确不做什么（砍到 Phase 1+）

| 砍掉的功能 | 推迟到 | 原因 |
|-----------|--------|------|
| Canvas/LMS API 集成 | Phase 1 | 需要 OAuth 回调 + API 鉴权，MVP 手动上传 PDF/URL 足够 |
| ~~多用户认证~~ | 不做 | 本地部署开源，参考 OpenClaw 单用户模式 |
| 7 层偏好 cascade | Phase 1 | MVP 先 3 层（临时→课程→全局→默认），已够用 |
| 完整 7 步分类流水线 | Phase 1 | MVP 只做文件上传+URL 抓取，不做自动分类分发 |
| 行为自动学习完整版（5 维度） | Phase 1 | MVP 只做 Step 3 简化版（默认不提取） |
| FSRS 间隔复习 | Phase 2 | 做题面板先只记录对错，Phase 2 再加间隔重复 |
| 知识图谱可视化 | Phase 3 | 用 content_tree 隐式表达即可 |
| Chrome 扩展 Canvas 提取 | Phase 2 | 需要 Manifest V3 开发 |
| 原文对照视图 / 标注系统 | Phase 1 | 非核心体验 |
| 定时自动抓取 | Phase 1 | 需要 APScheduler 配置 |

---

#### Phase 0-A：最小可运行骨架（Week 1-2）

**目标**：后端能接收 PDF 并建树，前端能显示内容，对话能流式返回。

**后端（Week 1）**
- [ ] Fork openakita，搭建项目结构，添加 FastAPI 路由层
- [ ] Docker Compose 配置（Python 后端 + PostgreSQL + Next.js 前端）
- [ ] PostgreSQL 建 6 张核心表（users, courses, course_content_tree, user_preferences, preference_signals, practice_problems）
- [ ] 文件上传 API：`POST /api/content/upload` → 接收 PDF
- [ ] Marker 集成：PDF → Markdown（`pip install marker-pdf`）
- [ ] PageIndex 集成：`md_to_tree()` → 存入 course_content_tree
- [ ] URL 抓取 API：`POST /api/content/url` → trafilatura 提取正文 → Markdown → 建树
- [ ] 对话 API：`POST /api/chat` → openakita Brain + SSE 流式返回
- [ ] LLM 推理式树搜索：对话时检索课程内容注入 RAG

**前端骨架（Week 2）**
- [ ] Next.js App Router + shadcn/ui + Tailwind 初始化
- [ ] 项目入口页（项目列表 + 创建新项目）
- [ ] 内容上传页（文件拖拽上传 + URL 输入）
- [ ] 解析进度页（SSE 推送 + 进度条）
- [ ] 学习空间骨架：react-resizable-panels 三面板框架
  - shadcn/ui 的 Resizable 组件 + 5 个布局预设（balanced/notesFocused/quizFocused/chatFocused/fullNotes）
  - 实现 `panelGroupRef` imperative API 接入
- [ ] 对话面板：assistant-ui 集成（流式渲染 + auto-scroll）
- [ ] 笔记面板：显示 course_content_tree 内容（Markdown 渲染）

**0-A 验收标准**：curl 上传 PDF → DB 有内容树 → 对话 API 引用课件回答 → UI 能上传并显示三面板骨架

---

#### Phase 0-B：三面板内容生成 + 偏好初始化（Week 3-4）

**目标**：三面板都有内容，偏好系统跑通 Step 1 + Step 2。

**AI 笔记面板（Week 3 前半）**
- [ ] AI 笔记重构：根据偏好将课件内容重组为 bullet/表格/步骤图
- [ ] Mermaid.js 渲染（思维导图/流程图）+ KaTeX 数学公式渲染
- [ ] 章节导航：内容树侧边栏，点击跳转
- [ ] AI 自动可视化：System Prompt 注入可视化工具说明，AI 自动选择

**做题面板（Week 3 后半）**
- [ ] PDF 题目提取：LLM structured output（参考 Obsidian Quiz Generator 的 7 种题型 prompt）
- [ ] 交互式答题 UI：一题一题展示 → 作答 → 提交（参考 Quenti 的 React 组件）
- [ ] 答案 + AI 解析：评判答案 + 引用课件内容生成解析
- [ ] 做题记录存入 practice_results 表

**偏好系统（Week 4 前半）**
- [ ] **Step 1 — Onboarding**：react-step-wizard 5 步流程
  - 笔记格式 / 详细程度 / 语言 / 布局模板 / "我有例子"（可跳过）
  - 结果写入 user_preferences (scope=global, source=onboarding)
- [ ] **Step 2 — 自然语言微调**：用户说"太长了"→ Brain 识别 → 更新偏好 → 确认 toast
  - 注册 NL 微调为 LLM tool call（set_layout_preset / switch_panel_view）
  - 模糊表达时返回选项追问
- [ ] 偏好解析引擎：3 层 cascade（临时→课程→全局→默认），~150 行 Python
- [ ] System Prompt 偏好注入模板

**NL 布局控制（Week 4 后半）**
- [ ] 布局操作注册为 LLM tool（CopilotKit 模式）
- [ ] 用户说"笔记放大" → LLM 返回 `set_layout_preset("notesFocused")` → imperative API 执行
- [ ] 用户说"换成思维导图" → LLM 返回 `switch_panel_view("notes", "mindmap")` → 重渲染

**0-B 验收标准**：上传 PDF → 笔记面板有 AI 重构内容 → 做题面板有提取的题目 → 对话能引用课件 → 说"换成表格"布局/格式立刻变化

---

#### Phase 0-C：偏好闭环 + 自用打磨（Week 5-6）

**目标**：偏好被记住并在下次体现，自己能用来准备下周学习。

**偏好行为学习简化版**
- [ ] **Step 3 简化版** — 适配 openakita Compiler 做偏好信号提取
  - 修改 `EXTRACTION_PROMPT` 为学习偏好维度
  - "默认不提取"策略（~95% 对话返回 NONE）
  - 信号写入 preference_signals 表
- [ ] 置信度计算：`confidence = base × frequency × recency × consistency`
  - base_score: 显式=0.7, 修改=0.5, 行为=0.3
  - recency_factor: `exp(-days/90)`
- [ ] 偏好确认弹窗：学习结束后 shadcn Dialog 展示偏好变化
  - 用户选 "长期习惯" / "这门课" / "不改"
  - 写入 user_preferences

**LangGraph 工作流**
- [ ] WF-4 学习 Session：load_context → search_content → generate_response → extract_signals
- [ ] WF-2 每周准备（简化版）：fetch_assignments → load_preferences → generate_plan

**记忆层**
- [ ] EverMemOS 三阶段记忆流水线：encode（摘要+偏好提取）→ consolidate（去重+置信度）→ retrieve（向量检索+偏好注入）
- [ ] pgvector 向量检索：对话记忆存取
- [ ] 课程内容检索：PageIndex 树形推理搜索（已在 0-A 实现）

**端到端打磨**
- [ ] 空状态 / 加载状态 / 错误状态 UI
- [ ] Toast 通知系统（sonner）
- [ ] 解析进度 SSE 优化
- [ ] 键盘快捷键（Cmd+1/2/3 切换面板）
- [ ] 用自己的真实课程跑一周，修复 bug

**0-C 验收标准**：
- ✅ 端到端闭环：上传 → 三面板 → 偏好初始化 → 学习 → 偏好记住 → 下次体现
- ✅ 说"我喜欢 bullet point" → 下次打开笔记面板自动用 bullet point
- ✅ 自己能用来准备下周学习

---

**Phase 0 总计时间**：6 周

**Phase 0 最终成功标准**：
- ✅ 端到端跑通整个闭环（PDF/URL → 三面板 → 偏好记忆 → 下次体现）
- ✅ 偏好被记住且下次对话/笔记格式体现
- ✅ 自己能用来准备下周学习
- ✅ 有偏好 vs 无偏好的 AI 输出质量有明显差异

---

### Phase 1: 功能补全（目标：完整的日常学习工具）

**新增功能**（含 Phase 0 推迟过来的）：
- [ ] **Canvas API 集成**（用 canvasapi 拉取课程/作业/课件）
- [ ] 完整6个工作流（WF-1学期初始化、WF-3作业分析、WF-5错题标记(不含FSRS)、WF-6考前规划）+ WF-2/WF-4增强
- [ ] 手动文件上传（多格式：PDF/PPTX/HTML/图片）+ **自动分类流水线**（Phase 0 只做上传，现在加分类分发）
- [ ] **偏好系统完整版**：7层cascade解析（Phase 0 只有 3 层）、5个维度、置信度计算、衰减机制
- [ ] **RRF 融合排名**（`score = 1/(60+rank)`，合并 PageIndex+pgvector 结果）
- [ ] **Provider Registry 模式**（参考 nanobot）+ 熔断器容错
- [ ] 学习进度追踪（课程级 → 章节级）
- [ ] 记忆系统增强：评估Graphiti知识图谱记忆（`pip install graphiti-core`）补充 EverMemOS 流水线
- [ ] 主动提醒推送（APScheduler + Web通知）
- [ ] 学习模板系统（5个内置模板，可自然语言修改）
- [ ] 课程内容树形视图
- [ ] README + 部署文档 + 贡献指南

**预计时间**：Phase 0后 4-6周

**成功标准**：
- ✅ 6个工作流全部跑通
- ✅ 偏好确认接受率 > 70%
- ✅ 能覆盖一学期完整学习场景

---

### Phase 2: 产品化（目标：可发布的开源项目）

**新增功能**：
- [ ] FSRS间隔复习 + 闪卡自动生成（参考spaceforge + py-fsrs）
- [ ] 复习提醒推送（FSRS计算 → 定时通知）
- [ ] Onboarding优化（学习模板选择 + 快速画像）
- [ ] Chrome扩展Canvas自动提取（Manifest V3）
- [ ] LLM熔断器增强：渐进冷却（参考openakita）+ LiteLLM集成
- [ ] 混合检索增强（PageIndex树搜索 + pgvector向量 + RRF融合优化）
- [ ] 多语言界面（中/英）
- [ ] 评估memvid/Letta替换/增强记忆系统
- [ ] 代码执行模式（编程课学习）
- [ ] 白板/可视化模式（数学/物理）

**预计时间**：Phase 1后 6-8周

**成功标准**：
- ✅ 开源发布，GitHub README + Docker 一键跑通
- ✅ 间隔复习后记忆保持率提升

---

### Phase 3: 扩展（目标：生态化，类OpenClaw的skills市场）

**新增功能**：
- [ ] 插件/技能市场（用户可创建、分享学习模板）
- [ ] 浏览器自动化（三层降级：httpx → Firecrawl → browser-use）
- [ ] 知识图谱可视化（显式知识点关联）
- [ ] 更多LMS支持（Blackboard、Moodle）
- [ ] 移动端优化（PWA增强）
- [ ] 偏好系统跨领域迁移评估
- [ ] 更多间隔重复模式（音频/视频内容复习）

---

### 功能 → 阶段映射总表

> Phase 0 内部子阶段：0-A = Week 1-2 骨架，0-B = Week 3-4 内容+偏好，0-C = Week 5-6 闭环打磨

| 功能 | Phase 0-A | Phase 0-B | Phase 0-C | Phase 1 | Phase 2 | Phase 3 |
|------|-----------|-----------|-----------|---------|---------|---------|
| **三大核心面板** | | | | | | |
| 📝 AI笔记面板 | 骨架(Markdown渲染) | ✅ AI重构+Mermaid/KaTeX | | 多格式增强 | | |
| ✏️ 做题面板 | | ✅ 题目提取+答题UI | | 增强 | | |
| 💬 AI对话助手 | ✅ 流式对话+RAG | | | 增强 | | |
| **内容输入** | | | | | | |
| PDF解析(Marker→PageIndex) | ✅ | | | 多格式(PPTX/HTML) | | |
| URL抓取(trafilatura) | ✅ | | | | | 三层降级 |
| 文件上传+自动分类流水线 | | | | ✅ | | |
| Canvas API集成 | | | | ✅ | Chrome扩展 | |
| **偏好系统** | | | | | | |
| Step 1: Onboarding选项 | | ✅ | | 优化 | | |
| Step 2: 自然语言微调 | | ✅ | | | | |
| Step 3: 行为自动学习 | | | ✅ 简化版 | 完整版(5维度) | | |
| 偏好 cascade 解析 | | ✅ 3层 | | 7层完整版 | | |
| 偏好确认弹窗 | | | ✅ | 优化 | | |
| System Prompt偏好注入 | | ✅ | | | | |
| **记忆系统** | | | | | | |
| EverMemOS记忆流水线 | | | ✅ | | | |
| pgvector向量检索 | | | ✅ | | 优化 | |
| RRF融合排名 | | | | ✅ | 增强 | |
| Graphiti知识图谱记忆 | | | | 评估 | | |
| **LLM系统** | | | | | | |
| openakita Brain(对话) | ✅ | | | | | |
| openakita Compiler(提取) | | | ✅ | | | |
| LLM统一接口(环境变量切换) | ✅ | | | Provider Registry | | |
| 熔断器容错 | | | | ✅ | 渐进冷却增强 | |
| LiteLLM集成 | | | | ✅ 可选 | | |
| **工作流** | | | | | | |
| WF-4 学习Session | | | ✅ | 优化 | | |
| WF-2 每周准备 | | | ✅ 简化版 | 优化 | | |
| WF-1/3/5/6 | | | | ✅ | | |
| **布局系统** | | | | | | |
| react-resizable-panels三面板 | | ✅ 骨架 | | | | |
| NL→布局控制(CopilotKit模式) | | ✅ | | 增强 | | |
| 布局预设切换 | | ✅ 5个预设 | | 模板系统 | | 市场化 |
| 自动可视化(Mermaid/KaTeX) | | ✅ | | | | |
| 内容树搜索(PageIndex) | ✅ | | | | 混合检索 | |
| **基础设施** | | | | | | |
| Docker Compose | ✅ | | | | | |
| 单用户模式（本地部署） | ✅ | | | | | |
| 学习进度追踪 | | | | ✅ | | |
| 主动提醒(APScheduler) | | | | ✅ | 增强 | |
| FSRS间隔复习 | | | | | ✅ | |
| 闪卡生成 | | | | | ✅ | |
| 多语言 | | | | | ✅ | |
| 浏览器自动化 | | | | | | ✅ |
| 知识图谱可视化 | | | | | | ✅ |
| 技能市场 | | | | | | ✅ |
| 更多LMS | | | | | | ✅ |

---

## 9. 验证标准

### Phase 0 成功标准（自己先用起来）
1. 端到端跑通：PDF/URL → 三面板生成 → 偏好初始化 → 学习 → 偏好记住 → 下次体现
2. 说"我喜欢 bullet point" → 下次打开笔记面板自动用 bullet point
3. 有偏好 vs 无偏好的 AI 输出质量有明显差异
4. 自己能用来准备下周学习（真实课程跑一周）

### Phase 1 成功标准（完整学习工具）
1. 6 个工作流全部跑通
2. 偏好确认接受率 > 70%
3. Canvas 集成能拉取课程数据
4. 能覆盖一学期完整学习场景

### 产品化成功标准（Phase 2+）
1. 间隔复习后记忆保持率提升
2. GitHub 开源发布，Docker 一键跑通

---

## 10. "自建"组件拆解：参考项目 + 难度评估 + 偷懒策略

> 2026-02-26 新增。对原本认为"必须完全自建"的 6 个核心组件逐一分析，找到可参考的成熟模式和开源项目。结论：原本估计 30% 需要完全自建的工作量实际可降到 ~15%。

### 10.1 偏好引擎（7 层 cascade 解析）

**难度：⭐⭐ 中低** — 模式烂大街，只是没人在学习领域用过

多层 cascade 解析是软件工程最经典的模式之一：

| 参考系统 | 层数 | 核心逻辑 |
|---------|------|---------|
| **Git Config** | 5 层 (system→global→local→worktree→CLI) | 后读覆盖前读 |
| **VS Code Settings** | 4 层 (default→user→workspace→folder) | JSON merge，更具体覆盖更通用 |
| **Spring Boot** | **14+ 层** | 有序列表，最后读取的优先 |
| **CSS Cascade** | 3 层 (user-agent→user→author) + `@layer` | origin + specificity + order |
| **Claude Code CLAUDE.md** | 3-4 层 (global→project→local→rules/) | 同上 |
| **npm .npmrc** | 4 层 (builtin→global→user→project) | 同上 |

你的 7 层 = Git Config 模式 + 课程/场景两个额外维度。核心代码就是一个 for 循环查数据库，**~150 行 Python**。

**置信度计算参考**：
- [Wilson Score Interval](https://github.com/msn0/wilson-score-interval) — Reddit 用的排名算法，处理小样本保守估计
- [clux/decay](https://github.com/clux/decay) — npm 包，Wilson Score + Reddit Hot + HN Hot 时间衰减
- [Hu-Koren-Volinsky 2008](http://yifanhu.net/PUB/cf.pdf) — 隐式反馈置信度加权（2017 IEEE 十年最高影响力论文）
- FSRS 的 Retrievability 衰减 — 和你的 90 天半衰期用同一个数学模型 `exp(-t/τ)`

**90 天衰减**就一行代码：`weight = math.exp(-age_days / 90)`

**偷懒策略**：cascade 照抄 Git Config 模式（for 循环+查表）、置信度用 Wilson Score 思路、衰减直接用 FSRS 指数衰减公式。

### 10.2 偏好确认流程

**难度：⭐⭐ 中低** — UX 设计问题 > 技术问题

| 模式 | 代表产品 | 做法 |
|------|---------|------|
| **Accept-or-Ignore** | GitHub Copilot / Gmail Smart Compose | 灰色建议，Tab 接受，继续打字=拒绝，零打扰 |
| **Ask Once** | [Slack](https://slack.design/articles/should-we-make-it-a-preference-on-customization-defaults-and-accessibility/) | 第一次遇到新功能时问一次，之后不问 |
| **Explore-Exploit** | Netflix / Spotify | 不问用户，A/B 测试+观察行为自动调整 |
| **Confidence Threshold** | FSRS | 置信度达标才生效，用户覆盖则降低 |
| **Contextual Bandits** | [Vowpal Wabbit](https://github.com/VowpalWabbit/vowpal_wabbit) | 多臂老虎机探索最优选项 |

你的设计（"任务结束后总结→用户选长期/短期/学科内"）= **Slack "Ask Once" + Confidence Threshold 混合**。

技术实现：openakita Compiler 异步提取信号 → 达到阈值 → shadcn/ui Dialog 弹窗 → 3 个按钮写入 DB。**~150 行前后端代码**。

### 10.3 场景识别

**难度：⭐ 低** — 正则+LLM 兜底，行业标准做法

| 系统 | 做法 |
|------|------|
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | libmagic（规则）→ 文件扩展名 → 用户指定 → LLM 分类 |
| [Apache Tika](https://github.com/apache/tika) | 5 层降级：magic bytes → XML root → 文件名 → content-type → fallback |
| [Orkes Conductor](https://github.com/conductor-oss/conductor) | Switch Task（ECMAScript 正则）→ LLM Text Complete |

你的双层设计（正则关键词→LLM few-shot 分类）完全是标准做法。一个字典 + `re.search` + 小模型兜底，**~30 行**。

### 10.4 统一分类流水线（7 步）

**难度：⭐⭐⭐ 中等** — 每步都有现成库

| 你的步骤 | 可复用方案 | GitHub |
|---------|-----------|--------|
| SHA-256 去重 | Papra 的 hash-during-stream + DB 唯一约束 | [papra-hq/papra](https://github.com/papra-hq/papra) |
| 文件名预分析 | Apache Tika 的 `tika-mimetypes.xml` 分层检测 | [apache/tika](https://github.com/apache/tika) |
| MIME 检测 | `python-magic` / `filetype` / `puremagic` | pip install 即用 |
| 内容提取 | **Unstructured 的 `partition()` 自动路由到正确提取器** | [Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured) |
| LLM 分类 | Docling 双管道(PDF vs markup) | [docling-project/docling](https://github.com/docling-project/docling) |
| 模糊匹配 | `thefuzz` 库 | `pip install thefuzz` |
| hash-based 缓存 | LlamaIndex IngestionPipeline 的 docstore upsert | [run-llama/llama_index](https://github.com/run-llama/llama_index) |

**关键发现**：Unstructured 的 `partition()` 已做了 MIME 检测+内容提取+路由的全部工作，MVP 可直接用 `pip install unstructured` 替代 Step 1-2。

**但 MVP 不需要完整 7 步**。Phase 0 只做文件上传+URL 抓取，不做自动分类分发。完整流水线推到 Phase 1。

### 10.5 三面板交互体验

**难度：⭐⭐⭐ 中等** — 组件全有现成，联动逻辑需要自己写

| 子功能 | 推荐方案 | GitHub |
|--------|---------|--------|
| **可调面板布局** | react-resizable-panels (via shadcn/ui Resizable) | [bvaughn/react-resizable-panels](https://github.com/bvaughn/react-resizable-panels) |
| **NL→布局控制** | CopilotKit 的 `useCopilotAction` 模式 | [CopilotKit/CopilotKit](https://github.com/CopilotKit/CopilotKit) |
| **Agent→UI 协议** | Google A2UI 声明式 JSON | [google/A2UI](https://github.com/google/A2UI) |
| **聊天面板** | assistant-ui（流式+tool-call rendering） | [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) |
| **题目生成 prompt** | Obsidian Quiz Generator（7 种题型、22 语言） | [ECuiDev/obsidian-quiz-generator](https://github.com/ECuiDev/obsidian-quiz-generator) |
| **做题 UI** | Quenti（开源 Quizlet，Next.js+tRPC+Zustand） | [quenti-io/quenti](https://github.com/quenti-io/quenti) |
| **PDF→quiz** | QuizCrafter（FastAPI+React 管道） | [raunakwete43/QuizCrafter](https://github.com/raunakwete43/QuizCrafter) |

**核心架构洞察**：react-resizable-panels 提供 **imperative API**（`panelGroup.setLayout([50, 25, 25])`），把布局操作注册为 LLM tool call，用户说"笔记放大"→ LLM 返回 `set_layout_preset("notesFocused")` → 直接调 imperative API。这是 CopilotKit 叫"Controlled Generative UI"的模式。

```typescript
// 布局预设
const PRESETS = {
  balanced: [33, 34, 33],
  notesFocused: [50, 25, 25],
  quizFocused: [20, 55, 25],
  chatFocused: [20, 20, 60],
};
// LLM tool call → panelGroupRef.current.setLayout(PRESETS[preset])
```

需要自己写的：三面板联动逻辑（选笔记内容→右键提问→chat 面板响应），**~500 行**。

### 10.6 偏好三步走的前端体验

**难度：⭐⭐ 中低** — 标准 wizard 组件

| 子功能 | 推荐方案 | 说明 |
|--------|---------|------|
| Step wizard | [react-step-wizard](https://github.com/jcmcneal/react-step-wizard) | 轻量，`<StepWizard>` 包裹即可 |
| 状态机管理 | [OnboardJS](https://onboardjs.com/) | Headless，复杂条件跳转 |
| 视觉多选网格 | Spotify onboarding 模式 | 卡片网格，最少选 N 个 |
| 布局预览选择 | 3 个可点击缩略图 | shadcn/ui Card |

Step 1（选项）= shadcn/ui 表单 ~50 行。Step 2（NL 微调）= 聊天面板本身，不需额外 UI。Step 3（行为学习）= 纯后端 openakita Compiler。**前端 ~200 行**。

### 10.7 难度总评

| 组件 | 原评估 | 重新评估 | 真实代码量 | 关键偷懒方式 |
|------|--------|---------|-----------|-------------|
| 偏好引擎 7 层 | "必须从头写" | ⭐⭐ 模式成熟 | ~150 行 Python | 照抄 Git Config 模式 |
| 偏好确认流程 | "独创设计" | ⭐⭐ 标准 dialog | ~150 行 | openakita Compiler + shadcn Dialog |
| 场景识别 | "需要定制" | ⭐ 正则+LLM | ~30 行 | Unstructured 降级链思路 |
| 分类流水线 | "从头构建" | ⭐⭐⭐ 每步有库 | ~300 行核心 | Unstructured + LLM structured output |
| 三面板交互 | "没有先例" | ⭐⭐⭐ 联动要写 | ~500 行 | resizable-panels + assistant-ui |
| 偏好三步走 | "产品设计" | ⭐⭐ 标准 wizard | ~200 行 | react-step-wizard + shadcn |

**结论**：原本估计 30% 完全自建 → 实际约 15% 真正从零写。核心创新不在技术难度，在于把这些成熟技术组合到学习场景中的产品设计。

---

> **当前状态**（2026-02-26）：
> 本文档已完成全面整理，定位为**本地开源单用户个性化学习 Agent**。
> 记忆系统采用 EverMemOS 三阶段流水线模式（PostgreSQL+pgvector 实现），偏好系统自建。
> Phase 0 拆为 0-A/0-B/0-C 三个子阶段，明确 MVP 范围与延期功能。
>
> 下一步：确认计划无误后，开始 Phase 0-A 的实施。
