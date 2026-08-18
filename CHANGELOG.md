# 更新日志（CHANGELOG）

## V2.3.0-P0 · 2026-08-18 — 预报缓存 manifest 化发布，消除线上 500

### 修复
- 修复预报周期状态与文件系统不一致导致的线上 500（TOCTOU：回退扫描与
  采集器剪枝竞争，`FileNotFoundError` 未捕获）。
- 修复磁盘不足时采集器删除最后一个完整周期、状态 JSON 仍声明 complete 的问题。
- 修复 12Z 回填完成后会把旧时次发布为 manifest current 的次序问题。

### 新增
- `meteostation/forecast/manifest.py`：manifest 原子发布（`set_slots` /
  `publish` / `mark_retired`）、深度校验 `validate_cycle_files`（变量、
  原生时次、气压层、721×1440 网格）、跨进程 flock 租约 `CycleLease`、
  `build_cycle_entry` 磁盘引导。
- 采集器：staging → 校验 → 原子发布 → 延迟退役（24 h 宽限期）流程；
  `storage-blocked` 状态；manifest current/previous 剪枝保护；
  手动 `--once` 引导（必须 `sudo -u meteostation` 运行）。
- Web：`_resolve_forecast_cycle` manifest + 文件系统交叉验证；
  单点/探空预报响应新增 `meta`（initialized_at / data_age_hours /
  degraded / max_stale_hours）；超过最大陈旧时间（IFS 18 h / AIFS 30 h）
  返回结构化 503；`/api/v1/forecast/cache/status` 交叉验证报告。
- 前端：单点与探空预报页显示实际起报时次、资料年龄与降级状态，
  结构化 503 的人类可读文案。
- 配置：`retain_complete_cycles=2`（每模型 current+previous ≈ 10.2 GB），
  `max_stale_hours`、`retire_grace_hours` 可调。
- 测试：+14 项（manifest 发布/校验/租约/剪枝保护/延迟退役、API 合约
  200/降级/结构化 503），全量 83 通过。
- 文档：新增 `docs/PRODUCTION_AUDIT.md` 审计基线、`CHANGELOG.md`；
  更新 `PROJECT_STATUS.md`、`OPERATIONS.md`。

### 部署
- 生产回滚点：`/opt/backups/meteostation/pre-p0-20260818-1726.tar.gz`。
- 验收：回填下载期间连续 120 次预报查询全部 200、零 500；
  宝山/北京/任意经纬度均返回完整资料。

## V2.2.1 · 2026-08-10 — 快速资料读取、全球选站与历史再分析工作台

（详见 `docs/PROJECT_STATUS.md` 历史完成记录）
