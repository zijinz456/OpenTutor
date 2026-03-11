# OpenTutor 优化计划

> 生成日期: 2026-03-12
> 目标: 在不砍功能的前提下，系统性提升代码质量、安全性、性能和可维护性

---

## 原则

1. **不砍功能** — 所有 service 都有活跃调用路径，全部保留
2. **先修危险的，再修影响体验的，最后优化结构**
3. **每个阶段可独立完成、独立 merge**
4. **所有改动都要有对应测试**

---

## 阶段零：紧急安全修复 (1-2 小时)

### 0.1 撤销泄露的 API 密钥
- [ ] 登录 DeepSeek 控制台，revoke `REDACTED_KEY`
- [ ] 生成新密钥，仅存入本地 `.env`
- [ ] 确认 `.env` 不在 git tracked 文件中 (`git ls-files .env` 应无输出)
- [ ] 运行 `git log --all -p -- '*.env'` 确认历史提交中没有密钥
- [ ] 如果历史中有，用 `git filter-repo` 或 BFG 清理

### 0.2 确认 .secrets.baseline 不含真实密钥
- [ ] 检查 `.secrets.baseline` 文件内容，确保只有 hash 没有明文

---

## 阶段一：Bug 修复 (半天)

### 1.1 Chat Clarify 协议注入风险
**文件**: `apps/web/src/store/chat.ts`
**问题**: `[CLARIFY:${key}:${value}]` 字符串拼接，key/value 含 `:` 或 `]` 时协议解析错误
**修复方案**: 改用 JSON 格式
```typescript
// Before
get().sendMessage(courseId, `[CLARIFY:${key}:${value}]`);

// After
get().sendMessage(courseId, JSON.stringify({ type: "clarify", key, value }));
```
**后端对应修改**: `apps/api/routers/chat.py` 或 agent 消息解析处，需要同步解析 JSON 格式

### 1.2 Timer 清理问题
**文件**: `apps/web/src/store/chat.ts`
**问题**: `_toolStatusTimer` 在 SSE 流中途断开 + 页面导航时可能泄漏
**修复方案**:
- 在 store 层面维护 active timer Set
- 提供 `cleanup()` 方法
- 在 chat 组件 unmount 时调用

### 1.3 memory/pipeline.py 静默吞错
**文件**: `apps/api/services/memory/pipeline.py` (行 179, 199)
**问题**: `except Exception: pass` — 完全静默，连日志都没有
**修复方案**: 至少加 `logger.debug(..., exc_info=True)`

---

## 阶段二：except Exception 精细化 (1 天)

### 分类处理

**可以保留的 (有日志 + 合理的降级逻辑):**
| 文件 | 行 | 理由 |
|------|-----|------|
| `llm/router.py:205` | probe 失败 | 已有注释说明，降级为 unhealthy |
| `llm/litellm_client.py:88,123,179` | provider 错误 | litellm 的异常类型不可预知，catch-all 后 re-raise |
| `llm/providers/openai_client.py:80` | probe 失败 | 合理，标记为 unhealthy |
| `agent/base.py:75` | agent 执行失败 | 顶层 catch，记录异常 |
| `agent/orchestrator.py:217` | 顶层 catch | 返回用户友好错误 |
| `routers/upload.py:113` | 清理文件 | catch 后 re-raise |
| `ingestion/pipeline.py:324` | 顶层管道 | 标记 job 为 failed |
| `activity/engine_execution.py:203` | task 失败 | 标记为 failed |

**需要修改的 (没日志 / 过于宽泛):**

| 文件 | 行 | 修改方案 |
|------|-----|---------|
| `memory/pipeline.py:179` | `except Exception: pass` | 改为 `except (KeyError, TypeError): pass` 或加日志 |
| `memory/pipeline.py:199` | `except Exception: pass` | 改为 `except (ValueError, AttributeError)` |
| `onboarding/persistence.py:74,100` | preference 写入 | 改为 `except (SQLAlchemyError, ValueError)` |
| `block_decision/preference.py:63,90` | block event | 改为 `except SQLAlchemyError` |
| `quiz_generation.py:263` | 前置知识检查 | 改为 `except (KeyError, LookupError)` |
| `scheduler/engine_helpers.py:124` | 通知存储 | 改为 `except SQLAlchemyError` |
| `agent/extensions.py:113` | 扩展钩子 | 保留但确保 exc_info=True |
| `agent/agenda.py:112` | agenda tick | 保留，已有完善处理 |

---

## 阶段三：SQLite 性能优化 (2 小时)

### 3.1 启用 WAL 模式
**文件**: `apps/api/database.py`

WAL (Write-Ahead Logging) 允许读写并发，对 agent 并发调用 LLM tool + 写数据库场景至关重要。

```python
# 在 engine 创建后添加:
if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

### 3.2 添加关键索引
- 检查 `chat_messages` 表是否有 `(course_id, created_at)` 复合索引
- 检查 `flashcards` 表是否有 `(course_id, next_review)` 索引
- 检查 `wrong_answers` 表是否有 `(course_id, created_at)` 索引

---

## 阶段四：前端健壮性 (1 天)

### 4.1 请求取消 (AbortController)
**问题**: 页面导航时 in-flight fetch 不被取消，导致 race condition
**涉及文件**: `apps/web/src/lib/api/client.ts`

```typescript
// 在 request<T> 函数中支持 signal 参数
export async function request<T>(
  path: string,
  options?: RequestInit & { signal?: AbortSignal }
): Promise<T> { ... }
```

**在关键 hooks 中使用:**
- `use-unit-data.ts` — 切换 unit 时取消上一个请求
- `use-course-data.ts` — 切换 course 时取消
- `use-dashboard-data.ts` — 离开 dashboard 时取消

### 4.2 i18n 响应式改造
**文件**: `apps/web/src/lib/i18n.ts`, `apps/web/src/lib/i18n-context.ts`
**问题**: 模块级变量 `currentLocale` 不触发 React 重渲染
**方案**: 已有 `i18n-context.ts`，确认所有组件通过 `useT()` hook 获取翻译而非直接调用 `t()`

### 4.3 CSP 安全性
**文件**: `apps/web/next.config.ts`
**问题**: `'unsafe-eval'` 和 `'unsafe-inline'` 削弱了 CSP
**方案**:
- 用 nonce-based CSP 替代 `'unsafe-inline'` (Next.js 支持 `nonce` via `headers()`)
- 检查 `'unsafe-eval'` 是否可移除（Mermaid 可能需要）
- 至少在生产环境条件化 `http://localhost:*`

### 4.4 Web Dockerfile 多阶段构建
**文件**: `apps/web/Dockerfile`
```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Runtime (只保留 .next/standalone 输出)
FROM node:20-alpine
WORKDIR /app
RUN adduser -D opentutor
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
USER opentutor
EXPOSE 3001
CMD ["node", "server.js"]
```
需要在 `next.config.ts` 中添加 `output: "standalone"`。

---

## 阶段五：后端测试覆盖 (2-3 天)

### 优先级排序 (按风险从高到低)

#### P1: 安全关键路径
| 测试文件 | 覆盖模块 | 测试点 |
|----------|---------|--------|
| `test_auth_jwt.py` | `services/auth/jwt.py` | token 生成/验证/过期/篡改 |
| `test_auth_dependency.py` | `services/auth/dependency.py` | auth_enabled=True/False 路径 |
| `test_csrf.py` | `middleware/csrf.py` | HMAC 签名验证、过期、重放 |
| `test_rate_limiter.py` | `middleware/security.py` | 令牌桶算法、桶清理、成本感知模式 |
| `test_path_sandbox.py` | `services/filesystem/sandbox.py` | 路径遍历、符号链接、../ 攻击 |

#### P2: 核心业务逻辑
| 测试文件 | 覆盖模块 | 测试点 |
|----------|---------|--------|
| `test_llm_router.py` | `services/llm/router.py` | 提供商选择、fallback 链、健康检查 |
| `test_circuit_breaker.py` | `services/llm/circuit_breaker.py` | 开/关/半开状态转换、冷却时间 |
| `test_fsrs.py` | `services/spaced_repetition/fsrs.py` | 复习间隔计算、参数边界 |
| `test_loom_mastery.py` | `services/loom_mastery.py` | 掌握度更新、概念混淆检测 |
| `test_lector.py` | `services/lector.py` | 复习优先级排序、会话构建 |

#### P3: 数据管道
| 测试文件 | 覆盖模块 | 测试点 |
|----------|---------|--------|
| `test_ingestion_pipeline.py` | `services/ingestion/pipeline.py` | 各格式解析、错误降级 |
| `test_search_hybrid.py` | `services/search/hybrid.py` | 关键词+向量混合搜索 |
| `test_diagnosis.py` | `services/diagnosis/classifier.py` | 错误分类准确性 |

### 测试基础设施
- 使用 `pytest-asyncio` 配合 `aiosqlite` 内存数据库
- Mock LLM 调用（已有 `providers/mock_client.py`）
- 目标覆盖率: 核心路径 80%+，整体 50%+

---

## 阶段六：代码结构优化 (1 天)

### 6.1 memory/pipeline.py 清理
三处 `except Exception: pass` 改为有意义的异常处理

### 6.2 统一 localStorage 访问层
**问题**: 101 处直接 `localStorage.getItem/setItem` 调用
**方案**: 创建 `apps/web/src/lib/storage.ts`
```typescript
export const storage = {
  get<T>(key: string, fallback: T): T {
    if (typeof window === "undefined") return fallback;
    try {
      const val = localStorage.getItem(key);
      return val ? JSON.parse(val) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown): void {
    if (typeof window === "undefined") return;
    localStorage.setItem(key, JSON.stringify(value));
  },
  remove(key: string): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem(key);
  },
};
```
然后逐步迁移现有 localStorage 调用。优先迁移 SSR 可能出错的组件。

### 6.3 评估/实验框架标记为 internal
**文件**: `apps/api/routers/` 中的 eval 相关路由
**方案**: 加 `tags=["internal"]` 标记，在 OpenAPI 文档中分组显示
不删除，但明确标注这些不是面向用户的 API。

---

## 阶段七：文档与开源准备 (半天)

### 7.1 CHANGELOG 更新
- 记录本次所有改动

### 7.2 Architecture Decision Records
- 记录为什么选择 SQLite 作为默认 (简单部署)
- 记录 LOOM/LECTOR 的完成度和路线图
- 记录 auth_enabled=False 的设计决策

### 7.3 .env.example 审查
- 确保所有配置项都有注释说明
- 确保没有真实密钥残留

---

## 时间线总结

| 阶段 | 内容 | 预估时间 | 优先级 |
|------|------|---------|--------|
| 0 | 紧急安全修复 | 1-2 小时 | 🔴 立即 |
| 1 | Bug 修复 | 半天 | 🔴 本周 |
| 2 | except 精细化 | 1 天 | 🟡 本周 |
| 3 | SQLite WAL 优化 | 2 小时 | 🟡 本周 |
| 4 | 前端健壮性 | 1 天 | 🟡 下周 |
| 5 | 后端测试覆盖 | 2-3 天 | 🟠 持续 |
| 6 | 代码结构优化 | 1 天 | 🟢 下周 |
| 7 | 文档与开源准备 | 半天 | 🟢 发布前 |

**总计: 约 7-8 个工作日**

---

## 不做的事情 (以及为什么)

| 不做 | 理由 |
|------|------|
| 砍功能 | 所有 service 都有活跃调用路径，LOOM/LECTOR/认知负荷是核心学习管道 |
| 拆分微服务 | 当前用户量不需要，单体 + SQLite 是对的选择 |
| 换数据库 | SQLite + WAL 对单用户/小团队完全够用，PostgreSQL 路径已有 |
| 重写 i18n | 已有 i18n-context.ts，只需确保一致使用 |
| 添加 E2E 测试 | 已有 Playwright 配置，优先补单元测试 |
