# Release Closeout Runbook（2-5 天）

以 2026-03-08 为起点，这份 runbook 用于完成 Beta 发布前最后 3 个收口动作：

1. Ubuntu 干净机首跑复测（Quickstart + Docker）
2. 两轮干净环境发布演练
3. 主干 CI 连续稳定窗口观察（1-2 个提交窗口）

## Day 1：Ubuntu 干净机首跑复测

本地或 GitHub Actions Ubuntu 环境执行：

```bash
bash scripts/release_rehearsal_round.sh --round round-1
```

该命令会自动执行：

- `.env.example` -> `.env`（临时）
- `bash scripts/check_local_mode.sh --env-file .env --skip-api`
- `bash scripts/quickstart.sh --exit-after-ready`
- `bash scripts/dev_local.sh up --build`
- Docker API/Web health
- `bash scripts/dev_local.sh verify-host --ci-parity`
- `STRICT_BENCHMARK=1 bash scripts/run_regression_benchmark.sh`

输出报告路径：`tmp/release-rehearsal/round-1/summary.md`

## Day 2-3：两轮干净环境发布演练

第二轮命令：

```bash
bash scripts/release_rehearsal_round.sh --round round-2
```

两轮都通过后，把以下条目勾选到 `docs/beta-release-checklist.md`：

- 首跑与启动 gate
- CI parity 与 strict benchmark gate
- Final release call 中的“两轮干净环境复跑”

报告路径：

- `tmp/release-rehearsal/round-1/summary.md`
- `tmp/release-rehearsal/round-2/summary.md`

## Day 4-5：主干 CI 稳定窗口观察

检查 `main` 分支最近 2 次完成态 CI 是否都成功：

```bash
GH_TOKEN=... bash scripts/check_ci_stability.sh \
  --repo zijinz456/OpenTutor \
  --branch main \
  --workflow ci.yml \
  --windows 2
```

如果你已 `gh auth login`，可省略 `GH_TOKEN`。

## 一键自动化（推荐）

可通过 GitHub Actions 手动触发：

- workflow: `.github/workflows/release-readiness.yml`
- 内容：自动跑两轮 Ubuntu 干净环境演练，并可选执行 CI 稳定窗口检查。

