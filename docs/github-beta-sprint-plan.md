# OpenTutor GitHub Beta 冲刺计划（7-14 天）

目标：把项目从可展示原型收敛为“外部技术用户 30 分钟内可跑通”的准稳定 Beta。

## Definition of Done

满足以下条件即视为可对外发布 Beta：

1. 陌生用户按 README Quickstart 或 Docker 文档，在 macOS/Linux 上可完成首跑。
2. API 与 Web 在默认端口均 ready（或按自定义端口 ready）。
3. 主干 CI 全绿，且本地 `verify-host --ci-parity` 与 CI 口径一致。
4. strict benchmark gate 可审计可失败，不允许“空评测绿灯”。
5. 已知限制与实验性能力在 README 前置说明。

## 冲刺节奏

### Day 1-3：首跑链路与脚本可移植性

- [ ] 脚本 Bash 3.2 兼容（macOS 默认 Bash）
- [ ] `bash scripts/quickstart.sh` 在本机与 Ubuntu 干净环境通过
- [ ] 阻断错误具备“缺什么 + 怎么修”的可执行提示
- [ ] README Quickstart 增补平台矩阵、耗时、依赖、排障入口

验收命令：

```bash
bash scripts/check_local_mode.sh --env-file .env --skip-api
bash scripts/quickstart.sh
```

### Day 4-7：CI / Local 口径统一与覆盖率策略

- [ ] `pytest.ini` 覆盖率门槛临时设置为 `25`
- [ ] CI 增加 gate consistency 检查（防止 `-o addopts=` 绕过）
- [ ] `verify-host` 增加 `--ci-parity` 并作为发布前必跑项
- [ ] 文档明确下一阶段目标回升 `30+`

验收命令：

```bash
bash scripts/dev_local.sh verify-host --ci-parity
```

### Day 8-10：strict benchmark gate 落地

- [ ] `run_regression_benchmark(strict=True)` 时，retrieval/recovery 被 skip 记为失败
- [ ] CI API smoke benchmark 使用 strict 模式 + 固定 fixture
- [ ] strict 模式失败原因可直接审计

验收命令：

```bash
apps/api/.venv/bin/python -m pytest tests/test_eval_regressions.py -q -o addopts=
apps/api/.venv/bin/python -m pytest tests/test_api_integration.py -k "regression_benchmark" -q -o addopts=
```

### Day 11-14：发布演练与收尾

- [ ] 干净环境复跑 2 轮（不复用旧缓存/旧数据）
- [ ] `docs/beta-release-checklist.md` 全部勾选
- [ ] CI 绿灯后打 Beta tag
- [ ] 发布说明包含已知限制与实验性能力

验收命令：

```bash
bash scripts/dev_local.sh verify-host --ci-parity
STRICT_BENCHMARK=1 bash scripts/run_regression_benchmark.sh
```

## 风险控制

1. 范围冻结：本轮不引入新产品能力，只做稳定性与可运行性收敛。
2. 平台冻结：只承诺 macOS + Linux，Windows 明确列为非首要支持。
3. 质量冻结：覆盖率门槛本轮 25，下一轮明确回升到 30+。
4. 发布冻结：未通过 checklist 与两轮干净环境复跑，不允许打 Beta tag。

## 配套文档

- `README.md`
- `docs/local-single-user.md`
- `docs/agent-eval-regression.md`
- `docs/beta-release-checklist.md`
- `docs/release-closeout-runbook.md`
