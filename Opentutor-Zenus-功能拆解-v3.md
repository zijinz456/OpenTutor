# Opentutor / Zenus — 完整功能拆解 v3


---

## 一、项目定位（更新版）

**一句话**：给我任何学习材料，我帮你变成一个属于你的、越用越懂你的个性化学习网站。

**产品形态**：本地部署 + Web前端界面（类OpenClaw），用户自备LLM API Key，完全开源。

**核心差异化**：
1. 不是聊天机器人，而是生成一个**交互式学习工作台**
2. 双记忆系统：偏好记忆（交互习惯）+ 学习记忆（知识掌握）
3. 模版市场降低门槛，自然语言微调提供灵活性
4. AI完全感知当前页面上下文，做题/笔记/问答一体化
5. **场景感知切换**：同一项目内可在日常学习/考试复习/写作业等场景间流畅切换，AI行为随场景自适应

---

## 二、全局布局系统（类VS Code）

### 2.1 四区布局

```
┌──────────┬─────────────────────────────────────────┬──────────────┐
│          │ [📚日常学习 ▾]  Tab1: 笔记  │  Tab2: 做题  │              │
│  左侧栏   │─────────────────────────────────────────│   右侧栏      │
│  项目列表  │                                         │  当前对话全文   │
│          │        主内容区域（多Tab + 可分屏）         │  + 历史session │
│          │                                         │   切换列表     │
│          │                                         │              │
├──────────┴─────────────────────────────────────────┴──────────────┤
│                     下方：AI聊天输入窗口（只发送）                     │
└────────────────────────────────────────────────────────────────────┘
```

> **v3新增**：Tab栏左侧增加场景选择器（Segmented Control / Dropdown），显示当前活跃场景。

### 2.2 各区域详细定义

| 区域 | 内容 | 交互方式 | 内置逻辑 |
|------|------|---------|---------|
| **左侧栏** | 项目列表（课程+子项目树） | 点击展开/折叠，右键操作菜单 | 默认按课程分组，用户可自由创建/重组 |
| **主内容区** | 多Tab页面，每个Tab是一种学习视图 | Tab切换 + 可拖拽分屏（类VS Code split） | AI生成的内容渲染在此，AI可感知当前Tab |
| **场景选择器** | 当前场景名称 + 切换入口 | 点击展开场景列表，选择即切换 | 切换时联动Tab组合、布局、AI workflow |
| **右侧栏** | 当前对话完整内容 + 历史session选择器 | 上方下拉箭头切换历史session，下方显示当前对话全文 | 每个项目/Tab的对话独立存储 |
| **下方输入** | AI聊天输入框 | 发送消息，支持@引用、拖拽文件 | 只是输入入口，完整对话显示在右侧栏 |

### 2.3 Tab系统

**前端表现**：
- 顶部Tab栏，可拖拽排序
- 支持分屏：拖拽Tab到左/右侧可创建分屏（类VS Code split editor）
- 每个Tab有类型标识icon

**内置逻辑**：
- Tab类型由模版定义或用户创建
- 每个Tab有独立的状态和数据源
- AI聊天时自动注入当前活跃Tab的上下文
- **场景切换时：Tab组合自动调整（详见模块9）**

**预设Tab类型**：

| Tab类型 | 功能 | 数据源 |
|---------|------|--------|
| 笔记 (Notes) | AI重构的课件笔记 | course_content_tree + 偏好 |
| 做题 (Quiz) | 交互式答题界面 | practice_problems |
| 学习计划 (Plan) | 日程/deadline/study plan | assignments + calendar |
| 知识图谱 (Graph) | 知识点依赖关系可视化 | knowledge_graph |
| 错题回顾 (Review) | FSRS驱动的间隔复习 | wrong_answers + fsrs_cards |
| 考试模式 (Exam) | 轻量计时做题 | practice_problems + timer |
| 作业引导 (Assignment) | 步骤化作业辅助 | assignment + knowledge_points |
| 自定义 (Custom) | 用户通过AI对话生成的自定义Tab | AI生成的React组件 |

---

## 三、模块拆解（9大模块 + 子模块）

---

### 模块1: 数据获取与解析

#### 1.1 文件上传

**前端表现**：
- 拖拽上传区域（支持多文件）
- 上传进度条 + 解析状态（SSE实时推送）
- 支持格式：PDF / PPTX / DOCX / 图片 / HTML / TXT

**内置逻辑**：
```
用户拖拽文件 → MIME检测 → SHA-256去重
  → 已存在？提示"已有相同文件"
  → 不存在？→ 内容提取（Marker/python-pptx/等）
    → 文件名正则预分析（"CS101_lecture_05.pdf" → 自动归类）
    → 如果用户指定了课程 → 跳过课程分类
    → 如果未指定 → LLM分类（课程 + 文件类型）
    → 存入 ingestion_jobs 表（状态机：pending → processing → success/failed）
    → 分发到业务表（lecture → content_tree，exam → calendar，assignment → tasks）
```

#### 1.2 URL抓取

**前端表现**：
- 输入框粘贴URL
- 或在AI对话中说"帮我去这个链接抓内容"

**内置逻辑**：
```
URL输入 → 三层降级抓取：
  1. trafilatura（免费、毫秒级）→ 大部分教授网站够用
  2. Firecrawl（付费、能绕反爬）→ trafilatura失败时
  3. browser-use（重、能处理JS渲染/登录）→ 最后手段
→ 抓取内容 → Markdown → 进入与文件上传相同的分类流水线
```

#### 1.3 LMS自动抓取（Canvas为主）

**前端表现**：
- 设置页面配置Canvas URL和登录方式
- 同步状态面板：最后同步时间、下次同步时间、同步日志
- Session过期时 → 通知用户重新登录（Toast/通知）

**内置逻辑**：
```
方式A: Chrome扩展（Phase 2）
  → Manifest V3，运行在Canvas页面
  → Canvas REST API + session cookies
  → 结构化数据（作业/日历/公告）→ 直接入库，不走LLM
  → 课程文件（PDF/PPT）→ 只分类file_type

方式B: Browser Use（通用方案）
  → 用户首次登录 → browser-use记录session
  → 定时任务（APScheduler）→ 检查session有效性
  → session有效 → 自动抓取新内容
  → session过期 → 发送通知要求重新登录
  → 抓取内容 → 进入统一分类流水线
```

#### 1.4 统一分类流水线

**内置逻辑（7步）**：
```
Step 0: 预处理
  ├── SHA-256 去重
  ├── 文件名正则预分析
  └── 预指定课程 → 跳过课程分类

Step 1: MIME 检测（python-magic）
Step 2: 内容提取（Marker/python-pptx/BeautifulSoup/多模态LLM）
Step 3: LLM 分类 → course_id + file_type
Step 4: 课程模糊匹配（thefuzz库）
Step 5: 存储到 ingestion_jobs
Step 6: 分发到业务表
  ├── lecture_slides / textbook → PageIndex树索引 → course_content_tree
  ├── exam_schedule → 提取日期 → calendar
  ├── assignment → 作业信息 → assignments表
  ├── syllabus → 课程结构提取
  └── practice_problems → 题目拆分 → practice_problems表
Step 7: 前端SSE通知完成
```

---

### 模块2: 笔记系统

#### 2.1 AI笔记重构

**前端表现（Notes Tab）**：
- 左侧：章节导航树（course_content_tree）
- 右侧：AI重构后的笔记内容
- 支持的渲染格式：
  - Markdown文本（bullet point / 段落）
  - Mermaid.js（思维导图/流程图/时序图）
  - KaTeX（数学公式）
  - 表格对比
  - 步骤图
- 工具栏：格式切换按钮 + "用AI重构"按钮

**内置逻辑**：
```
课件内容 + 用户偏好 + 当前场景偏好 → System Prompt注入
→ AI选择最合适的展示形式（或用户指定）
→ 生成重构后的笔记
→ 用户可在右侧栏对话中说：
  - "太长了" → AI识别为偏好反馈 → 更新偏好 → 重新生成
  - "这个概念什么意思" → AI识别为学习提问 → 引用课件回答

场景对笔记的影响（v3新增）：
  → study_session场景：笔记偏向完整理解，默认适中详细度
  → exam_prep场景：笔记自动切换为"精简要点+公式速查"模式
  → assignment_guide场景：笔记聚焦于作业相关章节，高亮关键定义
```

#### 2.2 自动可视化

**内置逻辑**：
```
AI分析内容类型：
  → 对比关系 → 表格
  → 流程/步骤 → Mermaid flowchart
  → 层级结构 → 思维导图
  → 数学推导 → KaTeX公式
  → 时间线 → 时序图
  → 默认 → bullet point文本
可视化格式写入System Prompt的工具说明 → AI自动选择
```

#### 2.3 章节导航

**前端表现**：
- 树形侧边栏，展示content_tree层级
- 点击节点 → 右侧跳转到对应章节
- 搜索框快速定位

**内置逻辑**：
- PageIndex的md_to_tree()构建层级树
- 每个节点：{title, node_id, start_index, end_index, summary, children}

---

### 模块3: 做题系统

#### 3.1 题目提取

**内置逻辑**：
```
PDF/课件内容 → LLM structured output
→ 识别题型（单选/多选/填空/简答）
→ 拆分为独立题目
→ 提取：题目文本、选项（如有）、参考答案（如有）、所属知识点
→ 存入 practice_problems 表
```

#### 3.2 交互式答题（Quiz Tab）

**前端表现**：
- **一题一题模式**：
  - 顶部：进度条（第3/20题）
  - 中间：题目内容（支持图片/公式）
  - 下方：答题区域
    - 单选/多选：点选选项卡片
    - 填空：输入框
    - 简答：文本编辑器（支持highlight、加思考笔记）
  - 提交按钮 → 显示答案 + AI解析
  - AI解析引用课件原文，标注知识点

**内置逻辑**：
```
用户作答 → 提交
→ 对比参考答案（如有）
→ AI评判 + 生成解析（引用course_content_tree）
→ 记录结果到 practice_results
→ 错题自动标记 → wrong_answers表
→ AI分析错因 → 标记薄弱知识点

场景对做题的影响（v3新增）：
  → study_session场景：每题做完即时反馈+详细解析
  → exam_prep场景：默认进入计时模式，题目优先从薄弱点出
  → assignment_guide场景：题目筛选为作业相关知识点
```

#### 3.3 轻量计时模式（Exam Tab）

**前端表现**：
- 顶部右上角：倒计时器（用户设定时长）
- 题号导航条（可跳题）
- 做完后统一显示成绩和逐题解析
- 无特殊限制（可切Tab、可看笔记——轻量模式）

**内置逻辑**：
```
用户选择题目集 + 设定时间 → 开始计时
→ 做题过程记录每题耗时
→ 时间到或手动交卷 → 统一评判
→ 生成成绩报告：正确率、耗时分布、薄弱知识点
→ 错题进入wrong_answers
```

#### 3.4 衍生题生成

**前端表现**：
- 在题目解析页面的操作按钮："生成类似题" / "针对薄弱点出题"
- 或在AI对话中说"给我出几道类似的题"

**内置逻辑**：
```
分析原题：
  → 识别知识点（knowledge_point_ids）
  → 识别出题模式（题型、难度、考察角度）

衍生模式A: 纯相似衍生
  → 保持相同知识点 + 相同出题模式，变换数据/场景

衍生模式B: 针对性衍生
  → 根据用户薄弱知识点（从wrong_answers分析）
  → 保持相似出题模式
  → 替换为用户不熟练的知识点

→ LLM生成新题 → 存入practice_problems（标记source=derived）
```

#### 3.5 自定义题型（混合模式）

**前端表现**：
- 常见题型用预设组件（选择、填空、简答）
- 用户可在AI对话中描述想要的题型
- AI生成React组件代码 → 前端实时渲染

**内置逻辑**：
```
预设组件库：
  - MultipleChoice（单选/多选）
  - FillInBlank
  - ShortAnswer
  - TrueFalse

自定义流程：
  用户对AI说"我想要一个配对题"
  → AI生成React组件代码（含答题逻辑）
  → 前端沙箱环境渲染
  → 如果用户满意 → 保存为自定义组件，可复用
```

---

### 模块4: AI对话系统

#### 4.1 上下文感知对话

**前端表现**：
- 下方输入框发送消息
- 右侧栏显示完整对话流
- 支持@引用（@这道题 / @这段笔记）
- 支持拖拽文件/截图到输入框

**内置逻辑**：
```
每次发送消息时，自动注入上下文：
  1. 当前活跃Tab类型和内容
  2. 如果是Notes Tab → 注入当前查看的章节
  3. 如果是Quiz Tab → 注入当前题目和用户的答案
  4. 如果是Plan Tab → 注入当前学习计划
  5. 用户偏好（从偏好引擎resolve后注入System Prompt）
  6. 相关课件内容（PageIndex树搜索RAG）
  7. 对话历史（pgvector向量检索相关记忆）
  8. 当前活跃场景 + 场景级行为规则（v3新增）
```

#### 4.2 意图分类（v3扩展为四类）

**内置逻辑（AI自动判断）**：
```
用户消息 → AI自动判断意图类别：

类别A: 偏好反馈
  特征词："太长了"/"换成表格"/"笔记放大"/"我更喜欢..."
  → 更新偏好 → 重新生成内容 → 确认Toast
  → 偏好信号写入 preference_signals

类别B: 学习提问
  特征词：关于学科内容的问题
  → RAG检索课件 → 引用原文回答
  → 记录到对话记忆

类别C: 操作指令
  特征词："帮我生成..."/"出几道题"/"做个学习计划"
  → 触发对应工作流 → 生成内容到对应Tab

类别D: 场景切换信号（v3新增）
  特征词：涉及学习目标/模式变化的表达
  → 详见模块9

判断方式：System Prompt中明确四类意图的定义和示例
→ AI根据上下文自动分类
→ 不需要用户显式标记
```

#### 4.3 课件RAG（混合检索）

**内置逻辑**：
```
用户提问 → 同时走两条检索路径：

路径1: PageIndex树搜索（课程内容）
  → LLM推理导航content_tree → 精准定位章节
  → 准确率98.7%

路径2: pgvector向量检索（对话记忆）
  → 向量相似度检索历史对话 → 补充上下文

合并：RRF融合排名 score = 1/(60+rank)
→ Top-K结果注入LLM上下文
→ 回答中标注引用来源 [Chapter 3.2]
```

#### 4.4 对话历史管理

**前端表现**：
- 右侧栏上方：历史session列表（下拉选择）
- 每个session有自动生成的标题和时间
- 可搜索历史对话内容

**内置逻辑**：
```
每个session绑定：user_id + project_id + 当前Tab上下文 + active_scene（v3新增）
→ 对话结束后 → EverMemOS编码阶段：
  1. 摘要提取 → conversation_memories表
  2. 偏好信号提取（双轨LLM，默认不提取）→ preference_signals
  3. 证据绑定：每条记忆追溯到 session_id + 日期
  4. 场景切换信号提取 → 更新scene_switch_log（v3新增）
```

---

### 模块5: 偏好系统（交互习惯记忆）

#### 5.1 偏好三步走

**Step 1: Onboarding选项初始化**

**前端表现**：
- 首次使用的引导向导（3-5步）
- 每步一个问题，卡片式选择
- 可跳过

**内置逻辑**：
```
问题列表：
  1. 笔记格式偏好：bullet point / 思维导图 / 表格 / 详细段落
  2. 详细程度：精简 / 适中 / 详细
  3. 语言偏好：中文 / 英文 / 中英混合
  4. 布局偏好：展示3个预设布局缩略图
  5. "我有例子"：用户可上传自己喜欢的笔记样本（可跳过）

→ 结果写入 user_preferences (scope=global, source=onboarding)
```

**Step 2: 自然语言微调**

**前端表现**：
- 在AI对话中直接说自然语言
- 执行后Toast确认："已将笔记格式更新为表格"

**内置逻辑**：
```
用户说"太长了" / "换成思维导图" / "笔记放大"
→ AI识别为偏好反馈（意图分类）
→ 映射到具体操作：
  - 布局相关："笔记放大" → set_layout_preset("notesFocused")
  - 格式相关："换成思维导图" → update_preference(notes_format, "mindmap")
  - 内容相关："太详细了" → update_preference(detail_level, "concise")
→ 更新偏好 → 立即重新渲染
→ 模糊表达时返回选项追问
```

**Step 3: 行为自动学习**

**前端表现**：
- 学习结束后的偏好确认弹窗（shadcn Dialog）
- 展示AI检测到的偏好变化
- 三个按钮："长期习惯" / "这门课专属" / "不改"

**内置逻辑**：
```
每次对话后 → 双轨LLM提取（openakita Compiler模式）：
  - 大模型处理对话（正常回复）
  - 小模型异步提取偏好信号（95%返回NONE，低成本）

信号类型：
  - 显式表达 (base_score=0.7)："我喜欢bullet point"
  - 修改行为 (base_score=0.5)：用户编辑AI输出后反馈
  - 行为模式 (base_score=0.3)：多次选择某种格式

→ 信号存入 preference_signals
→ 置信度计算：confidence = base × frequency × consistency
→ 达到阈值 → 学习结束后弹窗确认
→ 用户选择 → 写入 user_preferences (scope对应选择)
```

#### 5.2 偏好解析引擎（cascade）

**内置逻辑**：
```
resolvePreference(user_id, course_id, scene_type, dimension):
  1. 检查 临时偏好 (temporary)        → 有则返回
  2. 检查 课程场景偏好 (course_scene)  → 有则返回
  3. 检查 课程偏好 (course)            → 有则返回
  4. 检查 全局场景偏好 (global_scene)  → 有则返回
  5. 检查 全局偏好 (global)            → 有则返回
  6. 检查 模板偏好 (template)          → 有则返回
  7. 返回 系统默认偏好 (system_default)

→ 解析后的偏好JSON注入System Prompt
→ 影响：笔记格式、详细程度、语言、布局、可视化方式

v3补充 — scene_type的实际取值：
  → "study_session"  — 日常学习
  → "exam_prep"      — 考试复习
  → "assignment"     — 写作业
  → "review_drill"   — 错题专练
  → "note_organize"  — 笔记整理
  → 自定义场景名（用户可自建）

v3补充 — 场景偏好示例：
  同一个用户、同一门课：
  → study_session 场景下 notes_format = "detailed_paragraph"
  → exam_prep 场景下 notes_format = "bullet_summary"
  → 切换场景 → cascade自动解析到不同值 → 笔记自动变
```

#### 5.3 偏好"衰退"机制

**关键决策**：偏好基本不做时间衰退，而是做**行为覆盖**。

**内置逻辑**：
```
偏好不按时间衰退，而是通过以下机制更新：

1. 新行为覆盖：
   - 用户之前偏好bullet point
   - 最近3次都要求表格
   → 新信号置信度累积，自然超过旧偏好
   → 旧偏好的frequency_factor不再增长

2. 矛盾信号处理：
   - consistency_factor = 1.0 - contradiction_rate
   - 矛盾越多 → 旧偏好置信度下降
   → 触发确认弹窗："你之前喜欢bullet point，最近更常用表格，要更新吗？"

3. 低置信度推断清理：
   - source=behavior（AI推断的）且 confidence<0.3
   → 从未被用户确认过
   → 标记为"待确认"，不再主动应用

4. 用户主动重置：
   - 设置页面可查看/编辑所有偏好
   - 可一键重置某个维度
```

---

### 模块6: 学习记忆系统（知识掌握记忆）

#### 6.1 错题记录与分析

**前端表现（Review Tab）**：
- 错题列表，按知识点/课程/时间分组
- 每道错题：原题 + 你的答案 + 正确答案 + AI错因分析
- 操作按钮："重做" / "生成类似题" / "标记已掌握"

**内置逻辑**：
```
做题错误 → 记录到 wrong_answers表：
  {problem_id, user_answer, correct_answer,
   knowledge_points, error_analysis, created_at}

AI错因分析：
  → 分析用户答案 vs 正确答案
  → 归类错因：概念混淆 / 计算错误 / 审题不清 / 知识缺失
  → 标记对应薄弱知识点
  → 更新 knowledge_mastery 表中该知识点的掌握程度
```

#### 6.2 间隔重复（FSRS算法）

**前端表现**：
- Review Tab中的"今日复习"板块
- 显示今天需要复习的题目数量
- 复习完成后的掌握度变化图表

**内置逻辑**：
```
FSRS算法（比SM-2精确30%+）：
  → 每道错题创建一张FSRS卡片
  → 卡片属性：difficulty, stability, retrievability
  → 用户复习后评分（Again/Hard/Good/Easy）
  → 算法计算下次复习时间
  → retrievability = exp(-t/stability) ← 遗忘曲线

学习记忆衰退 = FSRS的遗忘曲线
  → 主动推送复习提醒
  → 复习后重置stability
  → 重复正确 → stability增长 → 复习间隔拉长
```

#### 6.3 知识图谱

**前端表现（Graph Tab）**：
- 可视化知识点依赖关系图（力导向图 / 树形图）
- 节点颜色表示掌握程度（红/黄/绿）
- 点击节点 → 显示相关笔记/题目/错题
- 用户可在AI对话中提意见修改图谱

**内置逻辑**：
```
构建流程：
  1. AI分析课程内容 → 提取知识点列表
  2. AI分析知识点间依赖关系 → 构建DAG
  3. 存入 knowledge_graph 表：
     {node_id, name, course_id, prerequisites[], mastery_level}
  4. 用户可通过对话修改："A不应该依赖B" → AI更新图谱

掌握程度计算：
  → 综合该知识点下所有做题正确率
  → 加权FSRS的retrievability
  → 输出 0-100 的mastery_level
```

#### 6.4 薄弱点追踪

**内置逻辑**：
```
持续追踪每个知识点的mastery_level：
  → 做题对了 → mastery上升
  → 做题错了 → mastery下降 + 记录错因
  → 长时间未复习 → FSRS衰退 → mastery自然下降

薄弱点判定：
  → mastery_level < 60 的知识点
  → 且有依赖它的其他知识点（图谱中的后继节点）
  → 优先推荐复习

用于：
  → 考前复习计划的比重分配
  → 衍生题的知识点选择
  → 学习建议的优先级
```

---

### 模块7: 学习规划系统

#### 7.1 自动Study Plan生成

**前端表现（Plan Tab）**：
- 日历视图 + 任务列表
- 每个任务：名称、截止时间、预估耗时、优先级
- 拖拽调整计划
- 颜色标注：红(紧急) / 黄(中等) / 绿(充裕)

**内置逻辑**：
```
输入：
  → assignments表（截止时间、科目）
  → 考试日程
  → 用户的空闲时间（可配置）
  → 每项任务的预估耗时（AI估算或用户修改）

算法：
  → 约束调度：基于截止日期 + 预估时间 + 可用时间
  → 优先级：deadline近 + 分值高 + 掌握度低 → 优先
  → 知识点依赖关系：需要先学A再学B → A排在B前面
  → 生成每日学习计划
```

#### 7.2 考前复习计划

**前端表现**：
- 考试日期和范围确认页
- AI分析后生成的复习计划：按天分配，每天有具体知识点
- 每个知识点旁显示掌握度颜色
- 完成复习后打勾，触发该单元的测验

**内置逻辑**：
```
输入：
  → 考试日期 + 考试范围（用户指定或AI从syllabus分析）
  → 历史试卷分析 → 各单元考试比重
  → 用户各知识点mastery_level
  → 知识点依赖关系图

输出：
  1. 按比重 + 薄弱程度分配复习时间
     → 比重高 + mastery低 → 分配最多时间
     → 比重高 + mastery高 → 适量复习
     → 比重低 + mastery高 → 可跳过
  2. 尊重知识点依赖顺序
     → 先复习基础知识点，再复习依赖它的高级知识点
  3. 每个单元复习完 → 按考试题型出测验题
     → 题型参考历史试卷分析的出题模式
```

#### 7.3 作业引导（Assignment Tab）

**前端表现**：
- 上方：步骤进度条（Step 1/5）
- 中间：当前步骤的知识点卡片 + 引导提示
- 下方：AI对话辅助
- AI不直接给答案，而是引导思路

**内置逻辑**：
```
Agent分析assignment要求 → 拆解为步骤：
  1. 识别需要的知识点
  2. 检查用户对这些知识点的掌握度
  3. 对于薄弱知识点 → 先提供简要复习
  4. 逐步引导完成每一步
     → 给出思路框架，不直接给答案
     → 用户卡住时给渐进式提示（Hint 1 → Hint 2 → 更详细）
  5. 记录用户的薄弱项
     → 更新knowledge_mastery
```

#### 7.4 每周准备

**内置逻辑**：
```
每周初自动生成：
  1. 获取本周截止的assignments
  2. 获取本周的课程安排
  3. 获取需要复习的FSRS卡片
  4. 根据偏好生成本周学习计划
  5. 推送通知/放在Plan Tab首页
```

---

### 模块8: 模版市场系统

#### 8.1 模版定义

**模版包含的完整内容**：

```yaml
# 模版 Manifest
name: "考前冲刺"
version: "1.0.0"
description: "一键生成考前复习工作台"
author: "official"
tags: ["exam", "review"]
preview_image: "preview.png"

# 场景定义（v3新增）
scene: "exam_prep"   # 该模版对应的场景标识

# 布局定义
layout:
  type: "split-horizontal"
  panels:
    - type: "notes"        # 左侧：笔记
      width: 40%
    - type: "quiz"          # 右侧上：做题
      width: 60%

# 默认Tab配置
tabs:
  - type: "notes"
    config: { format: "bullet_summary", detail: "concise" }
  - type: "quiz"
    config: { mode: "timed", source: "weak_points" }
  - type: "review"
    config: { algorithm: "fsrs", focus: "recent_errors" }
  - type: "plan"
    config: { mode: "exam_prep" }

# AI逻辑/工作流
workflow: "exam_prep"
prompts:
  system: "你正在帮助学生进行考前复习。重点关注薄弱知识点..."

# 默认偏好
preferences:
  notes_format: "bullet_summary"
  detail_level: "concise"
  quiz_focus: "weak_points"

# 前端组件组合
components:
  - "notes_panel"
  - "quiz_panel"
  - "review_panel"
  - "exam_timer"
  - "knowledge_heatmap"
```

#### 8.2 模版市场

**前端表现**：
- 首次进入 / 创建新项目时弹出
- 卡片网格展示可用模版
- 每个卡片：预览图 + 名称 + 描述 + 标签
- 点击"使用"→ 一键生成完整工作空间
- 也可选"空白项目"从零开始

**预设模版**：

| 模版名 | 描述 | 场景标识 | 包含Tab | 核心工作流 |
|--------|------|---------|---------|-----------|
| 日常学习 | 通用学习空间 | study_session | 笔记+做题+对话 | study_session |
| 考前冲刺 | 考试复习专用 | exam_prep | 笔记+做题+复习+计划 | exam_prep |
| 作业助手 | assignment辅助 | assignment | 作业引导+笔记+对话 | assignment_guide |
| 错题专练 | 错题复习+衍生 | review_drill | 错题回顾+做题 | review_drill |
| 笔记整理 | 纯笔记重构 | note_organize | 笔记+知识图谱 | note_organize |

#### 8.3 模版可修改性

**核心理念**：模版只是起点，一切都可以改。

**前端表现**：
- 使用模版后，所有部分都可通过AI对话修改
- "帮我把布局换成全屏笔记模式" → 立即执行
- "加一个计时做题的Tab" → 添加新Tab
- "删掉知识图谱，我用不到" → 隐藏Tab
- 设置页面可手动调整每个配置项

**内置逻辑**：
```
模版应用 → 初始化项目配置
→ 配置存入 project_config 表
→ 用户任何修改 → 更新 project_config
→ 不影响原始模版
→ 用户也可以"另存为新模版"分享到市场
```

---

### 模块9: 场景切换系统（v3新增）

> **核心理念**：场景 = 模版的运行时投影。模版在项目创建时应用一次，场景在项目生命周期内可以反复切换。切换场景不丢失任何数据，只改变"看数据的视角"和"AI的行为模式"。

#### 9.1 场景定义

每个场景是以下五个维度的一组预设值：

```
Scene = {
  scene_id:       string,       // "exam_prep"
  display_name:   string,       // "考前冲刺"
  icon:           string,       // "🎯"
  tab_preset:     TabConfig[],  // 该场景下默认显示哪些Tab、什么布局
  workflow:       string,       // AI工作流标识（决定System Prompt行为段）
  ai_behavior:    AIBehavior,   // AI在该场景下的行为规则
  preferences:    Partial<Pref> // 该场景的默认偏好覆盖
}
```

**预设场景清单**：

| 场景 | Tab组合 | AI工作流 | AI行为重点 | 偏好覆盖 |
|------|---------|---------|-----------|---------|
| 📚 日常学习 (study_session) | 笔记 + 做题 | study_session | 完整讲解、鼓励探索、每题即时反馈 | notes_format: 适中详细 |
| 🎯 考前冲刺 (exam_prep) | 笔记 + 做题 + 复习 + 计划 | exam_prep | 精简要点、薄弱优先、计时模式、生成复习计划 | notes_format: bullet_summary, quiz_focus: weak_points |
| ✍️ 写作业 (assignment) | 作业引导 + 笔记 | assignment_guide | 引导不给答案、渐进提示、聚焦相关章节 | detail_level: 按需展开 |
| 🔄 错题专练 (review_drill) | 错题回顾 + 做题 | review_drill | 错因分析、衍生题、间隔复习 | quiz_source: wrong_answers |
| 📝 笔记整理 (note_organize) | 笔记 + 知识图谱 | note_organize | 结构优化、跨章节整合、可视化建议 | notes_format: 用户偏好优先 |

#### 9.2 显式切换（用户主动）

**前端表现**：

```
场景选择器位于Tab栏最左侧：

┌─────────────────────────────────────────────────────────────┐
│ [📚 日常学习 ▾]   Tab1: 笔记  │  Tab2: 做题  │  + 新Tab     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  点击展开下拉：                                               │
│  ┌─────────────────────────┐                                │
│  │ 📚 日常学习      ← 当前  │                                │
│  │ 🎯 考前冲刺              │                                │
│  │ ✍️ 写作业               │                                │
│  │ 🔄 错题专练              │                                │
│  │ 📝 笔记整理              │                                │
│  │ ────────────────────    │                                │
│  │ ＋ 自定义场景...          │                                │
│  └─────────────────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

**切换时的过渡动画**：
- Tab栏平滑变化（旧Tab淡出、新Tab淡入）
- 场景选择器icon和颜色变化
- 右侧栏显示："已切换到「考前冲刺」模式"

#### 9.3 隐式切换（AI建议）

**内置逻辑**：

```
AI在对话中检测场景切换信号 → 意图分类D:

触发条件（任一满足即触发建议）：

1. 显式表达目标变化：
   → "我下周有考试" / "我要开始复习了"
   → "这个assignment怎么写" / "帮我做作业"
   → "我想把错题过一遍"
   → AI检测到关键词 + 语义分析

2. 行为模式推断：
   → 连续3+次请求都是做题且正确率较低 → 可能需要切到review_drill
   → 用户上传了assignment PDF + 开始问相关问题 → 可能需要切到assignment
   → 用户开始密集查看错题 → 可能需要切到review_drill
   → 用户设置了考试日期 → 可能需要切到exam_prep

3. 时间触发推断：
   → 距某门课考试<7天 且 用户打开了该课程 → 建议切到exam_prep
   → 某个assignment截止日期<3天 → 建议切到assignment

AI的建议方式（非强制）：
  → AI在回复中自然地提出建议：
     "看起来你在准备考试，要切换到「考前冲刺」模式吗？
      我会帮你生成复习计划、重点整理薄弱知识点。"
  → 回复末尾附带快捷按钮：[切换到考前冲刺] [保持当前]
  → 用户确认 → 执行切换
  → 用户拒绝 → AI记住这次拒绝，短期内不再建议同一切换
```

#### 9.4 切换执行逻辑

**内置逻辑**：

```
switchScene(project_id, new_scene_id):

  Step 1: 保存当前场景状态（快照）
    → scene_snapshots表：
      {project_id, scene_id, open_tabs, tab_states, scroll_positions, ...}
    → 目的：切回来的时候恢复原样

  Step 2: 加载目标场景配置
    → 优先级：
      a. 该项目对该场景的历史快照（如果曾经切到过）→ 恢复上次离开时的状态
      b. 该场景的模版默认配置（首次进入该场景）→ 应用模版预设

  Step 3: 执行Tab组合切换
    → 关闭不属于新场景的Tab（但不销毁数据，只是隐藏）
    → 打开新场景需要的Tab（如果已有则激活，没有则创建）
    → 恢复布局（面板宽度、分屏方式）

  Step 4: 切换AI工作流
    → 更新 project_config.active_scene = new_scene_id
    → 更新 System Prompt 中的 workflow 段
    → 更新 scene_type 参数 → 偏好cascade自动重新resolve

  Step 5: 触发场景初始化动作（首次进入时）
    → exam_prep: 自动分析薄弱点 + 生成复习计划草稿
    → assignment: 自动分析assignment要求 + 拆解步骤
    → review_drill: 自动加载到期的FSRS卡片
    → study_session / note_organize: 无额外动作

  Step 6: 前端通知
    → Toast："已切换到「考前冲刺」模式"
    → 场景选择器更新
    → 对话session标记场景变更
```

#### 9.5 场景感知的AI行为差异

```
同一个问题"帮我总结第3章"，AI在不同场景下的行为：

[study_session]
  → 生成完整的、结构化的笔记
  → 包含详细解释、例子、可视化
  → 鼓励追问："有什么不理解的可以继续问我"

[exam_prep]
  → 生成精简的考点速查卡片
  → 标注高频考点（如果有历史试卷数据）
  → 标注薄弱知识点（红色高亮）
  → 自动追问："要不要针对薄弱点做几道题？"

[assignment]
  → 只总结与当前作业相关的部分
  → 高亮作业需要用到的定义和公式
  → 不主动展开无关内容

实现方式：
  → System Prompt中注入场景行为规则段：
    "当前场景：exam_prep
     行为要求：
     - 笔记优先使用精简格式
     - 所有内容标注考试相关度
     - 主动识别薄弱知识点并建议练习
     - 出题时优先选择高频考点+薄弱知识点"
```

#### 9.6 场景间数据共享

```
关键原则：所有场景共享同一份底层数据，只是视图和行为不同。

共享的数据（场景切换不影响）：
  → course_content_tree（课件内容）
  → practice_problems（题库）
  → wrong_answers（错题记录）
  → knowledge_mastery（掌握度）
  → knowledge_graph（知识图谱）
  → fsrs_cards（复习卡片）
  → conversation_memories（对话历史）

场景独立的数据：
  → scene_snapshots（每个场景的UI状态快照）
  → 对话session按场景标记（可按场景筛选历史对话）
  → 场景级偏好（scope=course_scene / global_scene）

这意味着：
  → 在study_session中做题做错了 → 切到exam_prep时错题自动出现在复习列表
  → 在exam_prep中更新了掌握度 → 切回study_session时知识图谱颜色已更新
  → 在assignment中发现知识盲区 → 切到review_drill时该知识点已被标记为薄弱
```

#### 9.7 自定义场景

**前端表现**：
- 场景选择器底部的"＋ 自定义场景"入口
- 弹窗配置：场景名称、icon、Tab组合、AI行为描述
- 或通过AI对话创建："帮我建一个专门做past paper的场景"

**内置逻辑**：
```
用户创建自定义场景：
  → 方式A：UI配置
    → 选择Tab组合
    → 选择或输入AI行为规则
    → 存入 scenes 表

  → 方式B：AI对话创建
    → "帮我建一个Past Paper练习场景"
    → AI推断所需Tab组合（Exam + Review）
    → AI生成行为规则（"模拟真实考试环境，做完才看解析"）
    → 确认后存入

  → 自定义场景也可以"另存为模版"分享到模版市场
```

---

## 四、记忆系统总架构

### 两大记忆体系对比

| 维度 | 偏好记忆（交互习惯） | 学习记忆（知识掌握） |
|------|---------------------|---------------------|
| **存什么** | 笔记格式、详细程度、语言、布局偏好 | 错题、薄弱知识点、掌握度、学习进度 |
| **怎么收集** | 三步走（onboarding/NL微调/行为学习） | 做题结果、FSRS评分、AI分析 |
| **衰退方式** | 不按时间衰退，被新行为覆盖 | FSRS遗忘曲线，exp(-t/stability) |
| **存储位置** | user_preferences + preference_signals | wrong_answers + knowledge_mastery + fsrs_cards |
| **检索方式** | 7层cascade解析（含场景维度）→ System Prompt注入 | FSRS算法决定复习时间，知识图谱定位薄弱点 |
| **影响范围** | AI的输出格式、布局、表达风格 | 学习计划、出题选择、复习安排 |
| **场景交互（v3）** | 不同场景下可有不同偏好（scope=course_scene） | 所有场景共享，场景切换时数据无缝衔接 |

### EverMemOS三阶段流水线

```
编码阶段（对话结束后）
├── 对话摘要提取 → conversation_memories表
├── 偏好信号提取（双轨LLM）→ preference_signals表
├── 学习表现提取 → 更新knowledge_mastery
└── 场景切换信号提取 → scene_switch_log（v3新增）

巩固阶段（异步/定期）
├── 跨对话合并：相同偏好信号去重+强化
├── 偏好：新行为覆盖旧偏好（非时间衰退）
├── 学习：FSRS更新retrievability
└── 场景使用统计：统计各场景使用频率，优化AI建议时机（v3新增）

检索阶段（对话/内容生成时）
├── 课程内容：PageIndex树形推理搜索
├── 对话记忆：pgvector向量检索
├── 偏好：cascade解析（含active_scene参数）→ System Prompt注入
├── 学习状态：knowledge_mastery → 影响出题和计划
└── 场景上下文：active_scene → 影响AI行为模式和System Prompt（v3新增）
```

---

## 五、数据库表设计概览

| 表名 | 用途 | 模块 |
|------|------|------|
| users | 用户信息 | 基础 |
| projects | 项目（课程+自由项目）| 布局 |
| project_config | 项目配置（含 active_scene 字段）| 模版 + 场景 |
| courses | 课程元数据 | 数据获取 |
| course_content_tree | 课件内容层级树 | 笔记 |
| practice_problems | 题目库 | 做题 |
| practice_results | 做题结果记录 | 做题 |
| wrong_answers | 错题记录+错因 | 学习记忆 |
| fsrs_cards | FSRS间隔复习卡片 | 学习记忆 |
| knowledge_graph | 知识点+依赖关系 | 知识图谱 |
| knowledge_mastery | 每个知识点的掌握度 | 学习记忆 |
| user_preferences | 已确认的偏好 | 偏好系统 |
| preference_signals | 偏好信号（待确认）| 偏好系统 |
| conversation_memories | 对话记忆+摘要 | 记忆系统 |
| assignments | 作业/考试日程 | 学习规划 |
| study_plans | 生成的学习计划 | 学习规划 |
| ingestion_jobs | 数据获取任务追踪 | 数据获取 |
| templates | 模版定义 | 模版市场 |
| chat_sessions | 对话session管理 | AI对话 |
| **scenes** | **场景定义（预设+自定义）** | **场景切换（v3）** |
| **scene_snapshots** | **每个场景的UI状态快照** | **场景切换（v3）** |
| **scene_switch_log** | **场景切换历史记录** | **场景切换（v3）** |

### v3新增表结构详解

```sql
-- 场景定义表
CREATE TABLE scenes (
  id            UUID PRIMARY KEY,
  scene_id      VARCHAR(50) UNIQUE NOT NULL,  -- "exam_prep"
  display_name  VARCHAR(100) NOT NULL,         -- "考前冲刺"
  icon          VARCHAR(10),                   -- "🎯"
  is_preset     BOOLEAN DEFAULT false,         -- 预设/自定义
  tab_preset    JSONB NOT NULL,                -- Tab组合配置
  workflow      VARCHAR(50) NOT NULL,          -- AI工作流标识
  ai_behavior   JSONB NOT NULL,                -- AI行为规则
  preferences   JSONB,                         -- 场景默认偏好覆盖
  created_by    UUID REFERENCES users(id),     -- 自定义场景的创建者
  created_at    TIMESTAMP DEFAULT NOW()
);

-- 场景UI状态快照
CREATE TABLE scene_snapshots (
  id            UUID PRIMARY KEY,
  project_id    UUID REFERENCES projects(id),
  scene_id      VARCHAR(50) REFERENCES scenes(scene_id),
  open_tabs     JSONB NOT NULL,    -- [{type, config, position}]
  layout_state  JSONB NOT NULL,    -- 面板宽度、分屏方式
  scroll_positions JSONB,          -- 各Tab的滚动位置
  last_active_tab  VARCHAR(50),    -- 上次活跃的Tab
  updated_at    TIMESTAMP DEFAULT NOW(),
  UNIQUE(project_id, scene_id)
);

-- 场景切换日志
CREATE TABLE scene_switch_log (
  id            UUID PRIMARY KEY,
  project_id    UUID REFERENCES projects(id),
  user_id       UUID REFERENCES users(id),
  from_scene    VARCHAR(50),
  to_scene      VARCHAR(50),
  trigger_type  VARCHAR(20) NOT NULL,  -- "manual" / "ai_suggested" / "auto"
  trigger_context TEXT,                -- 触发原因描述
  created_at    TIMESTAMP DEFAULT NOW()
);

-- project_config 新增字段
ALTER TABLE project_config ADD COLUMN active_scene VARCHAR(50)
  REFERENCES scenes(scene_id) DEFAULT 'study_session';
```

---

## 六、AI意图判断的完整逻辑（v3更新）

这是系统的核心智能——AI在同一个聊天窗口中精准区分用户意图。

```
用户发送消息 → System Prompt中已注入：
  - 当前Tab类型和内容
  - 用户偏好
  - 当前活跃场景 + 场景行为规则（v3新增）
  - 四类意图定义和示例（v3: 新增类别D）

AI判断意图 →

[偏好反馈]
  ↓ 关键特征：涉及格式/样式/布局/详略/表达方式的变化
  ↓ 例："太长了" / "换成表格" / "字大一点" / "以后都用英文"
  → AI执行偏好更新
  → 如果是布局相关 → tool call更新布局
  → 如果是内容格式相关 → 更新偏好 → 重新渲染笔记/题目
  → Toast确认 + 偏好信号写入

[学习提问]
  ↓ 关键特征：关于学科知识/概念的疑问
  ↓ 例："什么是微分方程" / "这道题为什么选A" / "帮我解释一下这个概念"
  → RAG检索课件内容
  → 引用原文回答（回答风格受当前场景影响）
  → 如果是因为笔记总结过度导致不理解：
    → AI判断 → 这不是学习问题，是偏好问题（"总结太多了"）
    → 更新该知识点的偏好为"保留更多细节"
    → 这个判断本身也写入偏好记忆

[操作指令]
  ↓ 关键特征：要求AI执行某个动作
  ↓ 例："帮我出5道选择题" / "做个复习计划" / "把这个PDF的题拆出来"
  → 触发对应工作流
  → 结果渲染到对应Tab

[场景切换信号]（v3新增）
  ↓ 关键特征：学习目标/模式发生变化
  ↓ 例："我要开始复习了" / "帮我准备考试" / "这个作业怎么做"
  → AI识别为场景切换信号
  → 判断目标场景
  → 生成切换建议（非强制）：
    "看起来你要开始准备考试了，要切换到「考前冲刺」模式吗？"
    [切换] [保持当前]
  → 用户确认 → 执行 switchScene()
  → 用户拒绝 → 记录拒绝，继续当前场景
```

**关键场景：用户说"这个概念没看懂"**

```
AI需要判断原因：
  Case 1: 概念本身就难 → 学习提问 → 详细解释
  Case 2: 是因为笔记太简略了 → 偏好反馈
    → 怎么判断？检查当前笔记的detail_level
    → 如果是"concise"模式 → 可能是太简略
    → AI追问："是这个概念本身不理解，还是我的笔记总结得太简略了？"
    → 用户回答 → AI对应处理
    → 如果确认是太简略 → 更新该章节/课程的detail_level偏好
```

**关键场景：意图分类的边界情况（v3新增）**

```
"帮我出几道题练一下"
  → 在 study_session 场景下 → 操作指令（随机出题）
  → 在 exam_prep 场景下 → 操作指令（优先出薄弱点+高频考点）
  → 场景不改变意图类别，但改变执行策略

"我下周有个考试"
  → 可能同时是：场景切换信号 + 操作指令（生成复习计划）
  → AI先建议场景切换 → 切换后自动触发考前复习计划生成
  → 这是"场景切换 + 工作流联动"的典型例子

"这个作业不会"
  → 如果当前不在assignment场景 → 场景切换信号
  → 如果已在assignment场景 → 学习提问（请求帮助）
```

---

## 七、技术栈确认

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Next.js + shadcn/ui + Tailwind | UI框架 |
| | Zustand | 状态管理（含场景状态管理） |
| | react-resizable-panels | 分屏布局 |
| | assistant-ui | AI对话面板 |
| | Mermaid.js + KaTeX | 可视化渲染 |
| | Vercel AI SDK | 流式对话 |
| **后端** | Python FastAPI | API服务 |
| | LangGraph | 工作流引擎（每个场景一个workflow） |
| | SQLAlchemy + Alembic | ORM + 迁移 |
| **数据** | PostgreSQL + pgvector | 结构化 + 向量检索 |
| | Redis | 缓存（含场景快照缓存） |
| **AI** | LiteLLM | 多模型统一接口 |
| | PageIndex | 课件内容树索引+推理检索 |
| | py-fsrs | 间隔重复算法 |
| **解析** | Marker | PDF → Markdown |
| | trafilatura | URL内容抓取 |
| | python-pptx | PPTX解析 |
| **部署** | Docker Compose | 本地部署 |

---

## 八、与旧文档的关键变化对照

| 变化点 | v2 | v3（本次更新） |
|--------|--------|---------|
| **布局** | 四区布局（类VS Code） | 四区布局 + Tab栏左侧增加场景选择器 |
| **场景切换** | 未设计 | 完整的场景切换系统（显式+隐式+混合） |
| **模版 vs 场景** | 模版是创建时一次性选择 | 模版是起点，场景是运行时可反复切换的模式 |
| **AI意图分类** | 三类（偏好/学习/操作） | 四类（新增场景切换信号） |
| **AI行为差异** | 未按场景区分 | 同一问题在不同场景下AI回答风格和策略不同 |
| **偏好cascade** | 有scene_type参数但无前端触发 | scene_type由active_scene驱动，前端场景选择器联动 |
| **数据库** | 19张表 | 22张表（新增scenes/scene_snapshots/scene_switch_log） |
| **场景状态保持** | 无 | 场景快照机制：切出时保存UI状态，切回时恢复 |
| **模版市场** | 5个预设 | 5个预设，每个绑定scene标识，支持自定义场景 |

---

## 九、场景切换完整用户流程示例

### 示例1：日常学习 → 考前冲刺

```
1. 用户正在"日常学习"模式下看CS101的笔记
2. 用户在对话中说："下周二有期中考试"

3. AI检测到场景切换信号：
   → 关键词"期中考试" + 时间"下周二"
   → 目标场景：exam_prep

4. AI回复：
   "下周二的期中考试，还有5天时间。
    要切换到「考前冲刺」模式吗？我会帮你：
    - 生成按天分配的复习计划
    - 整理薄弱知识点速查卡
    - 按考试题型出模拟题
    [🎯 切换到考前冲刺] [保持当前]"

5. 用户点击 [切换到考前冲刺]

6. 系统执行 switchScene("exam_prep"):
   → 保存当前状态快照（Notes Tab在第3章，滚动位置等）
   → Tab栏变化：笔记 + 做题 → 笔记 + 做题 + 复习 + 计划
   → 笔记Tab自动切换为"精简要点"模式
   → Plan Tab自动生成5天复习计划草稿
   → 场景选择器从"📚 日常学习"变为"🎯 考前冲刺"
   → Toast："已切换到「考前冲刺」模式"

7. 考试结束后，用户点击场景选择器 → 选回"📚 日常学习"
   → 恢复之前的快照：Notes Tab回到第3章，原来的滚动位置
```

### 示例2：日常学习 → 写作业

```
1. 用户上传了一个PDF："CS101_HW3.pdf"
2. 系统分类流水线识别为 assignment → 存入 assignments 表

3. AI检测到新assignment：
   → 结合当前场景（study_session）
   → 建议："刚收到CS101的第3次作业，截止日期是下周五。
          要切换到「写作业」模式开始做吗？
          [✍️ 开始写作业] [稍后再说]"

4. 用户点击 [开始写作业]

5. 系统执行 switchScene("assignment"):
   → Tab变化：笔记 + 做题 → 作业引导 + 笔记
   → Assignment Tab自动加载HW3，拆解为步骤
   → 笔记Tab自动聚焦到HW3涉及的章节
   → AI行为切换：引导模式，不直接给答案

6. 作业做完后，用户对AI说"作业写完了"
   → AI："作业完成了！要切回「日常学习」继续看后面的内容吗？
          [📚 切回日常学习] [保持当前]"
```

---

## 十、待进一步细化的问题

以下问题在后续开发阶段需要进一步讨论：

1. **AI生成React组件的沙箱安全性** — 用户自定义UI的代码执行边界
2. **模版市场的审核机制** — 社区贡献的模版如何保证质量
3. **多人协作** — 是否支持共享学习空间（当前设计为单用户）
4. **移动端适配** — 四区布局在手机上的响应式方案
5. **离线支持** — 本地部署后断网时的功能降级
6. **LLM成本优化** — 各功能的模型选择和调用频率控制
7. **数据导入导出** — 与Anki/Notion/其他工具的互通
8. **场景切换的AI建议频率控制** — 避免过于频繁地打断用户（v3新增）
9. **跨项目场景同步** — 多门课同时进入考前冲刺时的统一管理（v3新增）
10. **场景切换的撤销机制** — 误切换后的快速回退体验（v3新增）
