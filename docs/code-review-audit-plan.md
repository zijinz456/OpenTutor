# OpenTutor 项目代码审计方案

> 版本: v1.0 | 日期: 2026-03-12
> 目标: 系统性检测项目中的断链、死代码、逻辑错误、闭环缺失等问题

---

## 目录

1. [前后端 API 连通性审计](#1-前后端-api-连通性审计)
2. [死代码与孤立模块检测](#2-死代码与孤立模块检测)
3. [逻辑一致性审计](#3-逻辑一致性审计)
4. [数据流闭环验证](#4-数据流闭环验证)
5. [状态管理一致性](#5-状态管理一致性)
6. [错误处理链完整性](#6-错误处理链完整性)
7. [类型安全与契约一致性](#7-类型安全与契约一致性)
8. [数据库模型与迁移一致性](#8-数据库模型与迁移一致性)
9. [安全性审计](#9-安全性审计)
10. [性能瓶颈检测](#10-性能瓶颈检测)
11. [测试覆盖度审计](#11-测试覆盖度审计)
12. [配置与环境一致性](#12-配置与环境一致性)
13. [国际化完整性](#13-国际化完整性)
14. [可观测性与监控链路](#14-可观测性与监控链路)
15. [构建与部署链完整性](#15-构建与部署链完整性)

---

## 1. 前后端 API 连通性审计

### 1.1 目标
确保前端每个 API 调用都有对应的后端 endpoint，反之亦然（除内部接口外）。

### 1.2 检测方法

#### A. 自动化扫描: 前端 → 后端

```bash
# 步骤 1: 提取前端所有 API 路径
grep -rn "fetch\|request(" apps/web/src/lib/api/ \
  | grep -oP '`/[^`]+`|"/[^"]+"' \
  | sort -u > /tmp/frontend_endpoints.txt

# 步骤 2: 提取后端所有路由定义
grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" apps/api/routers/ \
  | grep -oP '"/[^"]*"' \
  | sort -u > /tmp/backend_endpoints.txt

# 步骤 3: 对比差异 (需手动匹配路径参数)
diff /tmp/frontend_endpoints.txt /tmp/backend_endpoints.txt
```

#### B. 逐模块对照表 (需人工核对)

| 前端 API 模块 | 前端调用路径 | 后端 Router 文件 | 后端 Endpoint | 状态 |
|---|---|---|---|---|
| `courses.ts` | `GET /courses/overview` | `courses_crud.py` | `@router.get("/overview")` | ? |
| `courses.ts` | `POST /courses/` | `courses_crud.py` | `@router.post("/")` | ? |
| `courses.ts` | `PATCH /courses/{id}` | `courses_crud.py` | `@router.patch("/{course_id}")` | ? |
| `courses.ts` | `DELETE /courses/{id}` | `courses_crud.py` | `@router.delete("/{course_id}")` | ? |
| `courses.ts` | `PATCH /courses/{id}/layout` | `courses_crud.py` | `@router.patch("/{course_id}/layout")` | ? |
| `courses.ts` | `GET /courses/{id}/content-tree` | `courses_crud.py` | `@router.get("/{course_id}/content-tree")` | ? |
| `courses.ts` | `POST /content/upload` | `upload.py` | `@router.post("/upload")` | ? |
| `courses.ts` | `POST /content/url` | `upload.py` | `@router.post("/url")` | ? |
| `courses.ts` | `GET /content/files/{jobId}` | `upload.py` | `@router.get("/files/{job_id}")` | ? |
| `courses.ts` | `GET /health` | `health.py` | `@router.get("/health")` | ? |
| `courses.ts` | `POST /notes/restructure` | `notes.py` | `@router.post("/restructure")` | ? |
| `courses.ts` | `POST /notes/generated/save` | `notes.py` | `@router.post("/generated/save")` | ? |
| `courses.ts` | `GET /notes/generated/{courseId}` | `notes.py` | `@router.get("/generated/{course_id}")` | ? |
| `courses.ts` | `GET /notes/generated/{courseId}/by-node/{nodeId}` | `notes.py` | `@router.get("/generated/{course_id}/by-node/{node_id}")` | ? |
| `courses.ts` | `GET /scrape/auth/sessions` | `scrape.py` | `@router.get("/auth/sessions")` | ? |
| `courses.ts` | `POST /canvas/browser-login` | `canvas.py` | `@router.post("/browser-login")` | ? |
| `courses.ts` | `POST /canvas/course-info` | `canvas.py` | `@router.post("/course-info")` | ? |
| `chat.ts` | `POST /chat/` (SSE) | `chat.py` | `@router.post("/")` | ? |
| `chat.ts` | `GET /chat/greeting/{courseId}` | `chat.py` | `@router.get("/greeting/{course_id}")` | ? |
| `chat.ts` | `GET /chat/courses/{courseId}/sessions` | `chat.py` | `@router.get("/courses/{course_id}/sessions")` | ? |
| `chat.ts` | `GET /chat/sessions/{sessionId}/messages` | `chat.py` | `@router.get("/sessions/{session_id}/messages")` | ? |
| `practice.ts` | `GET /wrong-answers/{courseId}` | `wrong_answers.py` | `@router.get("/{course_id}")` | ? |
| `practice.ts` | `POST /wrong-answers/{id}/retry` | `wrong_answers.py` | `@router.post("/{wrong_answer_id}/retry")` | ? |
| `practice.ts` | `POST /wrong-answers/{id}/derive` | `wrong_answers.py` | `@router.post("/{wrong_answer_id}/derive")` | ? |
| `practice.ts` | `POST /wrong-answers/{id}/diagnose` | `wrong_answers.py` | `@router.post("/{wrong_answer_id}/diagnose")` | ? |
| `practice.ts` | `GET /wrong-answers/{courseId}/stats` | `wrong_answers.py` | `@router.get("/{course_id}/stats")` | ? |
| `practice.ts` | `GET /workflows/wrong-answer-review` | `workflows.py` | `@router.get("/wrong-answer-review")` | ? |
| `practice.ts` | `POST /quiz/extract` | `quiz_generation.py` | `@router.post("/extract")` | ? |
| `practice.ts` | `GET /quiz/{courseId}` | `quiz_submission.py` | `@router.get("/{course_id}")` | ? |
| `practice.ts` | `GET /quiz/{courseId}/generated-batches` | `quiz_generation.py` | `@router.get("/{course_id}/generated-batches")` | ? |
| `practice.ts` | `POST /quiz/submit` | `quiz_submission.py` | `@router.post("/submit")` | ? |
| `practice.ts` | `POST /quiz/save-generated` | `quiz_generation.py` | `@router.post("/save-generated")` | ? |
| `practice.ts` | `POST /flashcards/generate` | `flashcards.py` | `@router.post("/generate")` | ? |
| `practice.ts` | `POST /flashcards/generated/save` | `flashcards.py` | `@router.post("/generated/save")` | ? |
| `practice.ts` | `GET /flashcards/generated/{courseId}` | `flashcards.py` | `@router.get("/generated/{course_id}")` | ? |
| `practice.ts` | `POST /flashcards/review` | `flashcards.py` | `@router.post("/review")` | ? |
| `practice.ts` | `GET /flashcards/due/{courseId}` | `flashcards.py` | `@router.get("/due/{course_id}")` | ? |
| `practice.ts` | `GET /flashcards/lector-order/{courseId}` | `flashcards.py` | `@router.get("/lector-order/{course_id}")` | ? |
| `practice.ts` | `GET /flashcards/confusion-pairs/{courseId}` | `flashcards.py` | `@router.get("/confusion-pairs/{course_id}")` | ? |
| `progress.ts` | `GET /progress/courses/{courseId}` | `progress.py` | `@router.get("/courses/{course_id}")` | ? |
| `progress.ts` | `GET /progress/overview` | `progress.py` | `@router.get("/overview")` | ? |
| `progress.ts` | `GET /progress/trends` | `progress_analytics.py` | `@router.get("/trends")` | ? |
| `progress.ts` | `GET /progress/memory-stats` | `progress_analytics.py` | `@router.get("/memory-stats")` | ? |
| `progress.ts` | `POST /progress/memory-consolidate` | `progress_analytics.py` | `@router.post("/memory-consolidate")` | ? |
| `progress.ts` | `GET /progress/courses/{id}/forgetting-forecast` | `progress_knowledge.py` | `@router.get("/.../forgetting-forecast")` | ? |
| `progress.ts` | `GET /progress/courses/{id}/misconceptions` | `progress_knowledge.py` | `@router.get("/.../misconceptions")` | ? |
| `progress.ts` | `GET /progress/courses/{id}/knowledge-graph` | `progress_knowledge.py` | `@router.get("/.../knowledge-graph")` | ? |
| `progress.ts` | `GET /progress/courses/{id}/review-session` | `progress_knowledge.py` | `@router.get("/.../review-session")` | ? |
| `progress.ts` | `POST /progress/courses/{id}/review-session/rate` | `progress_knowledge.py` | `@router.post("/.../review-session/rate")` | ? |
| `progress-analytics.ts` | `POST /workflows/exam-prep` | `workflows.py` | `@router.post("/exam-prep")` | ? |
| `progress-analytics.ts` | `POST /workflows/study-plans/save` | `workflows.py` | `@router.post("/study-plans/save")` | ? |
| `progress-analytics.ts` | `GET /workflows/study-plans/{courseId}` | `workflows.py` | `@router.get("/study-plans/{course_id}")` | ? |
| `progress-analytics.ts` | `GET /workflows/courses/{id}/study-plans` | `workflows.py` | `@router.get("/courses/{course_id}/study-plans")` | ? |
| `progress-analytics.ts` | `GET /tasks` | `tasks.py` | `@router.get("/")` | ? |
| `progress-analytics.ts` | `POST /tasks/submit` | `tasks.py` | `@router.post("/submit")` | ? |
| `progress-analytics.ts` | `POST /tasks/{taskId}/approve` | `tasks.py` | `@router.post("/{task_id}/approve")` | ? |
| `progress-analytics.ts` | `POST /tasks/{taskId}/reject` | `tasks.py` | `@router.post("/{task_id}/reject")` | ? |
| `progress-analytics.ts` | `GET /goals/` | `goals.py` | `@router.get("/")` | ? |
| `progress-analytics.ts` | `POST /goals/` | `goals.py` | `@router.post("/")` | ? |
| `progress-analytics.ts` | `PATCH /goals/{goalId}` | `goals.py` | `@router.patch("/{goal_id}")` | ? |
| `progress-analytics.ts` | `GET /goals/{courseId}/next-action` | `goals.py` | `@router.get("/{course_id}/next-action")` | ? |
| `progress-analytics.ts` | `GET /progress/templates` | `progress_analytics.py` | `@router.get("/templates")` | ? |
| `progress-analytics.ts` | `POST /progress/templates/apply` | `progress_analytics.py` | `@router.post("/templates/apply")` | ? |
| `progress-analytics.ts` | `GET /progress/courses/{id}/velocity` | `progress_knowledge.py` | `@router.get("/.../velocity")` | ? |
| `progress-analytics.ts` | `GET /progress/courses/{id}/forecast` | `progress_knowledge.py` | `@router.get("/.../forecast")` | ? |
| `progress-analytics.ts` | `GET /progress/transfer-opportunities` | `progress_knowledge.py` | `@router.get("/transfer-opportunities")` | ? |
| `progress-analytics.ts` | `GET /agent/runs` | `agenda.py` | `@router.get("/runs")` | ? |
| `progress-analytics.ts` | `POST /agent/log-decision` | `agenda.py` | `@router.post("/log-decision")` | ? |
| `usage.ts` | `GET /usage/summary` | `usage.py` | `@router.get("/summary")` | ? |
| `usage.ts` | `GET /export/session` | `export.py` | `@router.get("/export/session")` | ? |
| `usage.ts` | `GET /export/anki` | `export.py` | `@router.get("/export/anki")` | ? |
| `usage.ts` | `GET /export/calendar` | `export.py` | `@router.get("/export/calendar")` | ? |
| `notifications.ts` | `GET /notifications` | `notifications.py` | `@router.get("/notifications")` | ? |
| `notifications.ts` | `POST /notifications/{id}/read` | `notifications.py` | `@router.post("/.../read")` | ? |
| `notifications.ts` | `POST /notifications/read-all` | `notifications.py` | `@router.post("/read-all")` | ? |
| `ingestion.ts` | `GET /content/jobs/{courseId}` | `upload.py` | `@router.get("/jobs/{course_id}")` | ? |
| `ingestion.ts` | `GET /scrape/sources` | `scrape.py` | `@router.get("/sources")` | ? |
| `ingestion.ts` | `POST /scrape/sources` | `scrape.py` | `@router.post("/sources")` | ? |
| `ingestion.ts` | `PATCH /scrape/sources/{id}` | `scrape.py` | `@router.patch("/sources/{source_id}")` | ? |
| `ingestion.ts` | `DELETE /scrape/sources/{id}` | `scrape.py` | `@router.delete("/sources/{source_id}")` | ? |
| `ingestion.ts` | `POST /scrape/sources/{id}/scrape-now` | `scrape.py` | `@router.post("/.../scrape-now")` | ? |
| `ingestion.ts` | `POST /courses/{id}/sync` | `courses_sync.py` | `@router.post("/{course_id}/sync")` | ? |
| `preferences.ts` | `GET /preferences/profile` | `preferences_crud.py` | `@router.get("/profile")` | ? |
| `preferences.ts` | `POST /preferences/` | `preferences_crud.py` | `@router.post("/")` | ? |
| `preferences.ts` | `POST /preferences/{id}/dismiss` | `preferences_crud.py` | `@router.post("/{preference_id}/dismiss")` | ? |
| `preferences.ts` | `POST /preferences/{id}/restore` | `preferences_crud.py` | `@router.post("/{preference_id}/restore")` | ? |
| `preferences.ts` | `GET /preferences/signals` | `preferences_crud.py` | `@router.get("/signals")` | ? |
| `preferences.ts` | `POST /preferences/signals/{id}/dismiss` | `preferences_signals.py` | `@router.post("/.../dismiss")` | ? |
| `preferences.ts` | `POST /preferences/signals/{id}/restore` | `preferences_signals.py` | `@router.post("/.../restore")` | ? |
| `preferences.ts` | `POST /preferences/memories/{id}/dismiss` | `preferences_signals.py` | `@router.post("/.../dismiss")` | ? |
| `preferences.ts` | `POST /preferences/memories/{id}/restore` | `preferences_signals.py` | `@router.post("/.../restore")` | ? |
| `preferences.ts` | `GET /preferences/runtime/llm` | `preferences_llm.py` | `@router.get("/runtime/llm")` | ? |
| `preferences.ts` | `PUT /preferences/runtime/llm` | `preferences_llm.py` | `@router.put("/runtime/llm")` | ? |
| `preferences.ts` | `POST /preferences/runtime/llm/test` | `preferences_llm.py` | `@router.post("/runtime/llm/test")` | ? |
| `preferences.ts` | `GET /preferences/runtime/ollama/models` | `preferences_llm.py` | `@router.get("/runtime/ollama/models")` | ? |

### 1.3 已知风险点

| 风险 | 说明 | 严重度 |
|------|------|--------|
| Voice WebSocket | 前端 `use-voice-session.ts` 连接 `/api/voice/ws/{courseId}`，需确认后端是否实现 | **高** |
| 已删除路由引用 | `knowledge_graph.py` 已标记删除(git status D)，前端是否仍在调用？ | **高** |
| 已删除组件 | `podcast-block.tsx`, `podcast-player.tsx`, `podcast-view.tsx` 已删除，是否有残留引用？ | **中** |
| 前缀匹配 | 前端 `/api/` 前缀通过 Next.js rewrite，后端 router prefix 是否一致？ | **高** |
| SSE 流断链 | chat SSE 事件类型 (content, actions, block_update...) 前后端是否完全匹配？ | **高** |

### 1.4 检测脚本

```python
#!/usr/bin/env python3
"""api_link_checker.py - 前后端 API 连通性自动检测"""
import re, os, json
from pathlib import Path

API_DIR = Path("apps/api/routers")
WEB_API_DIR = Path("apps/web/src/lib/api")

def extract_backend_routes():
    """提取后端所有已注册路由"""
    routes = []
    for f in API_DIR.glob("*.py"):
        content = f.read_text()
        for match in re.finditer(
            r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"', content
        ):
            method, path = match.groups()
            routes.append({"method": method.upper(), "path": path, "file": f.name})
    return routes

def extract_frontend_calls():
    """提取前端所有 API 调用路径"""
    calls = []
    for f in WEB_API_DIR.glob("*.ts"):
        content = f.read_text()
        # 匹配 request<T>(`/path`) 和 fetch(`/api/path`) 模式
        for match in re.finditer(r'(?:request|requestBlob|fetch)\s*[<(]\s*`([^`]+)`', content):
            path = match.group(1)
            # 提取 HTTP 方法
            method_match = re.search(r'method:\s*"(\w+)"', content[max(0,match.start()-200):match.end()+50])
            method = method_match.group(1) if method_match else "GET"
            calls.append({"method": method, "path": path, "file": f.name})
    return calls

def check_connectivity():
    backend = extract_backend_routes()
    frontend = extract_frontend_calls()

    # 将后端路径中的 {param} 转为正则
    def path_to_regex(path):
        return re.sub(r'\{[^}]+\}', r'[^/]+', path) + '$'

    orphan_frontend = []
    for call in frontend:
        matched = False
        for route in backend:
            if re.match(path_to_regex(route["path"]), call["path"].split("?")[0].lstrip("/")):
                matched = True
                break
        if not matched:
            orphan_frontend.append(call)

    orphan_backend = []
    for route in backend:
        matched = False
        for call in frontend:
            clean_path = call["path"].split("?")[0].lstrip("/")
            if re.match(path_to_regex(route["path"]), clean_path):
                matched = True
                break
        if not matched:
            orphan_backend.append(route)

    print("=== 前端调用但后端无对应路由 ===")
    for c in orphan_frontend:
        print(f"  [{c['method']}] {c['path']}  ({c['file']})")

    print("\n=== 后端路由但前端未调用 ===")
    for r in orphan_backend:
        print(f"  [{r['method']}] {r['path']}  ({r['file']})")

if __name__ == "__main__":
    check_connectivity()
```

---

## 2. 死代码与孤立模块检测

### 2.1 目标
检测不被任何入口引用的代码、废弃文件、未使用的导入和导出。

### 2.2 检测维度

#### A. 后端死代码

| 检测项 | 检测方法 | 工具 |
|--------|----------|------|
| 未注册的 Router | 对比 `router_registry.py` CORE_ROUTERS 与实际 router 文件 | 手动/脚本 |
| 未调用的 Service 函数 | `vulture apps/api/ --min-confidence 80` | vulture |
| 未使用的 Model 类 | grep 所有 Model 类名，检查引用次数 | grep/脚本 |
| 未使用的 Schema 类 | grep 所有 Schema 类名，检查引用次数 | grep/脚本 |
| 未使用的 import | `ruff check --select F401 apps/api/` | ruff |
| 已删除文件的残留引用 | grep 删除文件中的类/函数名 | grep |

```bash
# 检测未使用导入
ruff check --select F401 apps/api/

# 检测已删除的 knowledge_graph.py 的残留引用
grep -rn "knowledge_graph\|KnowledgeGraphRouter" apps/api/ --include="*.py"

# 检测已删除 podcast 相关代码的残留引用
grep -rn "podcast" apps/web/src/ --include="*.ts" --include="*.tsx"
```

#### B. 前端死代码

| 检测项 | 检测方法 | 工具 |
|--------|----------|------|
| 未引用的组件 | `npx knip` (unused exports) | knip |
| 未引用的 API 函数 | 检查 `lib/api/` 中每个导出函数的引用 | knip/ts-prune |
| 未引用的 hooks | 检查 `hooks/` 中每个导出的引用 | knip |
| 未引用的 store actions | 检查 zustand store 中每个 action 的引用 | grep |
| 未引用的类型定义 | `npx knip --include types` | knip |
| 废弃的 block 类型 | 对比 `BlockType` 联合类型与 `BLOCK_REGISTRY` | 手动 |

```bash
# 前端未使用导出检测
cd apps/web && npx knip --reporter compact

# 检测未使用的 API 函数
for fn in $(grep -oP 'export (async )?function \K\w+' src/lib/api/*.ts); do
  count=$(grep -rn "$fn" src/ --include="*.ts" --include="*.tsx" | grep -v "lib/api/" | wc -l)
  if [ "$count" -eq 0 ]; then
    echo "UNUSED API function: $fn"
  fi
done
```

#### C. 跨层孤立检测

```
已删除文件清单 (git status D):
  - apps/api/routers/knowledge_graph.py     → 检查前端是否仍 import
  - apps/web/src/components/audio/podcast-player.tsx  → 检查引用链
  - apps/web/src/components/blocks/blocks/podcast-block.tsx → 检查 BLOCK_REGISTRY
  - apps/web/src/components/sections/practice/podcast-view.tsx → 检查 practice-section
```

---

## 3. 逻辑一致性审计

### 3.1 目标
检测前后端对同一业务概念的理解是否一致，不存在"一方改了另一方没跟上"的情况。

### 3.2 检测维度

#### A. 枚举值一致性

| 概念 | 前端定义 | 后端定义 | 检查点 |
|------|----------|----------|--------|
| BlockType | `lib/block-system/types.ts` | `services/block_decision/rules.py` | 类型列表完全一致? |
| LearningMode | `lib/block-system/types.ts` | `config.py` 或 agent 逻辑 | 模式名一致? |
| BlockSize | `lib/block-system/types.ts` | 后端是否使用? | 是否仅前端概念? |
| BlockSource | `lib/block-system/types.ts` | SSE block_update event | 值域一致? |
| ChatEventType | `lib/api/chat.ts` SSE handler | `services/agent/stream_events.py` | 事件类型完全匹配? |
| ErrorCategory | `store/chat.ts` categorizeError | 后端错误码 | 分类逻辑一致? |
| PracticeMode | `quiz-options.tsx` | `quiz_generation.py` mode 参数 | 值域一致? |
| Difficulty | `quiz-options.tsx` | `quiz_generation.py` difficulty 参数 | 值域一致? |
| NotificationType | `schemas/notification.py` | `locales/en.json` 通知文案 | 每种类型有对应文案? |
| GoalStatus | `progress-analytics.ts` | `models/study_goal.py` | 状态机一致? |
| TaskStatus | `progress-analytics.ts` | `models/agent_task.py` | 状态流转一致? |

#### B. 请求/响应 Schema 一致性

```
检测方法:
1. 后端 Pydantic Schema → 生成 JSON Schema
2. 前端 TypeScript 类型 → 推断期望字段
3. 对比字段名、类型、可选性

关键检查:
- quiz/submit 请求体: 前端发送的字段是否后端都接收?
- chat SSE 事件: 前端解析的每个 key 后端都发送?
- block_update 操作: add/remove/reorder 的 payload 格式一致?
- 分页参数: limit/offset vs cursor 是否统一?
```

#### C. SSE 事件协议一致性 (重点)

```
前端 chat.ts 处理的事件类型:
  content, actions, status, plan_step, tool_status,
  tool_progress, clarify, block_update, done, warning

后端 stream_events.py 发送的事件类型:
  → 需逐一核对，确保无遗漏或拼写差异

检查重点:
  1. 事件名拼写是否完全一致 (如 block_update vs blockUpdate)
  2. 每个事件的 data 结构是否匹配
  3. done 事件是否包含前端期望的所有字段
  4. error 事件前端是否处理?
```

#### D. 业务逻辑一致性

| 逻辑 | 前端实现 | 后端实现 | 检查点 |
|------|----------|----------|--------|
| Block 解锁条件 | `feature-unlock.ts` | `block_decision/rules.py` | 条件公式一致? |
| FSRS 评分映射 | `flashcard-view.tsx` rating 值 | `services/spaced_repetition/fsrs.py` | 1-4 映射一致? |
| 认知负载计算 | 前端是否使用? | `cognitive_load_calibrator.py` 9 个权重因子 | 是否仅后端? |
| 掌握度阈值 | 前端显示逻辑 | 后端 mastery 计算 | 阈值一致? |
| 分页逻辑 | cursor/offset | 后端 limit/offset | 是否匹配? |
| 日期格式 | ISO 8601? | ISO 8601? | 时区处理一致? |

---

## 4. 数据流闭环验证

### 4.1 目标
确保每个核心用户流程从触发到完成形成完整闭环，不存在"发出去没回来"的半成品流程。

### 4.2 核心闭环清单

#### 闭环 1: 内容上传 → 解析 → 展示

```
用户上传文件
  → upload-dialog.tsx → uploadFile() → POST /content/upload
  → 后端 IngestionJob 创建 → pipeline 7步处理
  → 前端轮询 listIngestionJobs() → GET /content/jobs/{courseId}
  → 完成后 content-tree 刷新 → getContentTree()
  → 内容节点出现在 chapter-list

检查点:
  [ ] 上传失败时前端是否有错误提示?
  [ ] pipeline 中间步骤失败是否标记 job 状态?
  [ ] job 状态变化前端是否正确轮询?
  [ ] 长时间处理是否有超时机制?
  [ ] 解析完成后是否触发 content-tree 刷新?
```

#### 闭环 2: 发送消息 → Agent 处理 → 流式响应 → 副作用

```
用户发送消息
  → chat-input.tsx → sendMessage() → streamChat() SSE
  → 后端 orchestrator → intent分类 → agent路由 → tool调用
  → SSE 事件流: content → actions → block_update → done
  → 前端解析: 消息展示, workspace 操作, block 添加
  → 会话持久化: ChatMessageLog

检查点:
  [ ] SSE 连接断开时前端是否重连或提示?
  [ ] agent 工具调用失败时是否发送错误事件?
  [ ] block_update 事件中引用的 blockType 是否在前端 registry 中?
  [ ] actions 事件的操作 (navigate, refresh) 前端是否全部实现?
  [ ] abort 信号是否能真正中断后端处理?
```

#### 闭环 3: 做题 → 提交 → 评分 → 掌握度更新 → 复习调度

```
用户答题
  → quiz-view.tsx → submitAnswer() → POST /quiz/submit
  → 后端: 评分 → 错误分类 → mastery更新 → FSRS调度 → WrongAnswer记录
  → 前端: 显示结果 → progress-block 刷新 → 如果错 → wrong-answers-block
  → 后续: forgetting-forecast 更新 → review-session 调整

检查点:
  [ ] 提交后 progress-block 是否自动刷新?
  [ ] 错误答案是否出现在 wrong-answers 列表?
  [ ] FSRS 下次复习时间是否反映在 due flashcards?
  [ ] mastery-history 是否记录了此次变化?
  [ ] 知识图谱 mastery 颜色是否更新?
```

#### 闭环 4: 闪卡复习 → 评分 → FSRS 更新 → 下次调度

```
用户复习闪卡
  → flashcard-view.tsx → reviewFlashcard() → POST /flashcards/review
  → 后端: FSRS 评分 → stability/difficulty 更新 → next_review 计算
  → 前端: 下一张卡 → 统计更新

检查点:
  [ ] review 后 due 列表是否移除已复习卡?
  [ ] LECTOR 顺序是否在复习后重新计算?
  [ ] confusion-pairs 是否根据错误模式更新?
```

#### 闭环 5: Agent 建议 Block → 用户审批 → Block 显示

```
Agent 建议添加 block
  → SSE block_update 事件 → applyBlockDecisions()
  → workspace store: agentAddBlock() → needsApproval
  → 用户 approve → approveAgentBlock() → block 可见
  → 用户 dismiss → dismissAgentBlock() → recordDismiss() → 7天内不再建议

检查点:
  [ ] dismiss 记录是否持久化 (localStorage)?
  [ ] 7天过期逻辑是否正确?
  [ ] agent block 过期 (expiresAt) 后是否自动移除?
  [ ] 同时建议多个 block 时是否正确处理?
```

#### 闭环 6: 创建课程 → 模板应用 → 首次内容 → workspace 就绪

```
新建课程流程
  → new/page.tsx → createCourse() → POST /courses/
  → 模板选择 → applyBlockTemplate()
  → 内容上传 → 等待解析
  → 跳转 workspace → 加载 layout → block grid 展示

检查点:
  [ ] 无模板时默认 layout 是否合理?
  [ ] 模板 blocks 是否与 BLOCK_REGISTRY 一致?
  [ ] 首次加载无内容时是否有空状态引导?
  [ ] layout 是否持久化到 PATCH /courses/{id}/layout?
```

#### 闭环 7: 学习目标 → 下一步行动 → Agent 任务 → 完成

```
创建目标
  → createStudyGoal() → POST /goals/
  → getNextAction() → GET /goals/{courseId}/next-action
  → 推荐操作 → 用户执行
  → 目标进度更新 → updateStudyGoal() → PATCH /goals/{goalId}

检查点:
  [ ] next-action 推荐是否基于目标状态?
  [ ] 完成某个操作后目标进度是否更新?
  [ ] 所有子任务完成后目标是否标记完成?
```

#### 闭环 8: 通知生成 → 推送 → 阅读标记

```
后端生成通知
  → Notification model 创建
  → 前端 listNotifications() 轮询
  → notification-bell 展示未读数
  → 用户点击 → markNotificationRead()
  → 全部已读 → markAllNotificationsRead()

检查点:
  [ ] 通知轮询间隔是否合理 (不过频)?
  [ ] 未读计数是否实时更新?
  [ ] 关联 task 的通知是否可以批量标记?
```

---

## 5. 状态管理一致性

### 5.1 目标
确保 Zustand store 的状态在所有消费者之间保持一致，避免状态竞争和过期数据。

### 5.2 检测维度

#### A. 状态同步问题

| 检查项 | 场景 | 风险 |
|--------|------|------|
| course store vs workspace store | 切换课程时两者是否同步? | 显示旧课程的 blocks |
| chat store vs workspace store | block_update 事件同时操作两个 store | 竞态条件 |
| workspace blocks vs 后端 layout | 本地修改未持久化到后端 | 刷新丢失 |
| ingestion jobs 轮询 vs content tree | job 完成后 tree 是否刷新 | 看不到新内容 |
| practice 状态 vs progress 数据 | 提交答案后两者是否一致 | 数据不一致 |

#### B. 缓存一致性

```
检查所有 TTL 缓存:
  - course store: 60s TTL → 60s 内的数据变化用户看不到
  - chat sessions: 30s TTL → 新会话可能延迟显示

问题: 执行写操作后是否清除相关缓存?
  例: createCourse() 后是否清除 listCourseOverview() 的缓存?
```

#### C. 乐观更新一致性

```
检查所有乐观更新操作:
  - block reorder: 是否先更新 UI 再发请求?
  - block dismiss: localStorage 写入是否在 store 更新之前?
  - 如果后端拒绝操作，前端是否回滚?
```

---

## 6. 错误处理链完整性

### 6.1 目标
确保从后端到前端的错误链不断裂，用户能看到有意义的错误信息。

### 6.2 检测维度

#### A. 后端错误层级

```
异常传播链:
  Service 抛出 AppError 子类
    → Router 捕获或传播
      → main.py exception_handler 格式化
        → JSON {"code": "...", "message": "...", "status": N}
          → 前端 parseApiError() 解析

检查点:
  [ ] 每个 Service 函数是否使用正确的异常类型?
  [ ] 是否存在 bare except 吞掉有用错误信息?
  [ ] SQLAlchemyError 是否被正确转换为用户友好消息?
  [ ] LLM 超时/不可用是否返回 503 而非 500?
```

#### B. 前端错误处理

```
检查链:
  API 响应错误
    → parseApiError() 提取 message
      → toast 通知 (非 chat) 或 errorCategory (chat)
        → error boundary 捕获未处理异常
          → error.tsx 展示用户友好页面

检查点:
  [ ] 13 个 error.tsx 是否都正确实现了 reset 功能?
  [ ] chat 错误分类 (rate_limit, auth_error, timeout, llm_unavailable) 是否覆盖所有后端错误码?
  [ ] network 断开时是否有全局提示?
  [ ] retry 逻辑 (3次, 指数退避) 是否对所有 4xx 都生效? (不应该)
  [ ] 429 rate limit 是否显示剩余等待时间?
```

#### C. 错误 → 恢复 闭环

| 错误场景 | 用户看到什么 | 恢复方案 | 是否实现? |
|----------|-------------|---------|----------|
| LLM 不可用 | chat 区域提示 | 自动重连/切换 provider | ? |
| 上传文件太大 | 弹窗提示 | 显示大小限制 | ? |
| 网络断开 | 全局 banner | 自动重连 | ? |
| session 过期 | 重定向登录 | token refresh | ? |
| DB 迁移失败 | 健康检查红灯 | 手动 alembic | ? |
| SSE 流中断 | 消息不完整 | 重发/重连 | ? |
| quiz 提交失败 | 答案丢失 | 本地缓存重试 | ? |

---

## 7. 类型安全与契约一致性

### 7.1 目标
确保 TypeScript 类型与后端 Pydantic Schema 保持同步。

### 7.2 检测方法

#### A. 自动 Schema 对比

```bash
# 步骤 1: 导出后端 OpenAPI Schema
cd apps/api && python -c "
from main import create_app
import json
app = create_app()
schema = app.openapi()
with open('/tmp/openapi.json', 'w') as f:
    json.dump(schema, f, indent=2)
"

# 步骤 2: 对比前端类型期望
# 手动对照 OpenAPI definitions 与 TypeScript interfaces
```

#### B. 关键对比项

| 后端 Schema | 前端 Type | 对比字段 |
|-------------|-----------|----------|
| `CourseResponse` | courses.ts 返回类型 | id, name, description, metadata_ |
| `ChatRequest` | chat.ts 请求体 | content, course_id, images, learning_mode |
| `ProblemResponse` | practice.ts 返回类型 | id, question, options, difficulty |
| `AnswerResponse` | practice.ts 提交响应 | correct, explanation, mastery |
| `NotificationResponse` | notifications.ts | id, type, message, read, task_id |
| `BlockUpdateOp` | SSE block_update | op, type, config, size |

#### C. 可选字段陷阱

```
最常见的前后端不一致:
  1. 后端 Optional[str] = None → 前端未处理 null (直接 .length 崩溃)
  2. 后端新增必填字段 → 前端旧代码未发送
  3. 后端返回 snake_case → 前端期望 camelCase
  4. 后端日期格式 ISO → 前端是否正确解析
  5. 后端 UUID → 前端是否作为 string 处理
```

---

## 8. 数据库模型与迁移一致性

### 8.1 目标
确保 ORM 模型、Alembic 迁移、实际表结构三者一致。

### 8.2 检测方法

```bash
# 检查迁移与模型是否同步
cd apps/api && alembic check

# 检查是否只有一个迁移头
cd apps/api && alembic heads | wc -l  # 应该 = 1

# 检查模型是否都在 __init__.py 中注册
python -c "
from models import *  # 触发所有 import
from database import Base
tables = Base.metadata.tables.keys()
print(f'Registered tables: {len(tables)}')
for t in sorted(tables):
    print(f'  {t}')
"
```

### 8.3 检测维度

| 检查项 | 说明 | 工具 |
|--------|------|------|
| 模型全部注册 | `models/__init__.py` 导出所有模型类 | import 检查 |
| 迁移不分叉 | alembic heads 只有 1 个 | alembic heads |
| 索引合理性 | 高频查询列有索引 | 模型审查 |
| 外键约束 | 级联删除设置正确 | 模型审查 |
| 兼容层 | CompatUUID/CompatJSONB 在 SQLite/PG 都工作 | 双 DB 测试 |
| 字段类型 | metadata_ 的 JSON 字段跨 DB 兼容 | 运行时检查 |

---

## 9. 安全性审计

### 9.1 检测维度

| 检查项 | 方法 | 现状 |
|--------|------|------|
| SQL 注入 | 检查所有 raw SQL 查询 | SQLAlchemy ORM 基本安全 |
| XSS | 检查 `dangerouslySetInnerHTML`, 用户内容渲染 | React 默认转义 |
| CSRF | 检查 mutation 请求是否带 CSRF token | 中间件已实现 |
| Auth bypass | AUTH_ENABLED=False 时哪些 endpoint 暴露? | **全部暴露** |
| Rate limit bypass | 检查限流是否可绕过 (X-Forwarded-For 等) | 需审查 |
| 文件上传 | 检查文件类型验证、路径穿越 | 需审查 |
| SSE 注入 | 检查 SSE data 是否有注入风险 | 需审查 |
| 密钥泄露 | 检查 .env 是否在 .gitignore | 已有 gitleaks |
| 依赖漏洞 | pip-audit, npm audit | CI 已配置 |
| 命令注入 | 代码沙箱是否有逃逸风险 | 需审查 sandbox backend |
| Prompt 注入 | 用户输入是否直接拼入 LLM prompt | middleware 有检测 |

```bash
# 后端安全扫描
pip-audit
ruff check --select S apps/api/  # bandit rules

# 前端安全扫描
cd apps/web && npm audit
grep -rn "dangerouslySetInnerHTML" apps/web/src/
grep -rn "eval(" apps/web/src/
```

---

## 10. 性能瓶颈检测

### 10.1 检测维度

#### A. N+1 查询

```python
# 检查所有 for 循环中的数据库查询
# 模式: for item in items → await session.execute(select... where item.id)
grep -rn "for.*in.*:" apps/api/ --include="*.py" -A5 | grep "session\.\|await.*select"
```

#### B. 前端性能

| 检查项 | 方法 |
|--------|------|
| 不必要的重渲染 | React DevTools Profiler |
| 大 bundle | `npx @next/bundle-analyzer` |
| 缺少 memo/useMemo | 检查频繁渲染的组件 |
| 列表缺少 virtualization | 长列表是否用了 @tanstack/react-virtual |
| SSE 消息处理阻塞 UI | 是否在 requestAnimationFrame 中更新 |
| 图片未优化 | 是否使用 next/image |

#### C. 后端性能

| 检查项 | 方法 |
|--------|------|
| LLM 调用无超时 | 检查 tenacity retry 配置 |
| embedding 批处理 | 单条 vs 批量 embedding |
| 并发 SSE 限制 | sse_limiter.py 配置 |
| 数据库连接池 | 连接池大小配置 |
| 大文件内存加载 | streaming vs 全量读取 |

---

## 11. 测试覆盖度审计

### 11.1 目标
识别未覆盖的关键路径。

### 11.2 覆盖率矩阵

| 模块 | 测试文件 | 覆盖? | 优先级 |
|------|----------|-------|--------|
| **Chat SSE 流** | 无专门测试? | ? | **P0** |
| **Block Decision Engine** | test_block_*.py (3) | 部分 | P0 |
| **Ingestion Pipeline** | test_ingestion_regressions.py | 回归 | P0 |
| **FSRS 算法** | test_fsrs*.py (3) | 较好 | P1 |
| **Agent Orchestrator** | test_agent_*.py (3) | 部分 | P0 |
| **Quiz Submit 全流程** | ? | ? | P0 |
| **前端 Chat 流** | chat-input.test.tsx | 仅输入 | **P0** |
| **前端 Block 系统** | feature-unlock.test.ts | 仅解锁 | P1 |
| **API 客户端 重试** | client.test.ts | 有 | P1 |
| **WebSocket Voice** | use-voice-session.test.ts | 有 | P2 |
| **Canvas 集成** | test_canvas_*.py | 有 | P2 |
| **Middleware 安全** | test_middleware_security.py | 有 | P1 |

### 11.3 缺失测试 (建议补充)

```
P0 缺失:
  1. SSE 流完整性测试 (前端解析所有事件类型)
  2. Block 添加/删除/undo 完整流程
  3. Quiz 答题 → 评分 → mastery 更新 端到端
  4. 课程创建 → 上传 → 内容展示 端到端
  5. Agent 建议 block → approve/dismiss 流程

P1 缺失:
  6. 错误处理: 各种后端错误码的前端表现
  7. 并发 SSE 流限制场景
  8. 缓存失效场景
  9. 国际化: 所有 key 在两个 locale 中都存在
```

---

## 12. 配置与环境一致性

### 12.1 检测方法

```bash
# 检查 .env.example 与 config.py 的一致性
# .env.example 中定义的变量 config.py 是否都读取?
diff <(grep -oP '^[A-Z_]+=' .env.example | sort) \
     <(grep -oP "env\('([A-Z_]+)'" apps/api/config.py | sort)

# 检查 docker-compose.yml 的环境变量是否覆盖
grep "environment:" -A50 docker-compose.yml | grep -oP '\${[A-Z_]+' | sort -u

# 检查 next.config.ts 的 rewrites 是否与后端端口匹配
grep "destination" apps/web/next.config.ts
```

### 12.2 关键检查

| 检查项 | 问题 |
|--------|------|
| `install.sh` 中的 `<org>` 占位符 | 未替换，脚本无法运行 |
| AUTH_ENABLED 默认 False | 开发安全 但容易误上生产 |
| CORS_ORIGINS 配置 | 生产环境是否限制? |
| JWT_SECRET_KEY | 是否有默认值? 是否足够长? |
| ENCRYPTION_KEY | 生产是否必填? 是否检查? |
| LLM_PROVIDER 默认 lmstudio | docker 环境是否能连接? |
| SQLite 路径 | docker volume 映射是否正确? |
| Next.js rewrite /api/* | 端口是否匹配 docker-compose? |

---

## 13. 国际化完整性

### 13.1 检测方法

```bash
# 对比 en.json 和 zh.json 的 key
diff <(python3 -c "
import json
with open('apps/web/src/locales/en.json') as f:
    keys = sorted(json.load(f).keys())
print('\n'.join(keys))
") <(python3 -c "
import json
with open('apps/web/src/locales/zh.json') as f:
    keys = sorted(json.load(f).keys())
print('\n'.join(keys))
")

# 检查代码中使用的 i18n key 是否在 locale 文件中
grep -rhoP "useT\(\)\s*\(\s*['\"]([^'\"]+)['\"]" apps/web/src/ | sort -u > /tmp/used_keys.txt
```

### 13.2 检查项

| 检查项 | 方法 |
|--------|------|
| en/zh key 完全匹配 | JSON key diff |
| 无硬编码中文/英文 | grep 中文字符 in tsx (排除 locale 文件) |
| 插值参数一致 | `{{count}}` 等在两个 locale 都存在 |
| Block label 国际化 | BLOCK_REGISTRY 的 label/labelZh |
| 错误消息国际化 | toast 和 error boundary 文案 |
| 后端错误消息语言 | API 返回的 message 是否需要 i18n? |

---

## 14. 可观测性与监控链路

### 14.1 检测维度

| 检查项 | 现状 | 问题 |
|--------|------|------|
| 请求延迟追踪 | MetricsMiddleware | 是否覆盖 SSE 流? |
| 错误率监控 | 错误计数 | 是否分路由统计? |
| LLM 调用追踪 | usage.py | 是否记录 token 数? |
| 前端错误上报 | error-telemetry.ts (新) | 是否连接到后端? |
| 健康检查 | /health, /health/live, /health/ready | docker healthcheck 用哪个? |
| 日志格式 | 结构化? | 是否便于检索? |
| 分布式追踪 | tracing.py | trace ID 是否传递到前端? |
| 审计日志 | AuditLogMiddleware | 是否持久化? |

### 14.2 缺失的监控

```
建议补充:
  1. SSE 流断开率监控
  2. LLM circuit breaker 状态暴露
  3. 前端 Core Web Vitals 上报
  4. 数据库查询慢日志
  5. Agent 任务执行时长分布
  6. 内容解析成功/失败率
```

---

## 15. 构建与部署链完整性

### 15.1 CI/CD 链路

```
代码提交
  → pre-commit: gitleaks (密钥检测)
  → CI checks job:
    → pip-audit (依赖漏洞)
    → pytest (60 个测试文件)
    → alembic 迁移验证
    → 源码编译检查
    → ESLint
    → Vitest (172+ 测试)
    → Next.js build
  → api-smoke job:
    → Mock LLM + API 冒烟测试
    → 回归基准
  → e2e-ui job (可选):
    → Playwright 浏览器测试
  → llm-integration job (可选):
    → 真实 LLM 集成测试
```

### 15.2 链路断点检查

| 检查项 | 风险 |
|--------|------|
| pre-commit 未安装 | 开发者可提交密钥 |
| e2e 默认关闭 | UI 回归可能漏检 |
| llm-integration 默认关闭 | LLM 集成可能不工作 |
| docker build 未在 CI 中 | 容器构建可能失败 |
| 无自动部署 | 手动部署易出错 |
| 无 staging 环境 | 直接上生产 |
| 无回滚机制 | 发布后问题难恢复 |
| 无性能基准 | 无法检测性能退化 |

---

## 执行计划

### Phase 1: 自动化检测 (1-2 天)

| 任务 | 脚本/工具 | 预期输出 |
|------|----------|----------|
| API 连通性扫描 | `api_link_checker.py` | 断链列表 |
| 死代码扫描 | vulture + knip + ruff F401 | 死代码列表 |
| 类型检查 | pyright + tsc --noEmit | 类型错误列表 |
| 安全扫描 | pip-audit + npm audit + gitleaks | 漏洞列表 |
| i18n key 对比 | JSON diff 脚本 | 缺失 key 列表 |
| 配置一致性 | env/config diff 脚本 | 不一致列表 |

### Phase 2: 人工审查 (2-3 天)

| 任务 | 重点 | 审查人 |
|------|------|--------|
| SSE 协议审查 | 事件类型、payload 格式 | 全栈 |
| 数据流闭环 | 8 个核心闭环逐一验证 | 全栈 |
| 枚举值一致性 | 11 组枚举对照 | 全栈 |
| 错误处理链 | 从后端到前端完整链路 | 全栈 |
| 状态管理审查 | Zustand store 竞态分析 | 前端 |
| 数据库审查 | 索引、N+1、迁移 | 后端 |

### Phase 3: 修复与验证 (持续)

| 优先级 | 说明 |
|--------|------|
| **P0** | 断链 (前端调用不存在的后端接口)、安全漏洞、数据丢失风险 |
| **P1** | 死代码、类型不一致、错误处理不完整 |
| **P2** | 性能问题、测试覆盖、i18n 缺失 |
| **P3** | 配置优化、监控增强、文档补全 |

---

## 附录: 已知问题快速参考

| # | 问题 | 位置 | 严重度 | 状态 |
|---|------|------|--------|------|
| 1 | `knowledge_graph.py` 已删除但可能有残留引用 | `apps/api/routers/` | 高 | 待查 |
| 2 | podcast 相关组件已删除但可能有残留引用 | `apps/web/src/components/` | 中 | 待查 |
| 3 | Voice WebSocket endpoint 可能未实现 | `use-voice-session.ts` | 高 | 待查 |
| 4 | AUTH_ENABLED 默认 False | `config.py` | 高 | 已知 |
| 5 | `install.sh` 有 `<org>` 占位符 | `scripts/install.sh` | 中 | 已知 |
| 6 | 测试覆盖率门槛仅 25% | `pytest.ini` | 中 | 已知 |
| 7 | SSE 事件类型前后端一致性未验证 | 全局 | 高 | 待查 |
| 8 | Block 解锁条件前后端是否同步 | feature-unlock.ts / rules.py | 中 | 待查 |
| 9 | LM Studio 并发崩溃 | LLM router | 高 | 已知 |
| 10 | 两个 DeepSeek API key 在本地 .env | `.env` | 高 | 需撤销 |

---

> 本文档由项目架构审计生成，覆盖 15 个审计维度、140+ API 端点、25+ 数据模型、8 个核心数据流闭环。
> 建议每次大版本发布前重新执行 Phase 1 自动化检测。
