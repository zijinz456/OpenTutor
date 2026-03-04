# OpenTutor 改进路线图：从优秀技术原型到现象级产品

> 基于对整个代码库的深度调研，整理出的可执行改进方案。每个问题都附带了具体的文件路径、实现方案和工作量估算。

---

## 目录

1. [问题 1：安装门槛太高 — SQLite 轻量模式](#问题-1安装门槛太高--sqlite-轻量模式)
2. [问题 2：默认需要 API Key — Ollama 零配置方案](#问题-2默认需要-api-key--ollama-零配置方案)
3. [问题 3：首次体验链路太长 — Demo 数据 + 引导优化](#问题-3首次体验链路太长--demo-数据--引导优化)
4. [问题 4：移动端不可用 — 响应式改造](#问题-4移动端不可用--响应式改造)
5. [问题 5：缺少传播点 — 学习报告分享功能](#问题-5缺少传播点--学习报告分享功能)
6. [问题 6：一行命令启动 — 打包部署方案](#问题-6一行命令启动--打包部署方案)
7. [优先级排序与执行计划](#优先级排序与执行计划)

---

## 问题 1：安装门槛太高 — SQLite 轻量模式

### 现状

当前启动 OpenTutor 需要 4 个服务：PostgreSQL 17 + pgvector、Redis 7、FastAPI、Next.js。对非技术用户来说门槛过高。

### 调研结论

| 依赖 | 可替换性 | 替代方案 |
|------|----------|----------|
| PostgreSQL | 90% 可替换 | SQLite + aiosqlite |
| pgvector | 95% 可替换 | sqlite-vec 扩展 |
| Redis | 100% 可替换 | 已有轮询回退（0 工作量） |
| TSVECTOR 全文搜索 | 85% 可替换 | SQLite FTS5 模块 |

### PostgreSQL 专属特性清单（需要处理的）

#### 1.1 列类型迁移

| PG 类型 | 使用量 | SQLite 替代 | 改动难度 |
|---------|--------|-------------|----------|
| `UUID` | 35+ 个模型 | `TEXT` + Python `uuid4()` | 低 |
| `JSONB` | 25+ 列 | `TEXT` + JSON1 扩展 | 低 |
| `TSVECTOR` | 2 列（content, memory） | FTS5 虚拟表 | 中 |
| `Vector(1536)` | 2 列（content, memory） | sqlite-vec `float[1536]` | 中 |

#### 1.2 PG 专属 SQL 函数

| 函数 | 文件位置 | SQLite 替代 |
|------|----------|-------------|
| `plainto_tsquery()` | `services/search/hybrid.py:84-92` | FTS5 `MATCH` 查询 |
| `ts_rank_cd()` | `services/search/hybrid.py:173-179` | FTS5 `bm25()` 函数 |
| `to_tsvector()` + `setweight()` | `services/search/indexer.py:28-30` | FTS5 自动索引 |
| `cosine_distance()` | `services/search/hybrid.py:179` | `vec_distance_cos()` (sqlite-vec) |
| `gen_random_uuid()` | `alembic/versions/*.py` | Python `uuid.uuid4()` |
| `to_regclass()` | `services/migrations.py:77-78` | `sqlite_master` 表查询 |

#### 1.3 索引迁移

| PG 索引类型 | 位置 | SQLite 替代 |
|-------------|------|-------------|
| `postgresql_using="gin"` | `models/content.py:55`, `alembic/versions/*` | FTS5 自带索引 |
| `postgresql_where=` 条件索引 | `models/notification.py:46` | 去掉或用视图代替 |

### 具体实现方案

#### 方案 A：双数据库抽象层（推荐）

不删除 PostgreSQL 支持，而是创建一个数据库抽象层，根据配置自动选择 SQLite 或 PostgreSQL。

**Step 1：修改 `apps/api/database.py`**

```python
# 根据 DATABASE_URL 前缀自动选择驱动
if settings.database_url.startswith("sqlite"):
    engine = create_async_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_async_engine(settings.database_url)
```

**Step 2：创建 `apps/api/models/compat.py` — 类型兼容层**

```python
from sqlalchemy import Text, String
from sqlalchemy.engine import Engine

def get_uuid_type(engine: Engine):
    if engine.dialect.name == "sqlite":
        return String(36)  # UUID as TEXT
    from sqlalchemy.dialects.postgresql import UUID
    return UUID(as_uuid=True)

def get_json_type(engine: Engine):
    if engine.dialect.name == "sqlite":
        return Text  # JSON stored as TEXT
    from sqlalchemy.dialects.postgresql import JSONB
    return JSONB
```

**Step 3：修改搜索服务 `apps/api/services/search/hybrid.py`**

```python
async def keyword_search(self, query, ...):
    if self.engine.dialect.name == "sqlite":
        # FTS5 搜索
        stmt = text("SELECT rowid, rank FROM content_fts WHERE content_fts MATCH :query")
    else:
        # PostgreSQL TSVECTOR 搜索（现有代码）
        stmt = select(Content).where(Content.search_vector.match(query))
```

**Step 4：向量搜索兼容 `apps/api/services/search/hybrid.py`**

```python
async def vector_search(self, embedding, ...):
    if self.engine.dialect.name == "sqlite":
        # sqlite-vec 余弦距离
        stmt = text("""
            SELECT rowid, vec_distance_cos(embedding, :query_vec) as dist
            FROM content_vec ORDER BY dist LIMIT :k
        """)
    else:
        # pgvector 余弦距离（现有代码）
        stmt = select(Content).order_by(
            Content.embedding.cosine_distance(embedding)
        ).limit(k)
```

**Step 5：LangGraph Checkpoint 适配**

```python
# apps/api/services/workflow/checkpoint.py
if settings.database_url.startswith("sqlite"):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    saver = AsyncSqliteSaver.from_conn_string(settings.database_url)
else:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    saver = AsyncPostgresSaver.from_conn_string(pg_url)
```

**Step 6：配置默认值 `apps/api/config.py`**

```python
# 新增轻量模式默认值
database_url: str = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///~/.opentutor/data.db"  # 默认 SQLite
)
```

### Redis 替换（0 工作量）

Redis 已经是可选的，代码中有完善的回退机制：

- 文件：`apps/api/services/activity/redis_notify.py`
- 配置：`activity_use_redis_notify: bool = False`（默认关闭）
- 回退：数据库轮询（`POLL_INTERVAL_SECONDS = 1.0`）
- **结论：不需要任何改动，Redis 不装就不用**

### 工作量估算

| 任务 | 工时 |
|------|------|
| 数据库抽象层 + 类型兼容 | 16h |
| 搜索服务 SQLite 适配（FTS5 + sqlite-vec） | 24h |
| LangGraph Checkpoint 适配 | 8h |
| Alembic 迁移脚本适配 | 12h |
| 集成测试 + 回归测试 | 20h |
| **总计** | **~80h（2 周）** |

### 需要新增的依赖

```
aiosqlite>=0.20.0       # SQLite 异步驱动
sqlite-vec>=0.1.0       # 向量搜索扩展
```

---

## 问题 2：默认需要 API Key — Ollama 零配置方案

### 现状

- 默认 `llm_provider = "openai"`，需要 API Key
- Ollama 已支持但不是默认选项
- 无 API Key 时回退到 MockLLMClient（返回假响应）

### 调研发现的好消息

1. **Ollama 已集成**：通过 OpenAI 兼容 API（`/v1/chat/completions`），仅需改默认值
2. **嵌入已有本地回退**：`sentence-transformers/all-MiniLM-L6-v2`，无 API Key 也能生成向量
3. **健康检查已覆盖**：Ollama 有专门的 HTTP 探针检测（`/models`）
4. **熔断器已就位**：3 次失败自动切换到下一个提供商

### 需要的改动（极少量）

#### 2.1 改默认提供商（1 行）

```python
# apps/api/config.py:15
# 改前：
llm_provider: str = "openai"
# 改后：
llm_provider: str = "ollama"
```

#### 2.2 改默认模型

```python
# apps/api/config.py:16
# 改前：
llm_model: str = "gpt-4o-mini"
# 改后：
llm_model: str = "llama3.2:3b"  # 轻量本地模型
```

#### 2.3 Ollama 始终注册为回退（~10 行）

```python
# apps/api/services/llm/router.py，在 _build_registry() 中添加：

# 始终注册 Ollama 作为回退选项
ollama_client = OpenAIClient(
    "ollama", "llama3.2:3b",
    base_url=f"{settings.ollama_base_url}/v1",
    name="ollama"
)
registry.register("ollama", ollama_client,
    primary=(not any_cloud_provider_configured))
```

#### 2.4 前端设置页 Ollama 优先

```typescript
// apps/web/src/app/settings/page.tsx:33-45
// 改 PROVIDERS 数组顺序：
const PROVIDERS = ["ollama", "openai", "anthropic", "deepseek", ...] as const;

// 改 PROVIDER_META 默认值：
const PROVIDER_META = {
  ollama: { requiresKey: false, defaultModel: "llama3.2:3b" },
  openai: { requiresKey: true, defaultModel: "gpt-4o-mini" },
  // ...
} as const;
```

#### 2.5 首次启动自动检测 Ollama

```python
# apps/api/services/app_lifecycle.py，startup 中添加：
async def _detect_ollama():
    """首次启动时检测本地 Ollama 是否可用"""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if models:
                    logger.info(f"Detected Ollama with {len(models)} models")
                    return True
                else:
                    logger.info("Ollama running but no models pulled. "
                              "Run: ollama pull llama3.2:3b")
    except Exception:
        logger.info("Ollama not detected at localhost:11434")
    return False
```

### 工作量估算

| 任务 | 工时 |
|------|------|
| 后端配置默认值修改 | 2h |
| Router 注册逻辑调整 | 4h |
| 前端设置页调整 | 4h |
| Ollama 自动检测 + 提示 | 4h |
| 文档更新 | 2h |
| **总计** | **~16h（2 天）** |

---

## 问题 3：首次体验链路太长 — Demo 数据 + 引导优化

### 现状

- 有 5 个学习模板（STEM/人文/语言/视觉/速览）但不在 Onboarding 中展示
- 有 `APP_AUTO_SEED_SYSTEM` 配置，但默认关闭
- 没有示例课程数据（用户必须先上传资料才能体验）
- Onboarding 只设置偏好，没有交互式演示

### 解决方案

#### 3.1 内置 Demo 课程数据

创建一个「快速体验」课程包，首次启动自动加载：

```python
# apps/api/services/templates/demo_course.py（新文件）

DEMO_COURSE = {
    "title": "Python 入门 · 快速体验",
    "description": "3 分钟体验 OpenTutor 的核心功能",
    "contents": [
        {
            "title": "变量与数据类型",
            "type": "lecture",
            "content": "Python 支持多种数据类型：int, float, str, bool..."
        },
        {
            "title": "控制流：if/for/while",
            "type": "lecture",
            "content": "条件判断和循环是编程的基础..."
        }
    ],
    "flashcards": [
        {"front": "Python 中如何声明变量？", "back": "直接赋值：x = 10，不需要声明类型"},
        {"front": "list 和 tuple 的区别？", "back": "list 可变 []，tuple 不可变 ()"},
        # ... 10+ 张卡片
    ],
    "quiz_questions": [
        {
            "question": "以下哪个是合法的 Python 变量名？",
            "options": ["2name", "_name", "my-name", "class"],
            "correct": 1
        },
        # ... 5+ 道题
    ]
}

async def seed_demo_course(db: AsyncSession, user_id: str):
    """首次启动时自动创建 Demo 课程"""
    existing = await db.execute(
        select(Course).where(Course.title == DEMO_COURSE["title"])
    )
    if existing.scalar():
        return  # 已存在，跳过
    # 创建课程 + 内容 + 闪卡 + 题目
    ...
```

#### 3.2 改进 Onboarding 流程

```
当前流程（5 步）：
  语言 → 学习模式 → 详细度 → 布局 → 完成

改进流程（6 步）：
  语言 → 学习模式 → 详细度 → 布局 → 🆕 体验 Demo 课程 → 完成
```

新增的「体验 Demo 课程」步骤：
- 展示一个迷你聊天窗口，用户可以向 AI 提问
- 展示一张闪卡翻转动画
- 展示一道测验题
- 30 秒内让用户感受到产品核心价值

#### 3.3 启用自动 Seed

```python
# apps/api/config.py:71
# 改前：
app_auto_seed_system: bool = False
# 改后：
app_auto_seed_system: bool = True  # 默认启用
```

#### 3.4 「快速开始」模式 — 无需上传

在首页添加「快速开始」入口：

```typescript
// apps/web/src/app/page.tsx 中添加：
<Button onClick={() => router.push("/new?mode=topic")}>
  输入主题，AI 自动生成课程
</Button>
```

配套后端：

```python
# apps/api/routers/courses.py 新增端点
@router.post("/courses/from-topic")
async def create_course_from_topic(topic: str, db: AsyncSession):
    """根据主题名直接生成课程内容（无需上传文件）"""
    # 1. 用 LLM 生成课程大纲
    # 2. 用 LLM 生成每章节内容
    # 3. 自动生成闪卡和测验
    # 4. 返回课程 ID
```

### 工作量估算

| 任务 | 工时 |
|------|------|
| Demo 课程数据 + Seed 脚本 | 8h |
| Onboarding 体验步骤 | 12h |
| 「快速开始」无上传模式 | 16h |
| 默认启用 auto_seed | 1h |
| **总计** | **~37h（1 周）** |

---

## 问题 4：移动端不可用 — 响应式改造

### 现状

- VS Code 风格 3 面板布局（左树 + 中内容 + 下聊天）在手机上无法使用
- 部分页面有 `md:` `lg:` 断点但不完整
- 无移动端检测、无汉堡菜单、无触屏优化
- `html-to-image` 已安装但未使用

### 需要改造的核心文件

| 文件 | 问题 | 改造内容 |
|------|------|----------|
| `components/shell/app-shell.tsx` | 固定 3 面板，无移动适配 | 移动端切换为单面板 + Tab 导航 |
| `components/course-tree/` | 240px 固定宽度侧边栏 | 移动端抽屉式展开 |
| `components/chat/ChatInput.tsx` | 拖拽调整高度 | 移动端固定底部 |
| `components/sections/analytics/graph-view.tsx` | 固定 800x600 SVG | 响应式尺寸 |
| `app/analytics/page.tsx` | 网格布局未适配小屏 | 增加 `sm:` 断点 |

### 具体实现方案

#### 4.1 AppShell 响应式改造

```typescript
// apps/web/src/components/shell/app-shell.tsx

// 添加移动端检测 Hook
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return isMobile;
}

// 移动端布局：底部 Tab 导航 + 全屏单面板
{isMobile ? (
  <div className="flex flex-col h-screen">
    <div className="flex-1 overflow-auto">
      {activeTab === "chat" && <ChatPanel />}
      {activeTab === "notes" && <NotesSection />}
      {activeTab === "practice" && <PracticeSection />}
      {activeTab === "tree" && <CourseTree />}
    </div>
    <nav className="flex border-t bg-background">
      <TabButton icon={MessageSquare} label="Chat" tab="chat" />
      <TabButton icon={FileText} label="Notes" tab="notes" />
      <TabButton icon={Brain} label="Practice" tab="practice" />
      <TabButton icon={FolderTree} label="Files" tab="tree" />
    </nav>
  </div>
) : (
  // 桌面端：保持现有 3 面板布局
  <DesktopLayout />
)}
```

#### 4.2 课程树改为抽屉

```typescript
// 移动端使用 Sheet 组件（已有 shadcn/ui 的 Sheet）
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";

{isMobile && (
  <Sheet>
    <SheetTrigger asChild>
      <Button variant="ghost" size="icon"><Menu /></Button>
    </SheetTrigger>
    <SheetContent side="left" className="w-[300px]">
      <CourseTree />
    </SheetContent>
  </Sheet>
)}
```

#### 4.3 聊天面板移动端优化

```typescript
// 移动端：聊天占满屏幕，输入框固定底部
<div className="flex flex-col h-full">
  <div className="flex-1 overflow-y-auto">
    <MessageList />
  </div>
  <div className="sticky bottom-0 border-t bg-background p-2">
    <ChatInput />
  </div>
</div>
```

#### 4.4 图表响应式

```typescript
// analytics/graph-view.tsx
// 改前：固定 800x600
<svg width={800} height={600}>

// 改后：响应式
const containerRef = useRef<HTMLDivElement>(null);
const [dims, setDims] = useState({ w: 800, h: 600 });
useEffect(() => {
  if (containerRef.current) {
    const { width } = containerRef.current.getBoundingClientRect();
    setDims({ w: width, h: Math.min(width * 0.75, 600) });
  }
}, []);
<div ref={containerRef} className="w-full">
  <svg width={dims.w} height={dims.h}>
```

### 工作量估算

| 任务 | 工时 |
|------|------|
| AppShell 移动端布局 + Tab 导航 | 16h |
| CourseTree 抽屉模式 | 4h |
| ChatInput 移动端适配 | 4h |
| Analytics 页面响应式 | 8h |
| GraphView 响应式 | 4h |
| 闪卡/测验组件触屏适配 | 8h |
| 整体触屏手势优化 | 8h |
| 移动端测试（iOS Safari / Chrome） | 8h |
| **总计** | **~60h（1.5 周）** |

---

## 问题 5：缺少传播点 — 学习报告分享功能

### 现状

- 后端已有 `generate_daily_brief()` 和 `generate_weekly_report()` 能力
- 前端 Analytics 页面数据丰富（掌握率、学习时间、知识图谱）
- `html-to-image` 包已安装但**从未使用**
- 无分享链接、无社交分享按钮、无 PDF 导出

### 解决方案

#### 5.1 学习报告卡片生成

利用已安装的 `html-to-image` 生成可分享的学习报告图片：

```typescript
// apps/web/src/components/shared/ShareableReport.tsx（新文件）
import { toPng } from "html-to-image";

interface ReportData {
  courseName: string;
  masteryPercent: number;
  studyHours: number;
  quizAccuracy: number;
  streak: number;
  topConcepts: string[];
}

export function ShareableReport({ data }: { data: ReportData }) {
  const reportRef = useRef<HTMLDivElement>(null);

  const handleShare = async () => {
    if (!reportRef.current) return;
    const dataUrl = await toPng(reportRef.current, {
      width: 1200, height: 630,  // Open Graph 标准尺寸
      pixelRatio: 2
    });

    // 触发下载或分享
    if (navigator.share) {
      const blob = await (await fetch(dataUrl)).blob();
      const file = new File([blob], "learning-report.png", { type: "image/png" });
      await navigator.share({ title: "我的学习报告", files: [file] });
    } else {
      // 回退到下载
      const link = document.createElement("a");
      link.download = "learning-report.png";
      link.href = dataUrl;
      link.click();
    }
  };

  return (
    <>
      {/* 可视化报告卡片 */}
      <div ref={reportRef} className="bg-gradient-to-br from-blue-600 to-purple-700
        text-white p-8 rounded-2xl w-[600px]">
        <h2 className="text-2xl font-bold">📚 本周学习报告</h2>
        <p className="text-lg mt-2">{data.courseName}</p>

        <div className="grid grid-cols-2 gap-4 mt-6">
          <Stat label="掌握率" value={`${data.masteryPercent}%`} />
          <Stat label="学习时长" value={`${data.studyHours}h`} />
          <Stat label="测验正确率" value={`${data.quizAccuracy}%`} />
          <Stat label="连续学习" value={`${data.streak} 天`} />
        </div>

        <div className="mt-6 text-sm opacity-80">
          Powered by OpenTutor · opentutor.dev
        </div>
      </div>

      <Button onClick={handleShare} className="mt-4">
        <Share2 className="mr-2 h-4 w-4" /> 分享学习报告
      </Button>
    </>
  );
}
```

#### 5.2 后端报告 API 整合

```python
# apps/api/routers/export.py 新增端点
@router.get("/export/report/{course_id}")
async def get_shareable_report(course_id: str, period: str = "week"):
    """生成可分享的学习报告数据"""
    data = await report_generator.gather_report_data(course_id, days=7)
    return {
        "course_name": data["course_name"],
        "mastery_percent": data["mastery_avg"],
        "study_hours": data["total_hours"],
        "quiz_accuracy": data["accuracy"],
        "top_concepts": data["mastered_concepts"][:5],
        "streak": data["consecutive_days"],
        "generated_at": datetime.utcnow().isoformat()
    }
```

#### 5.3 知识图谱分享

```typescript
// 在 GraphView 中添加截图导出
import { toPng } from "html-to-image";

<Button onClick={async () => {
  const png = await toPng(graphContainer.current!);
  // 下载或分享
}}>
  导出知识图谱
</Button>
```

### 工作量估算

| 任务 | 工时 |
|------|------|
| ShareableReport 组件 | 8h |
| 报告数据 API | 4h |
| 知识图谱导出 | 4h |
| Web Share API 集成 | 4h |
| 报告样式设计 + 动画 | 8h |
| **总计** | **~28h（3-4 天）** |

---

## 问题 6：一行命令启动 — 打包部署方案

### 目标

```bash
# 目标体验
pip install opentutor
opentutor          # 自动打开浏览器
```

### 实现方案

#### 6.1 Python CLI 入口

```python
# opentutor/__main__.py（新文件）

import subprocess
import sys
import webbrowser
import time
from pathlib import Path

def main():
    """一行命令启动 OpenTutor"""
    data_dir = Path.home() / ".opentutor"
    data_dir.mkdir(exist_ok=True)

    # 设置默认环境变量
    env = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{data_dir}/data.db",
        "LLM_PROVIDER": "ollama",
        "LLM_MODEL": "llama3.2:3b",
        "DEPLOYMENT_MODE": "single_user",
        "APP_AUTO_CREATE_TABLES": "true",
        "APP_AUTO_SEED_SYSTEM": "true",
        **os.environ  # 用户自定义环境变量优先
    }

    # 启动后端
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(Path(__file__).parent / "api"),
        env=env
    )

    # 启动前端（预编译静态文件）
    web_proc = subprocess.Popen(
        ["node", "server.js"],
        cwd=str(Path(__file__).parent / "web"),
        env={**env, "PORT": "3000"}
    )

    # 等待服务就绪，然后打开浏览器
    time.sleep(3)
    webbrowser.open("http://localhost:3000")

    try:
        api_proc.wait()
    except KeyboardInterrupt:
        api_proc.terminate()
        web_proc.terminate()

if __name__ == "__main__":
    main()
```

#### 6.2 PyPI 打包

```toml
# pyproject.toml
[project]
name = "opentutor"
version = "0.1.0"
description = "Your local AI study buddy — private, adaptive, yours"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "aiosqlite>=0.20",
    "sqlite-vec>=0.1",
    # ... 其他核心依赖
]

[project.scripts]
opentutor = "opentutor.__main__:main"
```

#### 6.3 Next.js 预编译

```bash
# 构建时预编译前端为 standalone 输出
cd apps/web
npm run build  # output: standalone (next.config.ts 已配置)
# 产出 .next/standalone/server.js，直接 node 运行
```

#### 6.4 Homebrew 支持（未来）

```ruby
# Formula/opentutor.rb
class Opentutor < Formula
  desc "Local AI study buddy"
  homepage "https://github.com/xxx/opentutor"
  url "https://pypi.org/packages/opentutor-0.1.0.tar.gz"
  depends_on "python@3.11"
  depends_on "node@20"

  def install
    virtualenv_install_with_resources
  end
end
```

### 工作量估算

| 任务 | 工时 |
|------|------|
| CLI 入口 + 进程管理 | 12h |
| pyproject.toml 打包配置 | 4h |
| Next.js standalone 打包集成 | 8h |
| 依赖精简（去掉可选依赖） | 8h |
| 跨平台测试（macOS/Linux/Windows） | 12h |
| 文档 + README 更新 | 4h |
| **总计** | **~48h（1-1.5 周）** |

---

## 优先级排序与执行计划

### 按 ROI（投入产出比）排序

| 优先级 | 问题 | 工时 | 影响 | ROI |
|--------|------|------|------|-----|
| **P0** | 问题 2：Ollama 默认 | 16h | 去掉 API Key 依赖 | ★★★★★ |
| **P0** | 问题 3：Demo 数据 | 37h | 30 秒内感受价值 | ★★★★★ |
| **P1** | 问题 1：SQLite 模式 | 80h | 去掉 PG/Redis 依赖 | ★★★★☆ |
| **P1** | 问题 6：一行命令 | 48h | pip install 即用 | ★★★★☆ |
| **P2** | 问题 5：分享功能 | 28h | 增加传播性 | ★★★☆☆ |
| **P2** | 问题 4：移动端 | 60h | 覆盖移动用户 | ★★★☆☆ |

### 推荐执行顺序

```
Week 1-2:   P0 — Ollama 默认(16h) + Demo 数据(37h)
            ↓ 此时用户体验从 "需要配置" 变为 "打开就能用"
Week 3-4:   P1 — SQLite 模式(80h 的前 40h)
            ↓ 此时去掉 PostgreSQL 依赖
Week 5:     P1 — SQLite 完善(剩余 40h) + 一行命令(48h 的前 20h)
            ↓ 此时可以 pip install 了
Week 6:     P1 — 一行命令完善 + P2 分享功能(28h)
            ↓ 此时有传播点了
Week 7-8:   P2 — 移动端响应式(60h)
            ↓ 此时手机也能用了
```

### 里程碑检查点

| 时间 | 里程碑 | 验收标准 |
|------|--------|----------|
| Week 2 结束 | **v0.2: Zero-Config** | 安装 Ollama → `docker-compose up` → 30 秒内体验 Demo 课程 |
| Week 5 结束 | **v0.3: One-Line** | `pip install opentutor && opentutor` → 浏览器自动打开 |
| Week 6 结束 | **v0.4: Shareable** | 用户可以导出学习报告图片并分享 |
| Week 8 结束 | **v0.5: Mobile** | 手机浏览器可以正常使用核心功能 |

---

## 附录：关键文件速查表

| 改动类别 | 文件路径 |
|----------|----------|
| 数据库配置 | `apps/api/config.py`, `apps/api/database.py` |
| 数据模型 | `apps/api/models/*.py`（35+ 文件） |
| 搜索服务 | `apps/api/services/search/hybrid.py`, `indexer.py` |
| 向量搜索 | `apps/api/services/search/hybrid.py:152-197` |
| LLM 路由 | `apps/api/services/llm/router.py` |
| LLM 配置 | `apps/api/config.py:14-27` |
| Ollama 集成 | `apps/api/services/llm/router.py:831-836` |
| 嵌入服务 | `apps/api/services/embedding/registry.py`, `local.py` |
| 种子数据 | `apps/api/services/templates/system.py` |
| 生命周期 | `apps/api/services/app_lifecycle.py` |
| Onboarding | `apps/web/src/app/onboarding/page.tsx` |
| 设置页 | `apps/web/src/app/settings/page.tsx` |
| 主布局 | `apps/web/src/components/shell/app-shell.tsx` |
| 课程树 | `apps/web/src/components/course-tree/` |
| 聊天组件 | `apps/web/src/components/chat/` |
| 分析页 | `apps/web/src/app/analytics/page.tsx` |
| 图表组件 | `apps/web/src/components/sections/analytics/` |
| 导出路由 | `apps/api/routers/export.py` |
| 报告生成 | `apps/api/services/report/generator.py` |
| Redis（可选）| `apps/api/services/activity/redis_notify.py` |
| LangGraph | `apps/api/services/workflow/checkpoint.py` |
| Alembic | `apps/api/alembic/env.py`, `versions/*.py` |
