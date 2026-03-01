# OpenTutor 全量执行计划

> 基于深度代码审计的修正版。探索发现部分"缺失"实际已有实现（FSRS算法、MotivationAgent），
> 本计划仅针对**真正需要修改的问题**。

---

## Phase 0：让它稳定运行

### 0.1 LLM 调用超时 [H4]
**问题**: OpenAIClient 和 AnthropicClient 均无请求超时，LLM 无响应时请求永远挂起
**文件**: `apps/api/services/llm/router.py`
**修改**:
- OpenAIClient.__init__(): 添加 `timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10)`
- AnthropicClient.__init__(): 添加 `timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10)`
- stream_chat/chat/chat_with_tools: 确认 timeout 从 client 级别继承

### 0.2 Chat Markdown 渲染 [H7]
**问题**: chat-panel.tsx line 76 用 `whitespace-pre-wrap` 显示纯文本，不渲染 Markdown
**文件**: `apps/web/src/components/chat/chat-panel.tsx`
**修改**:
- 复用已有的 `MarkdownRenderer` 组件（`apps/web/src/components/course/markdown-renderer.tsx`）
- 替换 `<div className="whitespace-pre-wrap">{message.content}</div>` 为 `<MarkdownRenderer content={message.content} />`
- 添加 chat 场景的样式微调（较小字号、紧凑间距）

### 0.3 工具结果截断统一 [H2]
**问题**: base.py 定义 MAX_TOOL_RESULT_CHARS=8000，react_loop.py 定义 _TOOL_RESULT_CONTEXT_CHARS=4000
**文件**: `apps/api/services/agent/tools/base.py:22`, `apps/api/services/agent/tools/react_loop.py:32`
**修改**:
- 删除 react_loop.py 的本地常量
- 统一使用 base.py 的 MAX_TOOL_RESULT_CHARS（改为 6000，平衡信息量与 context 开销）
- react_loop.py 从 base 导入

### 0.4 版本对齐
**问题**: docker-compose.yml 用 pg16，CI 用 pg17；README 说 Python 3.12+，实际需要 3.11
**文件**: `docker-compose.yml:5`, `README.md:70`
**修改**:
- docker-compose.yml: `pgvector/pgvector:pg16` → `pgvector/pgvector:pg17`
- README.md: `Python 3.12+` → `Python 3.11`（注明 tiktoken 兼容性）

### 0.5 上下文加载并行化 [H1]
**问题**: orchestrator.py load_context() 三步串行（preferences → memories → content），注释声称并行
**文件**: `apps/api/services/agent/orchestrator.py`
**修改**:
- 用独立 db session 或 asyncio.gather() 并行化三个加载步骤
- 注意：每个步骤需要独立的异常处理，一个失败不应阻塞其他

### 0.6 前端 Error Boundary [H5]
**文件**: `apps/web/src/components/error-boundary.tsx`（新建）
**修改**:
- 创建 React Error Boundary 组件
- 在 layout.tsx 中包裹主内容区域
- 在 course/[id]/page.tsx 中包裹各面板

### 0.7 场景检测去重 [H3]
**问题**: load_context() 和 SceneAgent 各有场景检测逻辑
**文件**: `apps/api/services/agent/orchestrator.py`, `apps/api/services/agent/scene_agent.py`
**修改**:
- 提取 `detect_scene()` 为独立函数放在 scene_agent.py
- orchestrator.py 的 load_context() 直接调用 scene_agent 的函数

### 0.8 疲劳检测改进
**问题**: orchestrator.py 硬编码 4 个正则，有误匹配风险
**文件**: `apps/api/services/agent/orchestrator.py`
**修改**:
- 增加更多信号模式（英文、表情符号）
- 添加"积极信号"衰减（检测到"我懂了""明白了"时降低疲劳分）
- 将阈值和模式提取到配置

---

## Phase 1：核心教育能力补全

### 1.1 FSRS 连接到 LearningProgress [B1+D5]
**现状**: FSRS 算法已完整实现（`services/spaced_repetition/fsrs.py`），但 LearningProgress 模型
缺少完整 FSRS 字段（只有 ease_factor, interval_days, next_review_at，缺 difficulty, stability, reps, lapses, state）
**文件**: `apps/api/models/progress.py`, `apps/api/services/progress/tracker.py`
**修改**:
- 给 LearningProgress 添加缺失字段：difficulty, stability, reps, lapses, last_review, fsrs_state
- Alembic migration 添加新列
- tracker.py 的 `update_quiz_result()` 调用 FSRS `review_card()` 更新调度
- 确保 next_review_at 在每次答题后被正确更新

### 1.2 诊断对生成系统 [B3]
**现状**: ReviewAgent 读取 diagnostic pair 数据（diagnosis, original_layer, clean_status），
PracticeProblem 有 parent_problem_id + is_diagnostic 字段，但无生成代码
**文件**: 新建 `apps/api/services/diagnosis/pair_generator.py`
**修改**:
- 创建 `generate_diagnostic_pair(problem_id)`: 对错题生成简化版"干净"题目
- 简化策略：保留核心概念，去除干扰项/陷阱，降低难度层
- 对比原题和简化题的答题结果推断错因（fundamental_gap vs trap_vulnerability vs carelessness）
- 在 quiz submission 流程中，错题自动触发诊断对生成（异步后台）
- WrongAnswer.diagnosis 字段由对比结果填充

### 1.3 知识状态追踪 (简化 BKT) [D6]
**现状**: mastery_score = weighted decay of recent 20 results，无概率模型
**文件**: 新建 `apps/api/services/learning_science/knowledge_tracer.py`
**修改**:
- 实现简化 BKT（4 参数模型）：
  - P(L0): 初始掌握概率（从首次答题正确率估计）
  - P(T): 学习转移概率（从连续正确次数估计）
  - P(G): 猜测概率（从多选题选项数估计，默认 0.25）
  - P(S): 失误概率（从高 mastery 时仍答错的频率估计）
- 计算 P(Ln) = P(Ln-1|evidence) 作为真正的掌握概率
- 存入 LearningProgress 的 mastery_score（替代简单比率）
- 在 tracker.py update_quiz_result() 中调用

### 1.4 自适应难度选择 [D7]
**现状**: ExerciseAgent 有 3 层难度，但选择靠 LLM 判断
**文件**: `apps/api/services/agent/exercise.py`, 新建 `apps/api/services/learning_science/difficulty_selector.py`
**修改**:
- 实现基于 BKT mastery 的难度选择算法：
  - P(L) < 0.4 → Layer 1 (fundamental)
  - 0.4 <= P(L) < 0.7 → Layer 2 (transfer)
  - P(L) >= 0.7 → Layer 3 (trap)
- gap_type 也参与选择：fundamental_gap → 强制 Layer 1
- ExerciseAgent.build_system_prompt() 注入推荐难度层
- 保留 LLM 灵活性（推荐而非强制）

### 1.5 遗忘曲线预测 [D9]
**文件**: 扩展 `apps/api/services/spaced_repetition/fsrs.py`
**修改**:
- 利用已有的 `_retrievability()` 函数：R(t) = (1 + t/(9*S))^-1
- 新增 `predict_forgetting(progress_list)` → 返回各知识点的预计遗忘时间
- 新增 API 端点 `GET /api/progress/courses/{id}/forgetting-forecast`
- 前端 Progress 面板增加"遗忘预测"视图

---

## Phase 2：Agent 自主性提升

### 2.1 Multi-step Task Execution [D1]
**现状**: AgentContext 有 TaskPhase 但只做单轮；AgentTask 模型存在但未充分利用
**文件**: 新建 `apps/api/services/agent/task_planner.py`, 修改 orchestrator.py
**修改**:
- 创建 TaskPlanner：将复杂请求分解为多步 AgentTask
  - "帮我准备考试" → [检查进度, 找薄弱点, 生成练习, 安排复习]
  - 每步关联一个 specialist agent
- 扩展 orchestrate_stream()：检测复杂意图时启动 multi-step 模式
- 新增 SSE 事件类型 "plan_step" 告知前端当前执行到哪一步
- 前端展示执行进度条

### 2.2 跨 Agent 协作 (Delegation Protocol) [D2]
**文件**: 修改 `apps/api/services/agent/base.py`, `orchestrator.py`
**修改**:
- BaseAgent 添加 `delegate(target_agent, sub_context)` 方法
- 返回子 agent 的结果作为当前 agent 的 tool 输入
- 典型链：ExerciseAgent 出题 → 用户答错 → ReviewAgent 分析 → AssessmentAgent 评估
- 通过 AgentContext.delegated_agent 追踪委托链

### 2.3 主动推送系统 [D3]
**现状**: APScheduler + 内存通知存储
**文件**: 新建通知持久化模型 + WebSocket 端点
**修改**:
- 新建 Notification 数据库模型（替代内存存储）
- 新增 WebSocket 端点 `/api/ws/notifications`
- 扩展 scheduler jobs：
  - `daily_suggestion_job()`: 基于遗忘曲线推送复习提醒
  - `inactivity_alert_job()`: 超过 N 天未学习时推送鼓励
  - `goal_progress_job()`: 学习计划进度通知
- 前端：NotificationCenter 组件 + toast 提示

### 2.4 ReAct 循环深化 [D4]
**文件**: `apps/api/services/agent/tools/react_loop.py`, `react_mixin.py`
**修改**:
- 提高 react_max_iterations 默认值到 5
- 添加 observation-driven 分支：
  - tool 返回 empty/error → 尝试 alternative tool
  - 结果质量评分 < 阈值 → 自动 refine query
- 新增 education tools：
  - `check_prerequisites(topic)`: 检查先修知识是否掌握
  - `suggest_related_topics(topic)`: 推荐相关知识点
  - `get_forgetting_forecast(user_id, course_id)`: 获取遗忘预测

### 2.5 Evaluation 框架 [D15]
**文件**: 新建 `apps/api/services/evaluation/`
**修改**:
- 创建 offline eval 框架：
  - `eval_routing.py`: 意图分类准确率（golden intent → actual intent）
  - `eval_retrieval.py`: RAG 召回质量（golden docs → retrieved docs）
  - `eval_response.py`: 回答质量（LLM-as-judge: correctness, relevance, helpfulness）
- 创建 golden transcript fixtures
- 添加 CI eval step（optional，类似 llm-integration）
- 追踪指标随时间的变化

---

## Phase 3：产品体验跃升

### 3.1 多模态输入 [D10]
**文件**: 新建 `apps/api/services/multimodal/`, 修改 chat router
**修改**:
- 图片输入：利用 GPT-4o / Claude 的 vision 能力
  - 前端：Chat 输入框添加图片上传按钮
  - 后端：chat 请求支持 image attachments
  - LLM client：OpenAIClient/AnthropicClient 支持 image_url 消息格式
- 数学公式 OCR：调用 vision model 识别手写/照片中的公式
- 图表理解：自动分析上传的图表/示意图

### 3.2 PWA + 离线支持 [D12+D13]
**文件**: `apps/web/public/manifest.json`（新建），service worker
**修改**:
- 添加 Web App Manifest（icon, theme, display: standalone）
- 实现 Service Worker：缓存静态资源 + 课程数据
- 离线时显示已缓存的笔记/闪卡
- 安装提示 UI

### 3.3 分析仪表盘 [D14]
**文件**: `apps/web/src/app/analytics/page.tsx`
**修改**:
- 学习趋势折线图（每日学习时间、正确率）
- 知识地图热力图（掌握程度可视化）
- 遗忘预测曲线（基于 FSRS retrievability）
- 错误模式分析（分类分布饼图）
- 使用 recharts 或 chart.js 库

### 3.4 记忆系统升级 [D16]
**文件**: `apps/api/services/memory/pipeline.py`
**修改**:
- Consolidation 增强：
  - 相似记忆合并（不只是去重，而是语义融合）
  - 情景记忆：将连续对话的碎片记忆串成学习经历
  - 基于记忆构建"学习画像"prompt section
- 记忆可见化：
  - API: GET /api/memory/profile → 返回学习画像
  - 前端：Settings 中增加"学习画像"查看/编辑页

### 3.5 学习路径优化 [D8]
**文件**: 新建 `apps/api/services/learning_science/path_optimizer.py`
**修改**:
- 基于 KnowledgePoint.dependencies 构建 DAG
- 拓扑排序确定学习顺序
- 加入掌握程度权重：已掌握的跳过，薄弱的优先
- 加入时间约束：deadline 前的关键路径分析
- PlanningAgent 使用优化后的路径生成计划

---

## Phase 4：竞争壁垒

### 4.1 安全加固 [D18]
**修改**:
- FastAPI 中间件添加安全头（CSP, HSTS, X-Frame-Options, X-Content-Type-Options）
- Prompt injection 检测：input guard 在 orchestrator 入口检查
- Audit log：记录所有 API 调用 + agent 决策到审计表
- Rate limiting：使用 slowapi 或自定义中间件

### 4.2 A/B 测试框架 [D17]
**修改**:
- Experiment 模型：name, variants, allocation, metrics
- 用户分组：基于 user_id hash 分配 variant
- Metric 收集：mastery_score 变化、session 时长、正确率变化
- 分析端点：GET /api/experiments/{id}/results

### 4.3 知识图谱深化
**修改**:
- 基于 KnowledgePoint + dependencies 的推理能力
- 前端：可交互的力导向图（D3.js）
- 点击节点显示掌握程度、推荐练习
- 路径推荐：从当前位置到目标知识点的最优路径

### 4.4 协作学习基础 [D11]
**修改**:
- 分享功能：笔记/闪卡/学习计划生成分享链接
- 教师视图：查看学生群体进度（需 AUTH_ENABLED=true）
- 后续：实时协作、组队学习

---

## 验证策略

每个 Phase 完成后：
1. 运行现有测试：`pytest tests/test_api_unit_basics.py tests/test_services.py`
2. 运行集成测试：`pytest tests/test_api_integration.py`
3. 检查 TypeScript 编译：`cd apps/web && npm run build`
4. 新功能添加对应测试
5. 手动验证关键用户流程
