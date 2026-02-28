## OpenTutor v3 代码实现审计（纯代码分析）

> 本文档完全基于源代码审查，不参考任何需求文档或架构设计文档。目的是如实记录**代码实际做了什么**，**哪些功能是空壳或未完成**，**存在哪些 Bug**，以及**优化空间**。

基于纯代码分析，整个项目可以分为 **9 个大类**：

| # | 大类 | 核心代码位置 |
|---|------|------------|
| **1** | **内容摄入与解析系统** | `services/ingestion/`, `services/browser/`, `routers/upload.py` |
| **2** | **多 Agent 编排架构** | `services/agent/`（orchestrator, base, router, 10 个专职 Agent） |
| **3** | **RAG 混合检索系统** | `services/search/hybrid.py`, `services/search/rag_fusion.py`, `services/embedding/` |
| **4** | **学习场景系统** | `services/scene/`, `models/scene.py`, `routers/scenes.py` |
| **5** | **记忆系统** | `services/memory/pipeline.py`, `services/agent/memory_agent.py` |
| **6** | **个性化偏好引擎** | `services/preference/`（engine, extractor, confidence, scene, prompt） |
| **7** | **练习与间隔重复** | `services/spaced_repetition/`, `routers/quiz.py`, `routers/flashcards.py`, `routers/wrong_answers.py` |
| **8** | **工作流与调度** | `services/workflow/`（6 个工作流）, `services/scheduler/engine.py` |
| **9** | **前端工作台** | `apps/web/src/` 整个 Next.js 应用 + `services/llm/router.py` |

---

## 第一大类：内容摄入与解析系统

### 代码实际做了什么

这套系统把用户上传的文件（PDF、PPTX、DOCX、HTML、纯文本）或 URL 转换为系统内部的内容树。整条管道在 `services/ingestion/pipeline.py` 中实现，共 7 步：

**Step 0 去重**：对上传文件计算 xxhash（`xxh64`），在 `IngestionJob` 表中查询是否已处理过相同哈希。如果 xxhash 库未安装，退回到 SHA-256。重复文件直接返回历史结果。

**Step 1 MIME 检测**：三层策略——先用 `filetype` 库检查文件头字节，再用 `python-magic`，最后用 `mimetypes` 根据扩展名猜测。决定走哪个提取器。

**Step 2 内容提取**：`document_loader.py` 实现了一个统一文档加载器。对于 URL，采用 4 层降级瀑布：Crawl4AI（主引擎，支持 BM25 内容过滤和批量并行爬取 `arun_many()`）→ httpx + BeautifulSoup 清洗 → trafilatura 正文提取 → Playwright 完整浏览器渲染。对于 Office 文件，使用 python-docx / python-pptx / openpyxl 作为 fallback 链。

**Step 3 智能分类**：三层策略——文件名正则匹配（6 种类别：lecture/slides、homework/hw、exam/test、syllabus、textbook/chapter、notes）→ 内容启发式（扫描前 3000 字符的关键词频率）→ LLM 兜底（只处理前 2000 个 token，用 `content_trimmer.py` 的 tiktoken 感知裁剪）。

**Step 4 课程模糊匹配**：用 `thefuzz` 库做文件名与课程名的模糊匹配（阈值 70 分）。只有一门课时直接关联。

**Step 5-6 持久化与分发**：课件/教材/笔记类 → 构建内容树（`CourseContentTree`），按 Markdown 标题层级（`#` `##` `###`）用栈式扫描拆分成父子节点。作业/考试类 → 写入 `Assignment` 表。写入后立即调用 `index_content_nodes()` 构建 PostgreSQL `TSVECTOR` 全文搜索索引。

此外还有一个 **3 层浏览器级联系统**（`browser/automation.py`）：httpx → Scrapling → Playwright，按顺序尝试，成功即停。

### 未实现 / 问题

1. **内容树构建后不生成向量 embedding**：`_dispatch_content()` 完成后，`upload.py` 调用 `_background_embed()` 异步生成 embedding。但如果没有配置 `OPENAI_API_KEY` 且未安装 `sentence-transformers`，embedding 生成静默失败（只打印 debug 日志），所有内容节点的 `embedding` 列为 NULL。后续向量搜索完全失效，降级为纯关键词搜索，但**没有任何用户可见的提示**。

2. **Scrapling 层在 async 函数中同步阻塞**（`automation.py:42`）：`StealthyFetcher().fetch(url)` 是同步阻塞调用，直接在 `async def fetch_with_scrapling()` 中执行，没有用 `asyncio.run_in_executor()` 包装。这会阻塞整个 FastAPI 事件循环 10-30 秒，导致同时段所有其他请求被饿死。

3. **`GET /api/content/jobs/{course_id}` 无鉴权**：这个端点没有 `Depends(get_current_user)`，任何人可以通过猜测课程 UUID 查询任意课程的处理任务状态。

### 优化空间

- 内容启发式分类（`content_heuristics`）目前只有 5 条模式规则，覆盖面有限。可根据实际数据增加规则来进一步减少 LLM 调用率。
- 内容树构建后应立即触发异步批量 embedding 生成，并在没有 embedding provider 时给出明确警告。

---

## 第二大类：多 Agent 编排架构

### 代码实际做了什么

v3 的核心变更：用 `services/agent/orchestrator.py` 中的多 Agent 编排取代了原来单一的 chat 处理函数。`routers/chat.py` 现在是一个薄壳，只做 SSE 包装后调用 `orchestrate_stream()`。

**Agent 注册表**：10 个专职 Agent 作为单例注册在 `AGENT_REGISTRY` 字典中，通过 `INTENT_AGENT_MAP` 把 11 种意图映射到具体 Agent：

| 意图 | Agent | 文件 |
|------|-------|------|
| LEARN / GENERAL | TeachingAgent | `teaching.py` |
| QUIZ | ExerciseAgent | `exercise.py` |
| PLAN | PlanningAgent | `planning.py` |
| REVIEW | ReviewAgent | `review.py` |
| PREFERENCE / LAYOUT | PreferenceAgent | `preference_agent.py` |
| SCENE_SWITCH | SceneAgent | `scene_agent.py` |
| CODE | CodeExecutionAgent | `code_execution.py` |
| CURRICULUM | CurriculumAgent | `curriculum.py` |
| ASSESS | AssessmentAgent | `assessment.py` |
| （疲劳拦截） | MotivationAgent | `motivation.py` |

**BaseAgent 基类**（`base.py`）：定义了 `name`、`profile`（角色描述）、`model_preference`（模型大小偏好）。核心方法：
- `execute()` — 抽象方法，子类实现具体逻辑
- `stream()` — 默认先 `run()` 再一次性 yield；大多数 Agent 重写了此方法实现真正的逐 token 流式输出
- `build_system_prompt()` — 模板方法：拼接 profile + 场景行为规则 + 用户偏好 + 记忆 + RAG 内容

**7 步编排流水线**（`orchestrate_stream()`）：

1. **创建 AgentContext**：承载所有共享状态的 dataclass（`state.py`），包含用户身份、消息、意图、偏好、记忆、RAG 内容、执行阶段等。保留最近 10 轮对话历史。
2. **两阶段意图分类**（`router.py`）：先用 9 组正则规则匹配（从高优先级到低：LAYOUT 0.95 → SCENE_SWITCH 0.90 → PREFERENCE 0.90 → QUIZ 0.90 → PLAN 0.90 → CODE 0.90 → REVIEW 0.85 → CURRICULUM 0.85 → ASSESS 0.85）。全部未命中时调用 LLM 分类（截断消息到 300 字符，输出 JSON `{intent, confidence}`），解析失败默认 GENERAL/0.3。
3. **并行上下文加载**（`load_context()`）：用 `asyncio.gather()` 同时执行偏好解析、记忆检索、RAG 搜索（LEARN/REVIEW 用 RAG Fusion，其他用普通 hybrid search）。任何一个失败不影响其他。
4. **Token 预算裁剪**（`_trim_context()`）：三路限额——对话历史 2000 token、RAG 内容 3000 token、记忆 1500 token。超出时按优先级丢弃（历史从最老的丢，RAG 和记忆从尾部丢）。Token 估算用 ASCII÷4、CJK÷2 的启发式。
5. **Agent 路由**（含疲劳拦截）：`_detect_fatigue()` 用 3 组中英文正则检测挫败信号（"不想学"、"太难"、"看不懂"等），每命中一组加 0.3 分。超过 0.6 时路由到 MotivationAgent 而非常规 Agent。
6. **流式响应 + ACTION 标记解析**：逐 chunk 读取 Agent 流式输出，实时检测 `[ACTION:type:value:extra]` 标记，拆分为 `message` 和 `action` 两种 SSE 事件。
7. **Reflection 自检**（可选）：仅当意图为 LEARN/REVIEW 且响应超过 100 字符时触发。调用 `reflect_and_improve()` 做两步 LLM 调用（Critique → Improve），score < 7 时重写响应并发送 `replace` SSE 事件。
8. **后台后处理**：`asyncio.create_task()` 启动 3 个并行任务——偏好信号提取、记忆编码、知识图谱实体提取。用指数退避重试（1s→2s→4s）。任务引用保存在 `_background_tasks` 集合中防止 GC。

每个 Agent 的 `stream()` 方法在流结束时都会设置 `ctx.response = full_response`（已在 `teaching.py:63`、`exercise.py:93`、`planning.py:70`、`code_execution.py:200` 中确认），确保后处理能拿到完整响应。

**AgentContext 状态机**（`state.py`）：12 个阶段（IDLE → ROUTING → LOADING_CONTEXT → REASONING → ACTING → OBSERVING → VERIFYING → STREAMING → POST_PROCESSING → COMPLETED → FAILED → CANCELLED）。每次 `transition()` 都记录时间戳到 `phase_history`，支持精确性能计时。

### 未实现 / 问题

1. **代码沙箱超时未执行**（`code_execution.py:62`）：`MAX_EXECUTION_TIME = 5` 声明了 5 秒超时，但代码中**没有任何地方使用这个值**。`_execute_safe()` 直接调用 `exec(code, safe_globals)` 无超时包装。恶意或错误的无限循环（只要绕过 `while True` 检查，如 `while 1>0:`）会永远挂住服务进程。

2. **代码沙箱无进程隔离**（`code_execution.py:123`）：使用 `exec()` 配合受限 `__builtins__`，但没有进程级隔离。可通过 `().__class__.__bases__[0].__subclasses__()` 等 Python 内省技巧逃逸受限环境。

3. **`_execute_safe()` 是同步函数**（`code_execution.py:96`）：在 `async def stream()` 中直接调用，没有 `run_in_executor()`。执行学生代码期间阻塞事件循环。

4. **疲劳检测阈值硬编码且触发率低**：需要 3 组正则中命中 2 组以上（每组 0.3，总分 > 0.6）才触发。单独说"我好累"只匹配 1 组（0.3 分），不会触发动机 Agent。

5. **Reflection 额外消耗 1-2 次 LLM 调用**：没有用户级或课程级开关来关闭。每次 LEARN/REVIEW 长回复都会触发，对 API 用量敏感的场景可能需要可配置。

### 优化空间

- 历史对话只保留最后 10 轮后硬裁剪，可考虑引入 sliding window summarization 保留更长历史的语义压缩摘要。
- LEARN 意图的正则规则较宽泛（`what|how|why|explain|tell me|teach|define|describe` 等），与 GENERAL 边界模糊。可考虑正则置信度加权或多规则联合。

---

## 第三大类：RAG 混合检索系统

### 代码实际做了什么

从课程内容库中检索最相关的段落作为 AI 回答的事实依据。核心在 `services/search/hybrid.py`。

**三路搜索引擎**：

1. **BM25 全文搜索**：使用 PostgreSQL 的 `ts_rank_cd` + `plainto_tsquery('simple', query)` 对 `CourseContentTree.search_vector`（TSVECTOR 列）做全文排名。如果 TSVECTOR 不可用，退回到 `ILIKE` 多关键词匹配 + 层级权重提升（`level_boost = max(0.5, 1.0 - level * 0.1)`，即章节比小节更重要）。

2. **PageIndex 树搜索**：从 `level<=1` 的章节开始，用关键词粗筛相关章节（fallback 到前 3 章），再下钻到子节点逐个评分。模拟"先看目录再翻到相关章节"的查找策略。

3. **向量搜索**：用 pgvector 的余弦距离（`embedding <=> query_embedding`）在 `CourseContentTree.embedding` 上做最近邻搜索。如果内容节点没有 embedding（常见，见第一大类问题 1），则 fallback 到 `ConversationMemory.embedding` 搜索历史对话记忆。

三路结果用 RRF（Reciprocal Rank Fusion）算法融合：`score = Σ 1/(60 + rank_i)`，k=60 是文献标准值。同一文档在多路出现则分数累加，最终按总分降序取前 5 条。

**RAG Fusion**（`rag_fusion.py`）：仅当意图为 LEARN 或 REVIEW 时启用。3 步流程：LLM 生成 3 个查询变体（不同角度/关键词）→ 每个变体执行 `hybrid_search()` → 对全部结果做 RRF 二次融合。

### 未实现 / 问题

1. **三路搜索是串行执行的**：`hybrid.py` 中 `kw_results = await keyword_search()`、`tree_results = await tree_search()`、`vec_results = await vector_search()` 依次 await，没有用 `asyncio.gather()` 并行。理论上可降低约 60% 的检索延迟。

2. **RAG Fusion 静默降级**：当 MockLLMClient 激活或 LLM 报错时，`generate_query_variants()` 返回空列表，RAG Fusion 静默退化为普通单查询搜索。失败只打印 `logger.debug`，生产环境不可见。

3. **向量搜索在冷启动时完全失效**：如果没有 embedding provider，所有内容节点 embedding 为 NULL，向量搜索返回空。三路搜索实际退化为两路（关键词 + 树搜索），检索质量下降但没有任何警告。

### 优化空间

- `hybrid_search()` 中三路搜索改为 `asyncio.gather()` 并行执行。
- RAG Fusion 的 3 个查询变体生成也是串行的，可以并行化。
- 内容索引器应在 ingestion 完成时同步生成 embedding，而不是依赖后台异步任务。

---

## 第四大类：学习场景系统

### 代码实际做了什么

"场景"把学习模式（日常学习、考前冲刺、写作业、错题专练、笔记整理）与 UI 布局、AI 行为、偏好覆盖绑定在一起。

**5 个预设场景**（`scene/seed.py` 在启动时写入数据库）：

| 场景 ID | 名称 | 工作流 | AI 行为风格 |
|---------|------|--------|------------|
| `study_session` | 日常学习 | study | 深入探索、鼓励提问 |
| `exam_prep` | 考前准备 | exam | 简洁重点、薄弱点优先、高频出题 |
| `assignment` | 写作业 | assignment | 引导式、不给直接答案、渐进提示 |
| `review_drill` | 错题专练 | review | 分析错因、归类错误、生成同类题 |
| `note_organize` | 笔记整理 | notes | 结构化、跨章节关联 |

每个场景定义了 `tab_preset`（默认开启哪些 tab 及顺序）、`ai_behavior`（JSON 行为规则）、`preferences`（偏好覆盖值）。

**6 步场景切换**（`scene/manager.py` 的 `switch_scene()`）：
1. 把当前场景的 UI 状态快照（open_tabs + layout_state + scroll_positions）写入 `scene_snapshots` 表（upsert）
2. 从数据库加载目标场景配置（数据库优先，无则走硬编码 `SCENE_DEFAULTS`）
3. 尝试从 `scene_snapshots` 恢复历史 tab 布局，无历史则用场景 `tab_preset` 默认值
4. 更新 `courses.active_scene` 字段
5. 生成首次进入初始化动作（exam_prep → 生成复习计划提示；review_drill → 自动加载未掌握错题）
6. 写入 `scene_switch_log`（记录 from_scene、to_scene、trigger_type）

**AI 行为注入**（`scene_behavior.py`）：每个场景有独立的行为指令字符串，通过 `BaseAgent.build_system_prompt()` 注入到所有 Agent 的 system prompt 中。例如 assignment 场景注入"不给直接答案，用渐进式提示"。

**场景感知工具加载**（`tool_loader.py`）：按场景只加载必要的工具定义（core + layout + 按需加载 quiz/plan/review），节省约 30% system prompt token。

**触发方式**：手动（用户点击下拉框）、AI 建议（SceneAgent 发出 `[ACTION:suggest_scene_switch:scene_id]`）、自动（预留接口，未实现）。

### 未实现 / 问题

1. **3 张新数据表均已创建**（scenes、scene_snapshots、scene_switch_log），6 步切换流程完整实现，**这是 v3 中完成度最高的新系统**。

2. **自定义场景创建端点**（`POST /api/scenes/custom`）：代码存在但没有前端入口，用户无法从界面创建自定义场景。

3. **`auto` 触发方式未实现**：`trigger_type` 支持 `"auto"` 值，但没有任何代码会以这种方式触发场景切换。

### 优化空间

- 场景行为指令目前是硬编码在 Python 字符串中的，无法通过数据库或配置文件修改。可迁移到数据库的 `ai_behavior` JSON 字段中（字段已存在但实际读取时优先使用硬编码值）。

---

## 第五大类：记忆系统

### 代码实际做了什么

模仿人类"编码→巩固→检索"的记忆机制，核心在 `services/memory/pipeline.py`（18.9KB）。

**Stage 1 编码（`encode_memory()`）**：每轮对话后触发。使用 LLM 从对话中提取 0-3 个原子 MemCell，每个带类型标签（7 种：episode=学习里程碑、profile=学习者身份、preference=偏好、knowledge=知识掌握、error=错误模式、skill=技能、fact=原子事实）。采用"默认不提取"策略——约 95% 的对话 LLM 返回 "NONE"，只有涉及学习者身份、偏好、知识盲区等长期有价值的信息才被提取。JSON 解析失败时退回到旧版单条摘要编码。每个 MemCell 写入后立即更新 `search_vector = to_tsvector('simple', summary)`。

**Stage 2 巩固（`consolidate_memories()`）**：两阶段去重——词重叠预筛（阈值 0.5，仅同类型比较）→ 向量余弦相似度确认（阈值 0.85），无 embedding 时 fallback 到词重叠阈值 0.7。然后施加类型感知衰减：不同类型有不同半衰期（profile=365天、episode=180天、skill=120天、preference=120天、knowledge=90天、error=60天、conversation=60天），用指数衰减公式 `importance *= exp(-days/half_life)`。重要性低于 0.1 的记忆直接删除。

**Stage 3 检索（`retrieve_memories()`）**：并行 BM25 + 向量搜索，权重 0.7 向量 + 0.3 BM25，再做 RRF 融合。最低分过滤 0.35。每次检索自动递增 `access_count`。

### 未实现 / 问题

1. **巩固仅靠定时任务**：`consolidate_memories()` 不在 `encode_memory()` 后立即触发，完全依赖每 6 小时的 `memory_consolidation_job`。新编码的重复记忆在巩固前最多累积 6 小时。

2. **去重是 O(n²) 复杂度**：`_find_duplicates()` 对同类型记忆做两两比较。对记忆量大的用户（>500 条），每次巩固可能很慢。

3. **`categorize_uncategorized()` 也在 memory_agent.py 中**：LLM 为无分类记忆分配主题标签（如 "Linear Algebra / Eigenvalues"）。但该功能在后台静默运行，用户界面没有任何地方展示记忆分类。

### 优化空间

- 去重可按 `memory_type` 分桶后并行处理，降低时间复杂度。
- 可在 encode 后判断同类型记忆数量，达到阈值（如 10 条新增）立即触发一次局部巩固。
- 记忆分类结果目前无前端展示入口，可考虑在学习进度面板中展示。

---

## 第六大类：个性化偏好引擎

### 代码实际做了什么

自动感知并管理用户学习偏好。核心在 `services/preference/` 目录。

**七层偏好级联解析**（`engine.py` 的 `resolve_preferences()`）：借鉴 Git Config 的就近覆盖思想，从低优先级到高优先级逐层叠加（后者覆盖前者）：

1. **system_default**（最低）：每个维度内置默认值（笔记格式=bullet_point、详细程度=balanced、语言=english、解释风格=mixed、视觉偏好=auto）
2. **template**：5 套内置学习模板各自预设一组偏好值
3. **global**：用户在设置中明确选择的全局偏好
4. **global_scene**（v3 新增）：按当前学习场景自动调整的全局偏好。只有 `pref.scene_type == scene` 时才生效
5. **course**：针对某门课程的偏好
6. **course_scene**（v3 新增）：某课程的某场景下的偏好。同样需要 scene_type 匹配
7. **temporary**（最高）：对话中即时调整的偏好

解析时一次性从数据库加载该用户所有偏好记录，按 scope 分组后逐层覆盖。

**偏好信号提取**（`extractor.py`）：每轮对话后台 LLM 调用，分析消息中是否隐含偏好信号。4 种类型：显式（"我喜欢表格"）、修改（"换成要点"）、行为（反复追问细节 → 偏好详细）、否定（"别用图表"）。约 95% 返回 "NONE"。

**置信度计算与信号晋升**（`confidence.py`）：公式 `confidence = 基础分 × 频率因子 × 时效因子 × 一致性因子`。基础分按类型：显式 0.7、修改 0.5、否定 0.6、行为 0.3。频率因子 = count/5（封顶 1.0）。时效因子 = exp(-days/90)。一致性因子 = 指向同一值的信号比例。置信度超过 0.4 阈值时，信号晋升为正式 `UserPreference` 记录。

**场景检测**（`scene.py` 的 `detect_scene()`）：用正则匹配消息内容推断当前学习场景。注意这里检测的是**语义场景**（用于偏好 cascade 的 scene_type 匹配），与第四大类的 5 个预设场景有区别——前者是消息级的模糊推断，后者是用户/AI 主动切换的持久状态。

### 未实现 / 问题

1. **temporary 级偏好没有持久化机制**：每次新对话开始，之前对话中的临时偏好丢失。没有"高置信度临时信号自动晋升为 course 级"的逻辑。

2. **偏好注入格式**：`build_system_prompt()` 中把偏好字典格式化为 `- dimension: value` 行直接注入 system prompt，没有做自然语言转换。LLM 需要自己理解 `"note_format: table"` 意味着什么。

### 优化空间

- 五个维度（note_format、detail_level、language、explanation_style、visual_preference）目前是硬编码的。增加新维度需要改代码，可考虑数据驱动的维度定义。

---

## 第七大类：练习与间隔重复

### 代码实际做了什么

**AI 题目生成**（`services/parser/quiz.py` + `routers/quiz.py`）：把内容树节点的标题和正文交给 LLM，输出结构化 JSON 数组，支持 4 种题型（选择题 mc、判断题 tf、简答题 short_answer、填空题 fill_blank）。每道题存入 `PracticeProblem` 表。v3 新增 `knowledge_points` 字段（该题考察的知识点标签列表）和 `source` 字段。ExerciseAgent 额外注入了 VCE 三层难度分级指令（Layer 1 基础 / Layer 2 应用 / Layer 3 进阶），要求每题附带 JSON 元数据（`difficulty_layer`、`core_concept`、`bloom_level`、`potential_traps`）。

**答题交互**：用户提交答案后做字符串匹配判分，结果记录到 `PracticeResult` 表。

**错题系统**（`routers/wrong_answers.py`，v3 新增）：
- `GET /wrong-answers/{courseId}` — 列出未掌握的错题（`mastered=False`），可按 `error_category` 过滤
- `POST /wrong-answers/{id}/retry` — 重试答题，答对标记 `mastered=True`
- `POST /wrong-answers/{id}/derive` — 基于错题的知识点和错误模式，LLM 生成同类衍生题，保存为新 `PracticeProblem`

错题模型新增 `error_category`（5 种：conceptual/procedural/computational/reading/careless）和 `knowledge_points`（JSONB 列表）。

**闪卡与 FSRS**（`services/spaced_repetition/fsrs.py`）：完整实现 FSRS-4.5 算法（17 个参数 w0-w16）。核心函数：`_initial_stability()`（首次评分 → 初始稳定性）、`_difficulty_update()`、`_stability_recall()`（回忆成功时稳定性提升）、`_stability_forget()`（遗忘时稳定性重置）、`_retrievability()`（当前可回忆概率）。调度间隔 = `max(1, round(stability))` 天。评分 Again 会重置稳定性并设定明天复习。

**笔记重构**（`services/parser/notes.py`）：5 种格式——要点（bullet_point）、表格（table）、思维导图（mind_map → Mermaid 语法）、步骤流程（step_by_step）、总结（summary）。视觉偏好为 "auto" 时 AI 自动选择格式。

### 未实现 / 问题

1. **代码沙箱超时完全未执行**（已在第二大类详述）。

2. **`POST /wrong-answers/mark` 缺少鉴权**：没有 `get_current_user` 依赖，任何人可以标记任何错题为已复习。

3. **ExerciseAgent 的 VCE 三层元数据注入**：虽然 system prompt 要求 LLM 输出 JSON 元数据块，但代码中**没有解析这些元数据**——Agent 只是把 LLM 的完整响应作为流式文本输出到前端。`difficulty_layer`、`bloom_level` 等数据不会被存入 `PracticeProblem` 表，也不会被后续流程消费。

### 优化空间

- VCE 三层元数据应在 Agent 输出后解析并存入数据库，供 ReviewAgent 和 AssessmentAgent 使用。
- 闪卡生成时不自动获取已有闪卡，前端每次进入闪卡面板都需要手动点击"Generate Flashcards"。

---

## 第八大类：工作流与调度

### 代码实际做了什么

**6 个 LangGraph 工作流**（`services/workflow/` 目录）：

| 工作流 | 文件 | 触发方式 | 功能 |
|--------|------|---------|------|
| WF-1 学期初始化 | `semester_init.py` | 手动 API | 批量创建课程 → 按类型设初始偏好 → LLM 生成学期计划 |
| WF-2 每周准备 | `weekly_prep.py` | 每周一 8AM 定时 | 加载 14 天内截止日期 → 统计过去 7 天学习数据 → LLM 生成周计划 |
| WF-3 考前准备 | `exam_prep.py` | 手动 API | 提取章节 → 统计学习数据 → 生成分天复习计划 |
| WF-4 学习会话（图版） | `graph.py` | **无调用方** | LangGraph StateGraph，编译正常但不被任何 router 调用 |
| WF-4 学习会话（实际） | `orchestrator.py` | `POST /api/chat/` | 多 Agent 编排流水线（取代 LangGraph 版本） |
| WF-5 错题复习 | `wrong_answer_review.py` | 手动 API | 加载未掌握错题 → 混合搜索相关材料 → LLM 生成复习内容 |

**4 个 APScheduler 定时任务**（`scheduler/engine.py`）：
1. `weekly_prep_job` — 每周一 8:00 AM，为所有用户运行 WF-2
2. `fsrs_review_job` — 每小时，检查到期闪卡推送复习提醒
3. `scrape_refresh_job` — 每小时，重新抓取自动更新 URL（每个源控制自己的间隔）
4. `memory_consolidation_job` — 每 6 小时，运行记忆去重 + 衰减 + 分类

**通知系统**：调度任务通过 `_push_notification()` 推送到一个 Python 内存列表（`_notifications: list[dict]`），最多保留 200 条，通过 `/api/notifications` API 轮询获取。

**学习进度追踪**（`services/progress/tracker.py`）：以"课程→章节→知识点"三级粒度追踪。掌握度 = 测验正确率 × 0.7 + 学习时长因子 × 0.3（60 分钟封顶 1.0）。掌握度 ≥ 0.8 且测验 ≥ 3 次时状态晋升为"已掌握"。

### 未实现 / 问题

1. **WF-4 LangGraph 版本是死代码**（`workflow/graph.py`）：`run_study_session_graph()` 函数完整实现且编译通过，但**没有任何 router 调用它**。实际聊天流程走的是 `orchestrate_stream()`。这个文件有 23.1KB 的代码是死代码。

2. **`fsrs_review_job` 有字段名 Bug**（`scheduler/engine.py:105`）：代码引用 `LearningProgress.mastery_level`，但 `models/progress.py:37` 中的实际字段名是 `mastery_score`。这会导致 **`fsrs_review_job` 每小时崩溃**一次，抛出 `AttributeError`，但错误被 `try/except` 吞掉，只打印日志。FSRS 复习提醒功能**实际上从未正常工作过**。

3. **通知不持久化**：`_notifications` 是一个内存列表，服务重启后所有通知丢失。文件顶部注释说"notifications are stored in a `notifications` table"，但**根本不存在这张表**。也没有对应的 ORM 模型。注释与代码不一致。

4. **通知无鉴权**：`GET /api/notifications/` 接受 `user_id` 作为查询参数，没有 `get_current_user` 依赖。任何人可以传入任意 `user_id` 读取别人的通知。

5. **`weekly_prep_job` 遍历所有用户**：无论用户是否活跃，每周一都为所有用户生成周计划并调用 LLM。用户量增长后 API 调用开销线性增长。

### 优化空间

- 要么删除 `workflow/graph.py` 中的死代码 WF-4 LangGraph 版本，要么将它作为批处理/非流式场景的入口点（如考前复习整体规划）。
- 修复 `mastery_level` → `mastery_score` 的字段名 bug。
- 通知系统应迁移到数据库表。

---

## 第九大类：前端工作台与 LLM 路由

### LLM Provider Registry

`services/llm/router.py` 实现了一套多提供商 LLM 路由层。

**Provider Registry 模式**：启动时根据环境变量注册所有有 API Key 的提供商（OpenAI / Anthropic / DeepSeek / Ollama）。`get_llm_client()` 遍历注册列表，找到第一个健康的提供商返回。

**断路器模式**：每个提供商维护健康状态。失败触发渐进式冷却（5s→10s→20s→60s），连续失败 3 次则"断路"（120 秒内不尝试）。成功后立即重置。

**MockLLMClient 兜底**：所有 API Key 都没配时，启用 MockLLMClient。`stream_chat()` 返回固定提示文字；`extract()` 永远返回 `"NONE"`。**后果是所有后台 AI 功能静默失效**：记忆编码始终提取 0 条 MemCell、偏好信号始终为空、RAG Fusion 查询变体始终为空、图谱实体提取始终为空。系统表面正常运行但做不了任何智能事情，且**没有任何用户可见的警告**。

**Token 追踪**：`chat()` 和 `extract()` 返回 `(content, usage_dict)`。流式场景在流结束后从 `_last_usage` 取出。Orchestrator 把 token 数写入 `ctx.input_tokens / output_tokens`。

### 前端总览

基于 Next.js 16 + React 19 + Tailwind CSS v4 + shadcn/ui（New York 风格）+ Zustand 5 构建。3 个 Zustand Store：`course`（课程列表和内容树）、`chat`（对话历史和流式状态）、`scene`（场景列表和切换状态）。

**四面板可调布局**（`app/course/[id]/page.tsx`）：用 `react-resizable-panels` 实现 4 个可拖拽面板——PDF 查看器、笔记面板、练习面板（多 Tab：Quiz/Cards/Stats/Graph）、聊天面板。5 种预设布局（balanced/notesFocused/quizFocused/chatFocused/fullNotes），通过 Cmd/Ctrl+1/2/3/0 快捷键或活动栏图标切换。面板可关闭，底部显示恢复条。

**SSE 流式聊天**：`store/chat.ts` 中 `sendMessage()` 调用 `streamChat()`，手动解析 `ReadableStream` 的 SSE 事件。支持 `content`（逐字追加到 AI 消息）和 `action`（调用 `onAction` 回调执行布局变更/偏好更新/场景切换建议）两种事件。

**Markdown 渲染器**（`markdown-renderer.tsx`）：支持 KaTeX 数学公式（`$...$` 和 `$$...$$`）、Mermaid 图表（动态 import）、表格和代码块。

**i18n 模块**（`lib/i18n.ts`）：6 种语言（en/zh/ja/ko/es/fr）的完整翻译键值对。

### 未实现 / 空壳功能

**1. PDF 查看器是纯占位符**（`pdf-viewer.tsx`）：组件只显示静态文字"Upload a PDF to view its contents here"。没有 PDF.js 集成、没有 `<iframe>`、没有任何渲染逻辑。在课程页面中调用时甚至**没有传入任何 props**（`<PdfViewer />`，第 195 行），意味着它永远显示"No document loaded"空状态。**这是前端最大的空壳**。

**2. i18n 翻译完整但从未使用**：6 种语言约 50 个键值对的翻译全部写好了，但 `t()` 函数在**整个前端代码中零次调用**。所有组件都使用硬编码英文字符串。例如 `quiz-panel.tsx` 写的是 `"No quiz questions yet"` 而不是 `t("quiz.empty")`。`initLocale()` 有浏览器语言自动检测但从未在任何组件中调用。设置页面改语言只改 localStorage，不会触发重渲染。**整个 i18n 系统是完整的死代码**。

**3. 暗色模式未启用**：`next-themes` 已安装（`package.json`），很多组件使用了 `dark:` Tailwind 类（如 `progress-panel.tsx`、`quiz-panel.tsx`），但 `layout.tsx` 中**没有 `ThemeProvider` 包装**。`<html>` 标签没有 `suppressHydrationWarning`，没有 class 绑定。`dark:` 类永远不会激活。**暗色模式代码存在但永久失效**。

**4. `PreferenceConfirmDialog` 已实现但从未渲染**：对话结束后检测到偏好变化时应弹出的确认对话框（`preference-confirm-dialog.tsx`），提供"设为长期习惯"/"仅限本课程"/"不改变"三个选项，代码完整。但**在整个 `src/` 目录中没有任何组件 import 或渲染它**。

**5. `BreadcrumbsBar` 组件是死代码**：`workspace/breadcrumbs.tsx` 中实现了完整的面包屑导航组件。但课程页面使用**内联代码**直接渲染面包屑（`page.tsx` 第 151-165 行），从未 import 这个组件。

**6. 新建项目页多处状态收集后丢弃**（`app/new/page.tsx`）：
- `features` 状态（Quiz、Cards 等功能选择复选框）：toggles 正常工作但**选中结果从未提交到任何 API**
- `nlInput`（底部自然语言输入框）：有 state 绑定但**从未提交**
- `autoScrape`（自动抓取开关）和频率下拉框：有视觉状态但**值从未发送到后端**
- "Copy Settings from Existing Project" 下拉框：**没有 value、没有 onChange、Apply 按钮没有 onClick**——完全不可交互
- 解析进度的第 4、5 步（"Generate AI summaries"和"Build search index"）：是 `setTimeout(500)` 和 `setTimeout(300)` 的**假等待**，没有实际 API 调用

**7. Onboarding 第 5 步丢失用户输入**：拖拽上传区域**没有 `onDrop`/`onChange` 事件处理**。文本输入框有 state 绑定（`exampleText`）但**这个值从未被提交到任何 API**，用户输入的示例文本被静默丢弃。

**8. Dashboard "自动抓取状态"是硬编码假数据**（`app/page.tsx`）：
- `"Last scraped 1h ago, next in 6h"` — 硬编码字符串
- `"Session expired, please re-login"` — 无论实际状态如何，只要存在第二门课就永远显示
- "Re-login" 按钮没有 `onClick` 处理
- "Last studied" 显示的是 `created_at`（创建时间），不是实际最后学习时间

**9. NL Tuning FAB 发送原始文本作为偏好值**（`nl-tuning-fab.tsx`）：用户输入"simplify notes"后，组件把原始文本直接作为 `value` 传给 `setPreference(option.dimension, lastInput, ...)`。后端收到 `value="simplify notes"` 而不是有效枚举值如 `"concise"`。底部的"澄清"选项是 3 个硬编码选项，不根据用户输入动态生成。

**10. 5 个 API 函数定义但前端从未调用**（`lib/api.ts`）：
- `listPreferences()` — 从未 import
- `resolvePreferences()` — 从未 import
- `listWrongAnswers()` — 从未 import（错题面板未在前端实现）
- `retryWrongAnswer()` — 从未 import
- `deriveQuestion()` — 从未 import

**11. Store 中有无 UI 入口的 action**：
- `removeCourse()` — 实现了但**前端没有任何删除课程的按钮**
- `clearMessages()` — 实现了但**聊天面板没有清空按钮**

**12. 知识图谱 Canvas 不响应**（`knowledge-graph.tsx`）：`<canvas>` 硬编码 `width={800} height={600}` 但样式设为 `w-full h-full`。没有 `ResizeObserver`，面板大小变化时图表不会重绘。

**13. 状态栏学习时长永远显示 "0m"**（`course/[id]/page.tsx:322`）：`studyTime` 硬编码为 `"0m"`，没有实际时间追踪。`practiceProgress` 也从未传入。

**14. 上传对话框不支持拖拽**：UI 显示"drag & drop"文案，但没有 `onDrop`/`onDragOver` 处理器，只有 click-to-open 文件选择器。

### 安全问题汇总

| 严重性 | 位置 | 问题 |
|--------|------|------|
| 高 | `config.py:21` | JWT 密钥默认值 `"change-me-in-production"`，`AUTH_ENABLED=True` 时无启动校验 |
| 高 | `code_execution.py:123` | `exec()` 无进程隔离，可通过 Python 内省逃逸 |
| 中 | `routers/notifications.py` | 无 `get_current_user`，任何人可读任何用户通知 |
| 中 | `routers/upload.py` | `GET /jobs/{course_id}` 无鉴权 |
| 中 | `routers/workflows.py` | `POST /wrong-answer-review/mark` 无鉴权 |
| 中 | `routers/notes.py` | 无课程归属校验，任何用户可重构任何课程的笔记 |
| 低 | `config.py:9` | `redis_url` 配置声明但代码中从未使用（死配置） |
| 低 | `database.py:8` | 无 `pool_pre_ping=True`，PostgreSQL 重启后连接池中的连接会静默失败 |

### 测试覆盖评估

`tests/` 目录有 8 个测试文件，覆盖：
- API 集成测试（Health、课程 CRUD、偏好、上传、认证流程）
- 单元测试（RRF 评分、衰减公式、场景检测、文件名分类、MIME 检测、embedding 注册、密码哈希、JWT）
- 回归测试（Markdown 树构建、MIME fallback、爬取结果解析）
- Scrape/Canvas router 单元测试

**未测试的部分**（约 70% 的业务逻辑）：
- 多 Agent 编排（orchestrator + 10 个 Agent）
- 所有 6 个工作流服务
- 记忆管道（encode/consolidate/retrieve）
- 调度任务（包括有 bug 的 `fsrs_review_job`）
- 知识图谱提取
- Reflection Agent
- 前端组件（无任何前端测试）

---

## 已确认 Bug 清单（按严重性排序）

| # | 严重性 | 文件:行 | Bug 描述 |
|---|--------|---------|----------|
| 1 | **致命** | `scheduler/engine.py:105` | 引用 `LearningProgress.mastery_level` 但字段名是 `mastery_score`。`fsrs_review_job` 每小时崩溃，FSRS 复习提醒功能从未正常工作。 |
| 2 | **高** | `browser/automation.py:42` | Scrapling `fetcher.fetch(url)` 是同步阻塞调用，在 async 函数中直接执行，阻塞整个事件循环。 |
| 3 | **高** | `code_execution.py:62,123` | `MAX_EXECUTION_TIME=5` 声明但从未执行。无限循环代码可永久挂死服务。 |
| 4 | **中** | `scheduler/engine.py:10,30-31` | 文件注释说"通知存在 notifications 表"，但实际是内存列表，重启全丢。注释与代码不一致。 |
| 5 | **中** | `code_execution.py:96,123` | `_execute_safe()` 是同步函数，在 async 流式方法中直接调用，阻塞事件循环。 |
| 6 | **低** | `progress/tracker.py:61` | 使用已弃用的 `datetime.utcnow()`（无时区信息），应为 `datetime.now(timezone.utc)`。 |
