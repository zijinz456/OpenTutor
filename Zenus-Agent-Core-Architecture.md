# Zenus Agent Core — 底层架构与能力设计

---

## 〇、Agent 定位

Zenus Agent 是一个**上下文感知的学习 Agent**。它不是一个通用聊天机器人，而是一个能感知用户当前学习场景、自动学习用户偏好、持续追踪知识掌握状态的专用 Agent。

上层的所有功能（笔记重构、做题、学习计划、模版市场）都是在调用这个 Agent 的底层能力。Agent 本身只关心五件事：

1. **我现在看到什么？**（上下文组装）
2. **用户想让我做什么？**（意图路由）
3. **用户喜欢什么方式？**（偏好记忆）
4. **用户学到哪了？**（学习记忆）
5. **我能做什么操作？**（工具调用）

---

## 一、整体调用链

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────┐
│  1. Context Assembler（上下文组装器）          │
│     拉取：场景信息 + 偏好 + RAG结果 + 历史     │
│     输出：完整的 System Prompt + User Message  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  2. LLM 推理（带 Tool Calling）               │
│     模型：用户自备 API Key，LiteLLM 统一接口    │
│     输入：组装好的 prompt                      │
│     输出：文本回复 + 可选的 tool_calls          │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  3. Intent Router（意图路由器）                │
│     三条路径：偏好反馈 / 学习提问 / 操作指令     │
│     路由方式：LLM 自分类 or 前置分类器          │
└──────┬───────────┬──────────────┬────────────┘
       │           │              │
       ▼           ▼              ▼
   偏好更新     RAG回答       工作流触发
   重新渲染     引用课件       生成内容
       │           │              │
       └───────────┴──────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  4. Post-Conversation Pipeline（对话后处理）   │
│     异步触发：                                │
│     ├── 对话摘要 → conversation_memories      │
│     ├── 偏好信号提取（双轨LLM）→ preference_signals │
│     └── 学习表现更新 → knowledge_mastery       │
└─────────────────────────────────────────────┘
```

---

## 二、子系统 1：上下文组装器（Context Assembler）

### 2.1 职责

每次 LLM 调用前，把散落在各处的信息拼成一份结构化的 prompt。这个模块决定了 Agent "看到"什么。

### 2.2 上下文来源（6 个数据源）

| # | 数据源 | 来自哪里 | 注入位置 | 优先级 |
|---|--------|---------|---------|--------|
| 1 | 当前场景 | 前端传入的 Tab 类型 + 当前内容 | System Prompt 尾部 | 最高（必须包含） |
| 2 | 用户偏好 | Preference Cascade Engine resolve 后的 JSON | System Prompt 头部 | 最高（必须包含） |
| 3 | 课件检索结果 | PageIndex 树搜索返回的相关章节 | User Message 附加 | 高 |
| 4 | 对话记忆 | pgvector 向量检索返回的相关历史 | User Message 附加 | 中 |
| 5 | 学习状态 | 当前课程的 knowledge_mastery 概要 | System Prompt 中部 | 中 |
| 6 | 对话历史 | 当前 session 的最近 N 轮消息 | Messages 数组 | 最高（必须包含） |

### 2.3 Prompt 组装结构

```
System Prompt:
├── [ROLE] Agent 角色定义 + 行为准则
├── [PREFERENCES] 用户偏好 JSON（cascade resolve 后）
│   {
│     "notes_format": "bullet_summary",
│     "detail_level": "concise",
│     "language": "zh-CN",
│     "visualization": "auto"
│   }
├── [LEARNING_STATE] 当前课程学习状态概要
│   "用户在「线性代数」的薄弱知识点：特征值分解(mastery=35)、正交化(mastery=42)"
├── [TOOLS] 可用工具定义（function calling schema）
├── [INTENT_GUIDE] 三类意图定义 + 判断准则 + 示例
└── [SCENE] 当前场景上下文
    "用户正在 Quiz Tab，正在做第 3/20 题，题目内容：..."

Messages:
├── 历史对话（最近 N 轮）
├── [RAG_CONTEXT] 课件检索结果
│   "以下是与用户问题相关的课件内容：\n[Chapter 3.2] 特征值分解的定义..."
├── [MEMORY_CONTEXT] 相关对话记忆
│   "用户在 2 天前的对话中提到过对特征值的困惑..."
└── 用户当前消息
```

### 2.4 Context Window 管理策略

总 token 预算按模型能力分配（例如 128K 模型的预算分配）：

```
Token 预算分配：
├── System Prompt 固定部分（角色+工具+意图指南）  ～2,000 tokens
├── 偏好 JSON                                    ～500 tokens
├── 学习状态概要                                  ～500 tokens
├── 当前场景                                      ～1,000 tokens（取决于 Tab 内容）
├── 对话历史                                      ～4,000 tokens（最近 10-15 轮）
├── RAG 课件结果                                  ～3,000 tokens（Top-5 chunks）
├── 对话记忆                                      ～1,000 tokens（Top-3 memories）
├── 用户消息                                      ～500 tokens
└── 预留给模型输出                                 ～4,000 tokens
    ─────────────────────────────────────────
    总计 ≈ 16,500 tokens（保守估计，128K 模型下可扩大）
```

**截断策略**：当总 token 超预算时，按以下顺序裁剪：
1. 对话记忆（从最不相关的开始丢弃）
2. RAG 结果（从排名最低的 chunk 开始丢弃）
3. 对话历史（从最早的轮次开始丢弃，保留最近 3 轮）
4. 场景信息和偏好**永不截断**

### 2.5 接口定义

```python
class ContextAssembler:
    """
    每次 LLM 调用前，组装完整的 prompt。
    """

    async def assemble(
        self,
        user_message: str,
        user_id: str,
        project_id: str,
        session_id: str,
        scene: SceneContext,        # 前端传入的当前 Tab 信息
    ) -> AssembledPrompt:
        """
        返回组装好的 prompt，可直接传给 LiteLLM。
        """

        # 1. Resolve 偏好
        preferences = await self.preference_engine.resolve(
            user_id, scene.course_id, scene.tab_type
        )

        # 2. 获取学习状态
        learning_state = await self.learning_memory.get_summary(
            user_id, scene.course_id
        )

        # 3. RAG 检索
        rag_results = await self.retrieval_engine.search(
            query=user_message,
            course_id=scene.course_id,
            top_k=5
        )

        # 4. 对话记忆检索
        memory_results = await self.memory_store.search(
            query=user_message,
            user_id=user_id,
            top_k=3
        )

        # 5. 对话历史
        history = await self.session_store.get_recent(
            session_id=session_id,
            max_turns=15
        )

        # 6. 组装 + Token 预算管理
        return self._build_prompt(
            user_message=user_message,
            preferences=preferences,
            learning_state=learning_state,
            scene=scene,
            rag_results=rag_results,
            memory_results=memory_results,
            history=history,
            token_budget=self.config.token_budget
        )


@dataclass
class SceneContext:
    """前端传入的当前场景信息"""
    tab_type: str           # "notes" | "quiz" | "plan" | "graph" | "review" | ...
    course_id: str
    content_snapshot: str   # 当前 Tab 的核心内容（题目/笔记/计划）
    metadata: dict          # Tab 特定的额外信息（如当前题号、章节ID等）


@dataclass
class AssembledPrompt:
    """组装完成的 prompt，可直接传给 LiteLLM"""
    system_message: str
    messages: list[dict]    # [{"role": "user"/"assistant", "content": "..."}]
    tools: list[dict]       # function calling schema
    token_count: int        # 实际使用的 token 数
```

---

## 三、子系统 2：意图路由器（Intent Router）

### 3.1 职责

判断用户的消息属于哪一类，然后触发不同的下游处理逻辑。

### 3.2 三类意图定义

```
┌────────────────────────────────────────────────────────┐
│                    用户消息                              │
└────────────────────┬───────────────────────────────────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ 偏好反馈  │ │ 学习提问  │ │ 操作指令  │
    │ PREF     │ │ LEARN    │ │ ACTION   │
    └────┬─────┘ └────┬─────┘ └────┬─────┘
         │            │            │
         ▼            ▼            ▼
    更新偏好      RAG检索+回答    触发工作流
    重新渲染      引用课件       Tool Call
    Toast确认     标注来源       结果→Tab
```

| 意图类型 | 触发特征 | 典型用语 | 下游动作 |
|---------|---------|---------|---------|
| **PREF（偏好反馈）** | 涉及格式、样式、布局、详略、语言的变化 | "太长了"、"换成表格"、"以后用英文"、"字大一点" | tool call → update_preference → 重新渲染 |
| **LEARN（学习提问）** | 关于学科知识/概念的疑问 | "什么是微分方程"、"这题为什么选A"、"解释一下这个概念" | RAG检索 → 引用课件回答 → 写入对话记忆 |
| **ACTION（操作指令）** | 要求 Agent 执行某个动作 | "出5道选择题"、"做个复习计划"、"把PDF题拆出来" | tool call → 触发对应工作流 → 结果渲染到Tab |

### 3.3 路由实现方案

**推荐方案：LLM 自分类（Prompt 内分类）**

不单独调用分类模型，而是在 System Prompt 的 `[INTENT_GUIDE]` 区域明确定义三类意图的判断规则，让主模型在回复时自动分类并选择对应的 tool call。

```
# System Prompt 中的 INTENT_GUIDE 部分

你需要在回复前先判断用户意图，分为三类：

[PREF] 偏好反馈 — 用户在表达对输出格式、布局、详略、语言等的偏好。
  信号词：太长/太短、换成XX格式、放大/缩小、用XX语言、我更喜欢...
  行动：调用 update_preference 工具，然后确认更新。

[LEARN] 学习提问 — 用户在问学科知识或概念。
  信号词：什么是、为什么、怎么理解、解释一下...
  行动：基于提供的课件内容回答，标注引用来源。

[ACTION] 操作指令 — 用户要求你执行某个任务。
  信号词：帮我生成、出几道题、做个计划、整理一下...
  行动：调用对应的工具完成任务。

特殊判断：
- "这个概念没看懂" → 先检查当前 detail_level：
  - 如果是 concise 模式 → 可能是笔记太简略（PREF），追问确认
  - 如果是 detailed 模式 → 大概率是学习问题（LEARN），直接解释
```

**为什么不用前置分类器？**
- 多一次 LLM 调用 = 多一次延迟 + 多一份成本
- 主模型在 System Prompt 指导下已经能很好地判断意图
- 边界 case（如"没看懂"到底是 PREF 还是 LEARN）需要上下文信息才能判断，分类器拿不到完整上下文

**降级方案（如果自分类不稳定）：**
- 给 LLM 的输出加一个 `intent` 字段的 structured output
- 或者用 tool_choice 机制：偏好类操作必须走 `update_preference` tool，操作类走对应 action tool，纯文本回复 = LEARN

### 3.4 边界 Case 处理

```python
EDGE_CASES = {
    "没看懂 / 不理解": {
        "判断逻辑": "检查当前 detail_level 偏好",
        "concise模式": "追问：是概念难还是笔记太简略？",
        "detailed模式": "直接当 LEARN 处理",
    },
    "这个例子不好": {
        "判断逻辑": "检查是否涉及内容准确性",
        "内容错误": "LEARN — 提供更好的解释",
        "风格不合": "PREF — 更新示例风格偏好",
    },
    "帮我换一种说法": {
        "判断逻辑": "可能是 PREF，也可能是 ACTION",
        "处理": "默认当 PREF（更新表达风格偏好），同时重新生成",
    },
    "混合意图": {
        "例子": "这个概念帮我解释一下，用表格的形式",
        "处理": "LEARN + PREF 同时处理：RAG 检索 + 表格格式输出 + 记录格式偏好",
    },
}
```

---

## 四、子系统 3：偏好记忆系统（Preference Memory）

### 4.1 系统概览

偏好记忆负责 Agent "记住用户喜欢什么方式"。

```
┌──────────────────────────────────────────────────────┐
│                  偏好记忆系统                          │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │  采集层（三步走）                               │    │
│  │  ├── Onboarding 初始化选项                     │    │
│  │  ├── 自然语言微调（实时）                       │    │
│  │  └── 行为自动学习（双轨LLM异步提取）            │    │
│  └──────────────────┬───────────────────────────┘    │
│                     │ preference_signals              │
│                     ▼                                │
│  ┌──────────────────────────────────────────────┐    │
│  │  存储层                                       │    │
│  │  ├── preference_signals（待确认信号 + 置信度）  │    │
│  │  └── user_preferences（已确认偏好）            │    │
│  └──────────────────┬───────────────────────────┘    │
│                     │                                │
│                     ▼                                │
│  ┌──────────────────────────────────────────────┐    │
│  │  解析层（7层 Cascade）                         │    │
│  │  临时 → 课程场景 → 课程 → 全局场景             │    │
│  │  → 全局 → 模版 → 系统默认                      │    │
│  │  输出：resolved_preferences JSON               │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 4.2 偏好维度

Agent 需要追踪的偏好维度：

| 维度 | 可选值 | 影响范围 | 默认值 |
|------|-------|---------|--------|
| `notes_format` | bullet_summary / mindmap / table / detailed_paragraph / step_by_step | 笔记 Tab 的输出格式 | bullet_summary |
| `detail_level` | concise / moderate / detailed | 所有文本输出的详略程度 | moderate |
| `language` | zh-CN / en-US / mixed | 输出语言 | 跟随课件语言 |
| `visualization` | auto / prefer_mermaid / prefer_table / prefer_text | 可视化方式选择 | auto |
| `explanation_style` | example_first / theory_first / analogy_based | 解释概念时的风格 | theory_first |
| `quiz_feedback` | immediate / after_submit / detailed_steps | 做题反馈时机和详细度 | immediate |
| `formality` | casual / academic / mixed | 语言正式程度 | academic |

### 4.3 采集层：三步走

#### Step 1: Onboarding 初始化

```python
ONBOARDING_QUESTIONS = [
    {
        "dimension": "notes_format",
        "question": "你喜欢什么样的笔记格式？",
        "options": [
            {"value": "bullet_summary", "label": "要点列表"},
            {"value": "mindmap", "label": "思维导图"},
            {"value": "table", "label": "表格对比"},
            {"value": "detailed_paragraph", "label": "详细段落"},
        ],
        "skippable": True,
    },
    {
        "dimension": "detail_level",
        "question": "你希望内容多详细？",
        "options": [
            {"value": "concise", "label": "精简（快速浏览）"},
            {"value": "moderate", "label": "适中"},
            {"value": "detailed", "label": "详细（完整解释）"},
        ],
        "skippable": True,
    },
    {
        "dimension": "language",
        "question": "输出语言偏好？",
        "options": [
            {"value": "zh-CN", "label": "中文"},
            {"value": "en-US", "label": "English"},
            {"value": "mixed", "label": "中英混合"},
        ],
        "skippable": True,
    },
]

# Onboarding 结果直接写入 user_preferences
# scope = "global", source = "onboarding", confidence = 1.0
```

#### Step 2: 自然语言微调（实时）

```python
# 当 Intent Router 判断为 PREF 时触发

async def handle_preference_feedback(
    user_message: str,
    current_scene: SceneContext,
    current_preferences: dict,
) -> PreferenceUpdate:
    """
    AI 解析自然语言偏好反馈，映射到具体操作。
    """
    # AI 判断要更新哪个维度、更新成什么值
    # 示例映射：
    #   "太长了"           → detail_level = "concise"
    #   "换成思维导图"      → notes_format = "mindmap"
    #   "以后都用英文"      → language = "en-US", scope = "global"
    #   "这门课用表格比较好" → notes_format = "table", scope = "course"

    # 模糊表达 → 追问
    #   "换个方式" → "你希望换成哪种方式？表格/思维导图/详细段落？"

    update = PreferenceUpdate(
        dimension="notes_format",
        value="mindmap",
        scope=determine_scope(user_message),  # global / course / temporary
        source="explicit",
        confidence=1.0,  # 用户明确说的 → 置信度 = 1.0
    )

    # 立即写入 user_preferences
    await preference_store.update(update)

    # 触发重新渲染
    return update
```

#### Step 3: 行为自动学习（双轨 LLM）

```python
async def extract_preference_signals(
    conversation: list[Message],
    current_preferences: dict,
) -> list[PreferenceSignal] | None:
    """
    对话结束后异步调用，用小模型提取偏好信号。
    95% 的情况返回 None（无偏好信号）。
    """

    # 小模型 prompt
    extraction_prompt = """
    分析以下对话，判断用户是否隐含了新的偏好信号。
    只关注：格式偏好、详细程度、语言选择、可视化方式、解释风格。

    当前已知偏好：{current_preferences}

    如果没有发现任何新的偏好信号，返回 NONE。
    如果发现了，返回 JSON：
    {
        "dimension": "...",
        "value": "...",
        "evidence": "用户原话或行为描述",
        "signal_type": "explicit | behavioral | pattern"
    }
    """

    result = await litellm.completion(
        model="gpt-4o-mini",  # 小模型，成本低
        messages=[{"role": "user", "content": extraction_prompt}],
    )

    if result == "NONE":
        return None

    # 存入 preference_signals（待确认）
    signal = PreferenceSignal(
        dimension=result.dimension,
        value=result.value,
        evidence=result.evidence,
        base_score=SIGNAL_WEIGHTS[result.signal_type],
        # explicit=0.7, behavioral=0.5, pattern=0.3
    )
    await signal_store.save(signal)
    return signal
```

### 4.4 置信度计算与确认机制

```python
def calculate_confidence(signals: list[PreferenceSignal]) -> float:
    """
    计算某个偏好维度的最终置信度。
    """
    if not signals:
        return 0.0

    # 基础分（信号类型决定）
    base = max(s.base_score for s in signals)

    # 频率因子（同一信号出现越多次越可信）
    frequency = min(len(signals) / 5, 1.0)  # 5次封顶

    # 一致性因子（信号之间是否矛盾）
    values = [s.value for s in signals]
    most_common = Counter(values).most_common(1)[0][1]
    consistency = most_common / len(values)

    confidence = base * (0.4 + 0.3 * frequency + 0.3 * consistency)
    return round(confidence, 2)


# 确认阈值
CONFIRMATION_THRESHOLD = 0.6

# 达到阈值 → 弹窗确认
# 用户选择：
#   "长期习惯"    → scope = "global", source = "confirmed"
#   "这门课专属"  → scope = "course", source = "confirmed"
#   "不改"        → 丢弃信号
```

### 4.5 Cascade 解析引擎

```python
class PreferenceCascadeEngine:
    """
    7 层 cascade 解析，从最具体到最通用。
    """

    async def resolve(
        self,
        user_id: str,
        course_id: str | None,
        scene_type: str | None,  # "notes" | "quiz" | "plan" | ...
    ) -> dict:
        """
        返回解析后的完整偏好 JSON。
        每个维度独立解析，取第一个命中的层级。
        """
        resolved = {}

        for dimension in PREFERENCE_DIMENSIONS:
            value = None

            # Layer 1: 临时偏好（当前 session 内有效）
            value = value or await self._get(user_id, dimension,
                scope="temporary")

            # Layer 2: 课程 + 场景偏好
            if course_id and scene_type:
                value = value or await self._get(user_id, dimension,
                    scope="course_scene", course_id=course_id,
                    scene_type=scene_type)

            # Layer 3: 课程偏好
            if course_id:
                value = value or await self._get(user_id, dimension,
                    scope="course", course_id=course_id)

            # Layer 4: 全局 + 场景偏好
            if scene_type:
                value = value or await self._get(user_id, dimension,
                    scope="global_scene", scene_type=scene_type)

            # Layer 5: 全局偏好
            value = value or await self._get(user_id, dimension,
                scope="global")

            # Layer 6: 模版偏好
            value = value or await self._get_template_default(
                user_id, dimension)

            # Layer 7: 系统默认
            value = value or SYSTEM_DEFAULTS[dimension]

            resolved[dimension] = value

        return resolved
```

### 4.6 偏好更新机制（非时间衰退）

```
偏好不按时间衰退，而是通过行为覆盖更新：

旧偏好：notes_format = "bullet_summary" (confidence=0.8)
新行为：用户最近 3 次都要求 "table"

→ 新信号累积：
  signal_1: table (base=0.5, 行为推断)
  signal_2: table (base=0.5, 行为推断)
  signal_3: table (base=0.7, 明确表达)

→ confidence("table") = 0.7 × (0.4 + 0.3×0.6 + 0.3×1.0) = 0.63
→ 超过阈值 0.6 → 触发确认弹窗
→ 用户确认 → notes_format = "table" (confidence=1.0, source=confirmed)
→ 旧偏好被覆盖（不删除，标记为 superseded，保留审计轨迹）
```

---

## 五、子系统 4：学习记忆系统（Learning Memory）

### 5.1 系统概览

学习记忆负责 Agent "记住用户学到哪了"。

```
┌──────────────────────────────────────────────────────┐
│                  学习记忆系统                          │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │  知识图谱层                                    │    │
│  │  ├── 知识点提取（LLM 从课件中提取）             │    │
│  │  ├── 依赖关系构建（DAG）                       │    │
│  │  └── 节点：{name, prerequisites[], mastery}    │    │
│  └──────────────────┬───────────────────────────┘    │
│                     │                                │
│  ┌──────────────────┼──────────────────────────┐    │
│  │  掌握度追踪层     │                           │    │
│  │  ├── 做题结果 ────┤──→ mastery 上升/下降       │    │
│  │  ├── 错因分析 ────┤──→ 标记薄弱知识点          │    │
│  │  └── FSRS 衰退 ──┤──→ 遗忘曲线自然下降        │    │
│  └──────────────────┼───────────────────────────┘    │
│                     │                                │
│  ┌──────────────────┼──────────────────────────┐    │
│  │  间隔复习层（FSRS）│                           │    │
│  │  ├── 错题 → FSRS 卡片                         │    │
│  │  ├── 复习评分 → 更新 stability                 │    │
│  │  └── retrievability = exp(-t/stability)        │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 5.2 知识图谱构建

```python
class KnowledgeGraphBuilder:
    """
    从课件内容中提取知识点和依赖关系。
    """

    async def build_from_course(
        self, course_id: str, content_tree: ContentTree
    ) -> KnowledgeGraph:
        """
        Step 1: 用 LLM 提取知识点列表
        Step 2: 用 LLM 分析知识点间的依赖关系
        Step 3: 构建 DAG（有向无环图）
        Step 4: 验证图的合法性（无环检测）
        """

        # LLM 提取知识点
        extraction_prompt = """
        分析以下课程内容，提取核心知识点列表。
        每个知识点包含：
        - name: 知识点名称
        - description: 一句话描述
        - chapter_refs: 出现在哪些章节

        课程内容：
        {content}
        """

        knowledge_points = await self._extract_points(content_tree)

        # LLM 分析依赖关系
        dependency_prompt = """
        给定以下知识点列表，分析它们之间的前置依赖关系。
        如果理解 B 需要先掌握 A，则 A → B。
        只标注直接依赖，不标注传递依赖。

        知识点列表：
        {points}
        """

        dependencies = await self._analyze_dependencies(knowledge_points)

        # 构建 DAG
        graph = KnowledgeGraph()
        for point in knowledge_points:
            graph.add_node(point)
        for dep in dependencies:
            graph.add_edge(dep.prerequisite, dep.dependent)

        # 环检测
        if graph.has_cycle():
            graph = self._break_cycles(graph)  # 用 LLM 辅助判断哪条边应该去掉

        return graph


@dataclass
class KnowledgeNode:
    node_id: str
    name: str
    course_id: str
    description: str
    chapter_refs: list[str]       # 关联的章节 ID
    prerequisites: list[str]      # 前置知识点 ID
    mastery_level: float          # 0-100，掌握程度
    last_practiced: datetime | None
    fsrs_card_ids: list[str]      # 关联的 FSRS 卡片
```

### 5.3 掌握度计算

```python
class MasteryTracker:
    """
    追踪每个知识点的掌握程度。
    """

    async def update_after_practice(
        self,
        user_id: str,
        problem_id: str,
        is_correct: bool,
        knowledge_point_ids: list[str],
    ):
        """做题后更新掌握度"""
        for kp_id in knowledge_point_ids:
            mastery = await self.store.get_mastery(user_id, kp_id)

            if is_correct:
                # 正确 → mastery 上升（递减增长，越高越难涨）
                delta = (100 - mastery.level) * 0.1
                mastery.level = min(100, mastery.level + delta)
            else:
                # 错误 → mastery 下降
                mastery.level = max(0, mastery.level - 10)
                # 记录错因
                await self._record_error(user_id, problem_id, kp_id)

            mastery.last_practiced = datetime.now()
            await self.store.save_mastery(mastery)

    async def apply_fsrs_decay(self, user_id: str, course_id: str):
        """
        定期任务：根据 FSRS 遗忘曲线衰减 mastery。
        retrievability = exp(-t / stability)
        """
        all_cards = await self.fsrs_store.get_cards(user_id, course_id)

        for card in all_cards:
            days_since_review = (datetime.now() - card.last_review).days
            retrievability = math.exp(-days_since_review / card.stability)

            # mastery 受 retrievability 影响
            kp = await self.store.get_mastery(user_id, card.knowledge_point_id)
            kp.level = kp.base_level * retrievability
            # base_level = 上次做对时的 mastery
            # 随时间推移 retrievability 下降 → mastery 自然下降
            await self.store.save_mastery(kp)


    def get_weak_points(
        self, user_id: str, course_id: str, threshold: float = 60
    ) -> list[KnowledgeNode]:
        """
        获取薄弱知识点：
        1. mastery < threshold
        2. 且有后继节点依赖它（图谱中的下游知识点）
        → 这些点优先复习
        """
        ...
```

### 5.4 FSRS 间隔复习集成

```python
from fsrs import FSRS, Card, Rating

class SpacedRepetitionManager:
    """
    基于 py-fsrs 的间隔复习管理。
    """

    def __init__(self):
        self.fsrs = FSRS()  # 使用默认参数，后续可根据用户数据优化

    async def create_card_from_wrong_answer(
        self, wrong_answer: WrongAnswer
    ) -> FSRSCard:
        """错题自动创建 FSRS 卡片"""
        card = Card()  # py-fsrs 的 Card 对象
        db_card = FSRSCard(
            card_id=generate_id(),
            user_id=wrong_answer.user_id,
            problem_id=wrong_answer.problem_id,
            knowledge_point_ids=wrong_answer.knowledge_points,
            fsrs_card=card,
            created_at=datetime.now(),
        )
        await self.store.save(db_card)
        return db_card

    async def review_card(
        self, card_id: str, rating: Rating
    ) -> datetime:
        """
        用户复习后评分，返回下次复习时间。
        Rating: Again(1) / Hard(2) / Good(3) / Easy(4)
        """
        db_card = await self.store.get(card_id)
        scheduling_cards = self.fsrs.repeat(db_card.fsrs_card, datetime.now())
        updated_card = scheduling_cards[rating].card

        db_card.fsrs_card = updated_card
        db_card.next_review = scheduling_cards[rating].review_log.review
        await self.store.save(db_card)

        # 更新对应知识点的 mastery
        await self.mastery_tracker.update_after_review(
            db_card.user_id,
            db_card.knowledge_point_ids,
            rating
        )

        return db_card.next_review

    async def get_due_cards(self, user_id: str) -> list[FSRSCard]:
        """获取今天需要复习的卡片"""
        return await self.store.get_due(user_id, datetime.now())
```

### 5.5 错因分析

```python
class ErrorAnalyzer:
    """
    AI 分析做题错误的原因，归类并标记薄弱知识点。
    """

    ERROR_CATEGORIES = [
        "concept_confusion",    # 概念混淆（如：混淆了特征值和特征向量）
        "calculation_error",    # 计算错误（思路对但算错了）
        "misread_question",     # 审题不清（看错条件/要求）
        "knowledge_gap",        # 知识缺失（完全不知道这个知识点）
        "application_error",    # 应用错误（知道概念但不会用）
    ]

    async def analyze(
        self,
        problem: Problem,
        user_answer: str,
        correct_answer: str,
        course_content: str,  # RAG 检索到的相关课件
    ) -> ErrorAnalysis:
        prompt = """
        分析学生的答题错误：

        题目：{problem}
        学生答案：{user_answer}
        正确答案：{correct_answer}
        相关课件内容：{course_content}

        请返回：
        1. error_category: 错因类型
        2. explanation: 为什么错了（引用课件解释）
        3. weak_points: 需要加强的知识点 ID 列表
        4. suggestion: 学习建议
        """
        ...
```

---

## 六、子系统 5：检索引擎（Retrieval Engine）

### 6.1 双路径检索架构

```
用户提问
    │
    ├──────────────────────────────┐
    │                              │
    ▼                              ▼
┌────────────────────┐  ┌────────────────────┐
│  路径 1: PageIndex  │  │  路径 2: pgvector   │
│  树形推理搜索       │  │  向量语义检索        │
│                    │  │                    │
│  搜索对象：         │  │  搜索对象：          │
│  course_content_   │  │  conversation_     │
│  tree (课件内容)    │  │  memories (对话记忆) │
│                    │  │                    │
│  搜索方式：         │  │  搜索方式：          │
│  LLM推理导航树节点  │  │  embedding 余弦相似  │
│  精准定位章节       │  │  Top-K 检索         │
│                    │  │                    │
│  准确率：98.7%      │  │  用途：补充上下文     │
└────────┬───────────┘  └────────┬───────────┘
         │                       │
         │   Top-K results       │   Top-K results
         │                       │
         ▼                       ▼
    ┌─────────────────────────────────┐
    │  RRF 融合排名                    │
    │  score = Σ 1/(60 + rank_i)      │
    │  合并去重 → 最终 Top-K           │
    └────────────────┬────────────────┘
                     │
                     ▼
              注入 LLM 上下文
```

### 6.2 PageIndex 树搜索

```python
class PageIndexSearcher:
    """
    基于 content_tree 的 LLM 推理搜索。
    不同于传统向量检索，PageIndex 让 LLM 像人一样"翻目录"找内容。
    """

    async def search(
        self,
        query: str,
        course_id: str,
        top_k: int = 5,
    ) -> list[ContentChunk]:
        # 获取课程的内容树
        tree = await self.store.get_content_tree(course_id)

        # LLM 推理导航：从根节点开始，逐层判断应该往哪个子节点走
        navigation_prompt = """
        用户问题：{query}

        当前树层级的节点：
        {current_level_nodes}

        请判断用户的问题最可能在哪个/哪些节点下找到答案。
        返回要展开的节点 ID 列表。
        """

        # 递归导航直到叶节点
        target_nodes = await self._navigate(tree.root, query)

        # 提取目标节点的内容
        chunks = []
        for node in target_nodes[:top_k]:
            chunk = await self.store.get_content(node.node_id)
            chunks.append(ContentChunk(
                node_id=node.node_id,
                title=node.title,
                content=chunk,
                source=f"[{node.chapter_path}]",  # 如 [Chapter 3.2]
            ))

        return chunks
```

### 6.3 pgvector 对话记忆检索

```python
class MemoryRetriever:
    """
    基于 pgvector 的对话记忆向量检索。
    """

    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int = 3,
    ) -> list[ConversationMemory]:
        # 生成查询 embedding
        query_embedding = await self.embedder.embed(query)

        # pgvector 余弦相似度检索
        results = await self.db.execute("""
            SELECT *, 1 - (embedding <=> $1) AS similarity
            FROM conversation_memories
            WHERE user_id = $2
            ORDER BY similarity DESC
            LIMIT $3
        """, query_embedding, user_id, top_k)

        return [ConversationMemory(**r) for r in results]


    async def encode_memory(
        self,
        session_id: str,
        conversation: list[Message],
    ):
        """
        对话结束后，提取摘要并存储为记忆。
        """
        summary = await self._summarize(conversation)
        embedding = await self.embedder.embed(summary)

        memory = ConversationMemory(
            memory_id=generate_id(),
            session_id=session_id,
            user_id=conversation[0].user_id,
            summary=summary,
            embedding=embedding,
            created_at=datetime.now(),
            evidence_refs=[session_id],  # 追溯到原始对话
        )
        await self.store.save(memory)
```

### 6.4 RRF 融合

```python
def reciprocal_rank_fusion(
    pageindex_results: list[ContentChunk],
    memory_results: list[ConversationMemory],
    k: int = 60,
    final_top_k: int = 5,
) -> list[RetrievalResult]:
    """
    RRF 融合排名：score = Σ 1/(k + rank_i)
    k=60 是经验值，平衡不同来源的排名差异。
    """
    scores = defaultdict(float)

    for rank, chunk in enumerate(pageindex_results):
        scores[chunk.id] += 1 / (k + rank + 1)  # rank 从 1 开始
        scores[chunk.id]  # 记录来源

    for rank, memory in enumerate(memory_results):
        scores[memory.id] += 1 / (k + rank + 1)

    # 按融合分数排序
    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:final_top_k]
```

---

## 七、子系统 6：工具调用层（Tool Layer）

### 7.1 Agent 可用工具清单

Agent 通过 LLM function calling 调用以下工具：

```python
AGENT_TOOLS = [
    # ── 偏好操作 ──
    {
        "name": "update_preference",
        "description": "更新用户偏好设置",
        "parameters": {
            "dimension": "要更新的偏好维度",
            "value": "新值",
            "scope": "global | course | course_scene | temporary",
        }
    },
    {
        "name": "set_layout_preset",
        "description": "切换界面布局预设",
        "parameters": {
            "preset": "notesFocused | quizFocused | splitView | default",
        }
    },

    # ── 内容生成 ──
    {
        "name": "generate_notes",
        "description": "为指定章节生成/重构笔记",
        "parameters": {
            "chapter_id": "章节 ID",
            "format": "可选，覆盖偏好中的 notes_format",
        }
    },
    {
        "name": "generate_quiz",
        "description": "生成练习题",
        "parameters": {
            "knowledge_point_ids": "目标知识点",
            "count": "题目数量",
            "difficulty": "easy | medium | hard",
            "types": "multiple_choice | fill_blank | short_answer",
        }
    },
    {
        "name": "generate_derived_problems",
        "description": "基于原题生成衍生题",
        "parameters": {
            "source_problem_id": "原题 ID",
            "mode": "similar | targeted_weakness",
        }
    },

    # ── 学习规划 ──
    {
        "name": "create_study_plan",
        "description": "生成学习计划",
        "parameters": {
            "mode": "daily | weekly | exam_prep",
            "exam_date": "考试日期（exam_prep 模式需要）",
            "exam_scope": "考试范围（章节列表）",
        }
    },

    # ── 知识图谱 ──
    {
        "name": "update_knowledge_graph",
        "description": "修改知识图谱（添加/删除节点或边）",
        "parameters": {
            "action": "add_node | remove_node | add_edge | remove_edge",
            "data": "操作数据",
        }
    },

    # ── 数据获取 ──
    {
        "name": "extract_problems_from_file",
        "description": "从上传文件中提取题目",
        "parameters": {
            "file_id": "文件 ID",
        }
    },
    {
        "name": "fetch_url_content",
        "description": "抓取 URL 内容并导入",
        "parameters": {
            "url": "目标 URL",
        }
    },

    # ── 查询操作 ──
    {
        "name": "get_weak_points",
        "description": "获取当前课程的薄弱知识点",
        "parameters": {
            "course_id": "课程 ID",
            "threshold": "掌握度阈值，默认 60",
        }
    },
    {
        "name": "get_due_reviews",
        "description": "获取今日待复习的内容",
        "parameters": {}
    },
]
```

### 7.2 工具执行架构

```python
class ToolExecutor:
    """
    接收 LLM 的 tool_calls，执行对应操作，返回结果。
    """

    def __init__(self):
        self.handlers = {
            "update_preference": self.preference_engine.update,
            "set_layout_preset": self.layout_manager.set_preset,
            "generate_notes": self.note_generator.generate,
            "generate_quiz": self.quiz_generator.generate,
            "create_study_plan": self.plan_generator.create,
            # ...
        }

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        handler = self.handlers.get(tool_call.name)
        if not handler:
            return ToolResult(error=f"Unknown tool: {tool_call.name}")

        try:
            result = await handler(**tool_call.arguments)
            return ToolResult(
                tool_name=tool_call.name,
                success=True,
                data=result,
                # 前端需要知道如何响应
                frontend_action=self._determine_frontend_action(tool_call.name, result)
            )
        except Exception as e:
            return ToolResult(error=str(e))

    def _determine_frontend_action(self, tool_name: str, result) -> dict:
        """
        告诉前端应该做什么响应。
        """
        ACTION_MAP = {
            "update_preference": {"type": "toast", "message": "偏好已更新"},
            "set_layout_preset": {"type": "layout_change", "preset": result},
            "generate_notes": {"type": "render_tab", "tab": "notes", "content": result},
            "generate_quiz": {"type": "render_tab", "tab": "quiz", "content": result},
            "create_study_plan": {"type": "render_tab", "tab": "plan", "content": result},
        }
        return ACTION_MAP.get(tool_name, {"type": "none"})
```

---

## 八、子系统 7：对话后处理流水线（Post-Conversation Pipeline）

### 8.1 流水线概览

```
对话结束（session close 或超时）
    │
    ▼
┌─────────────────────────────────────────────┐
│  EverMemOS 编码阶段（异步执行）               │
│                                             │
│  ┌─────────────────────┐                    │
│  │ Task 1: 摘要提取     │                    │
│  │ 大模型提取对话摘要   │──→ conversation_   │
│  │                     │    memories 表     │
│  └─────────────────────┘                    │
│                                             │
│  ┌─────────────────────┐                    │
│  │ Task 2: 偏好信号提取  │                    │
│  │ 小模型异步分析       │──→ preference_     │
│  │ 95% 返回 NONE       │    signals 表      │
│  └─────────────────────┘                    │
│                                             │
│  ┌─────────────────────┐                    │
│  │ Task 3: 学习表现更新  │                    │
│  │ 统计本次做题结果     │──→ knowledge_      │
│  │                     │    mastery 表      │
│  └─────────────────────┘                    │
│                                             │
└─────────────────────────────────────────────┘
```

### 8.2 实现

```python
class PostConversationPipeline:
    """
    对话结束后的异步处理流水线。
    三个任务并发执行，互不依赖。
    """

    async def process(self, session: ChatSession):
        conversation = await self.session_store.get_messages(session.id)

        # 三个任务并发执行
        await asyncio.gather(
            self._extract_summary(session, conversation),
            self._extract_preference_signals(session, conversation),
            self._update_learning_performance(session, conversation),
        )

    async def _extract_summary(self, session, conversation):
        """Task 1: 对话摘要提取"""
        summary_prompt = """
        提取这段对话的核心摘要（2-3句话）：
        - 讨论了什么主题
        - 用户遇到了什么问题
        - 得到了什么结论

        对话内容：{conversation}
        """
        summary = await litellm.completion(model="gpt-4o", ...)
        embedding = await self.embedder.embed(summary)

        memory = ConversationMemory(
            session_id=session.id,
            user_id=session.user_id,
            summary=summary,
            embedding=embedding,
            created_at=datetime.now(),
        )
        await self.memory_store.save(memory)

    async def _extract_preference_signals(self, session, conversation):
        """Task 2: 偏好信号提取（小模型，低成本）"""
        # 见 4.3 节的 extract_preference_signals 实现
        ...

    async def _update_learning_performance(self, session, conversation):
        """Task 3: 学习表现更新"""
        # 扫描对话中的做题记录
        practice_events = self._find_practice_events(conversation)

        for event in practice_events:
            await self.mastery_tracker.update_after_practice(
                user_id=session.user_id,
                problem_id=event.problem_id,
                is_correct=event.is_correct,
                knowledge_point_ids=event.knowledge_points,
            )
```

### 8.3 巩固阶段（定期异步任务）

```python
class ConsolidationScheduler:
    """
    定期执行的巩固任务（APScheduler / Celery Beat）。
    """

    # 每 6 小时执行一次
    async def consolidate_preference_signals(self):
        """跨对话合并偏好信号"""
        users = await self.user_store.get_all_active()

        for user in users:
            signals = await self.signal_store.get_pending(user.id)

            # 按维度分组
            by_dimension = group_by(signals, key=lambda s: s.dimension)

            for dimension, dim_signals in by_dimension.items():
                confidence = calculate_confidence(dim_signals)

                if confidence >= CONFIRMATION_THRESHOLD:
                    # 达到阈值 → 标记为"待确认"
                    # 下次用户上线时弹窗确认
                    await self.notification_store.create(
                        user_id=user.id,
                        type="preference_confirmation",
                        data={
                            "dimension": dimension,
                            "suggested_value": most_common_value(dim_signals),
                            "confidence": confidence,
                            "evidence": [s.evidence for s in dim_signals[:3]],
                        }
                    )

    # 每天凌晨执行
    async def apply_fsrs_decay(self):
        """FSRS 遗忘曲线衰退"""
        users = await self.user_store.get_all_active()
        for user in users:
            courses = await self.course_store.get_by_user(user.id)
            for course in courses:
                await self.mastery_tracker.apply_fsrs_decay(user.id, course.id)
```

---

## 九、核心数据模型（Agent 相关）

```python
# ── 偏好相关 ──

@dataclass
class UserPreference:
    """已确认的偏好"""
    id: str
    user_id: str
    dimension: str           # notes_format, detail_level, ...
    value: str               # bullet_summary, concise, ...
    scope: str               # global | course | course_scene | global_scene | temporary
    course_id: str | None
    scene_type: str | None
    source: str              # onboarding | explicit | confirmed | template
    confidence: float        # 0.0 - 1.0
    created_at: datetime
    updated_at: datetime
    superseded_by: str | None  # 被哪条新偏好覆盖


@dataclass
class PreferenceSignal:
    """待确认的偏好信号"""
    id: str
    user_id: str
    dimension: str
    value: str
    evidence: str            # 用户原话或行为描述
    signal_type: str         # explicit | behavioral | pattern
    base_score: float        # 0.3 | 0.5 | 0.7
    session_id: str          # 来源 session
    created_at: datetime
    status: str              # pending | confirmed | rejected | superseded


# ── 学习记忆相关 ──

@dataclass
class KnowledgeMastery:
    """知识点掌握度"""
    id: str
    user_id: str
    knowledge_point_id: str
    course_id: str
    level: float             # 0-100
    base_level: float        # 上次做对时的 level（用于 FSRS 衰退计算）
    total_attempts: int
    correct_attempts: int
    last_practiced: datetime | None
    error_categories: dict   # {concept_confusion: 3, calculation_error: 1, ...}


@dataclass
class WrongAnswer:
    """错题记录"""
    id: str
    user_id: str
    problem_id: str
    user_answer: str
    correct_answer: str
    knowledge_point_ids: list[str]
    error_category: str
    error_analysis: str      # AI 生成的错因分析
    created_at: datetime
    reviewed_count: int      # 复习次数
    mastered: bool           # 用户标记为"已掌握"


@dataclass
class FSRSCard:
    """FSRS 间隔复习卡片"""
    id: str
    user_id: str
    problem_id: str
    knowledge_point_ids: list[str]
    difficulty: float
    stability: float
    retrievability: float
    state: int               # New(0) | Learning(1) | Review(2) | Relearning(3)
    next_review: datetime
    last_review: datetime
    review_count: int


# ── 对话记忆 ──

@dataclass
class ConversationMemory:
    """对话记忆（摘要 + 向量）"""
    id: str
    user_id: str
    session_id: str
    summary: str
    embedding: list[float]   # pgvector
    created_at: datetime
    evidence_refs: list[str] # 关联的 session_id 列表


# ── 场景上下文 ──

@dataclass
class SceneContext:
    """前端传入的当前场景"""
    tab_type: str
    course_id: str
    content_snapshot: str
    metadata: dict
```

---

## 十、Agent 入口（主调用流程）

```python
class ZenusAgent:
    """
    Zenus Agent 主入口。
    每次用户发消息时调用 handle_message。
    """

    def __init__(self):
        self.context_assembler = ContextAssembler()
        self.tool_executor = ToolExecutor()
        self.post_pipeline = PostConversationPipeline()
        self.llm = LiteLLM()

    async def handle_message(
        self,
        user_message: str,
        user_id: str,
        project_id: str,
        session_id: str,
        scene: SceneContext,
    ) -> AgentResponse:
        """
        Agent 主循环：
        1. 组装上下文
        2. LLM 推理
        3. 执行工具调用（如有）
        4. 返回结果
        """

        # Step 1: 上下文组装
        prompt = await self.context_assembler.assemble(
            user_message=user_message,
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            scene=scene,
        )

        # Step 2: LLM 推理（流式）
        response = await self.llm.completion(
            model=self._select_model(scene),  # 根据场景选择模型
            messages=prompt.messages,
            system=prompt.system_message,
            tools=prompt.tools,
            stream=True,
        )

        # Step 3: 处理 tool calls
        tool_results = []
        if response.tool_calls:
            for tool_call in response.tool_calls:
                result = await self.tool_executor.execute(tool_call)
                tool_results.append(result)

            # 如果有 tool call，可能需要再调用一次 LLM 生成最终回复
            if self._needs_followup(tool_results):
                response = await self._followup_call(
                    prompt, response, tool_results
                )

        # Step 4: 保存对话记录
        await self.session_store.save_turn(
            session_id=session_id,
            user_message=user_message,
            assistant_message=response.content,
            tool_calls=response.tool_calls,
            tool_results=tool_results,
        )

        return AgentResponse(
            text=response.content,
            tool_results=tool_results,
            frontend_actions=[r.frontend_action for r in tool_results if r.frontend_action],
        )

    async def end_session(self, session_id: str):
        """
        对话结束时触发后处理流水线。
        """
        session = await self.session_store.get(session_id)
        # 异步执行，不阻塞用户
        asyncio.create_task(self.post_pipeline.process(session))
```

---

## 十一、关键技术决策摘要

| 决策点 | 选择 | 理由 |
|-------|------|------|
| 意图分类方式 | LLM 自分类（Prompt 内） | 省一次调用，主模型有完整上下文做判断 |
| 偏好衰退策略 | 行为覆盖（非时间衰退） | 用户习惯不会因为时间消退，只会被新习惯替代 |
| 学习记忆衰退 | FSRS 遗忘曲线 | 知识确实会随时间遗忘，FSRS 比 SM-2 精确 30%+ |
| 检索融合方式 | RRF (k=60) | 简单高效，无需训练权重 |
| 双轨 LLM 执行 | 对话后异步并发 | 不影响用户体验，小模型成本低 |
| 偏好存储分层 | signals + preferences 两表 | 区分"AI 推测"和"用户确认"，避免误更新 |
| context window 管理 | 固定预算 + 优先级截断 | 保证关键信息（场景+偏好）永不丢失 |
| 知识图谱构建 | LLM 提取 + DAG | 比纯统计方法更准确，支持依赖关系推理 |

---

## 十二、模块依赖图

```
                 ┌─────────────┐
                 │ ZenusAgent  │ (主入口)
                 └──────┬──────┘
                        │
         ┌──────────────┼──────────────┐
         │              │              │
         ▼              ▼              ▼
┌────────────┐ ┌──────────────┐ ┌───────────┐
│  Context   │ │    Tool      │ │   Post    │
│  Assembler │ │   Executor   │ │  Pipeline │
└─────┬──────┘ └──────┬───────┘ └─────┬─────┘
      │               │               │
      ├───────────┐    │    ┌──────────┤
      │           │    │    │          │
      ▼           ▼    ▼    ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│Preference│ │Retrieval │ │   Learning   │
│ Engine   │ │ Engine   │ │   Memory     │
│          │ │          │ │              │
│ ·cascade │ │ ·PageIdx │ │ ·mastery     │
│ ·signals │ │ ·pgvec   │ │ ·FSRS        │
│ ·confirm │ │ ·RRF     │ │ ·graph       │
│          │ │          │ │ ·error_anal  │
└──────────┘ └──────────┘ └──────────────┘
      │           │               │
      └───────────┴───────┬───────┘
                          │
                          ▼
                  ┌──────────────┐
                  │  PostgreSQL  │
                  │  + pgvector  │
                  │  + Redis     │
                  └──────────────┘
```

---

*基于 Opentutor/Zenus 功能拆解 v2 文档设计*
*Agent Core Architecture v1.0*
