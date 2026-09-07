# 更新日志（CHANGELOG）

## V3.0.0 · 2026-09-06 — 天气图重绘与全球、区域输出

- 保留页面布局，重写天气图配色、图幅、统一字号和标注避让；气旋详细资料回到图下注释。
- 地面层增加有明确累计时段的 IFS 降水；统一图例单位，遮罩地下气压面，不向全球外推中国气候态。
- 全球与华东近海生成独立的五层产品，支持管理员指定经纬度范围；复用原始资料并控制归档保留期。
- 修正气旋跨海盆来源、未来时刻筛选和 NRL 预报位置误用；保留 JTWC 风速为节。
- 自动诊断仍明确标为候选，不声明已通过人工分析或专题地图审查。

## V2.4.1 · 2026-08-31 — 天气图分析界面收口

- 天气图分析改为紧凑的无框主画布，探空工具以细分隔线并列，移除标题上下的说明性口号。
- 集合、台风与历史相似页面同步移除大标题上下的小标题，并统一压低标题字号。
- 所有公开 HTML 页面禁止缓存旧发布内容，静态资源更新版本标识，避免新旧界面交替出现。

## V2.4.0 · 2026-08-31 — 紧凑界面与气象产品实用化

- 全站标题与页面间距收紧，修正顶栏状态方格的实际网格列宽和视觉中心。
- 探空新增逆温、湿层、干层、低空急流和对流层顶候选识别，显示范围、强度与可信度；图内标题改为中文。
- IBTrACS 相似案例新增目标与前五案例路径叠加，并把案例日期和路径范围联动到 ERA5。
- ERA5 按要素使用专用色标、自动等值线间隔和中文悬停；风速场叠加抽稀风矢量。
- 色条刻度改用自适应阈值，同时识别浅底深字和深底浅字，按单调性与字符置信度自动选择结果。
- AIFS ENS 与 WeatherNext 2 已验证 360 小时真实逐点集合；WNC 增加严格来源校验的派生轨迹和聚类展示契约。
- 生产侧只长期保存轻量派生产品和 0.9 MB 的西北太平洋 IBTrACS 压缩索引。

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

## V2.3.1 · 2026-08-18 — 分层健康监控与真实页面统计

### 新增
- `/health/live`、`/health/ready`（数据过期返回 503）、`/health/data`、`/metrics`。
- `meteostation/health.py`：HealthMetrics 持久化计数器、q-weather 观察者、
  数据新鲜度聚合、机器人 UA 识别。
- 首页三格状态综合“服务器资源 + 资料可用性”，过期资料不再显示绿色。
- 页面浏览只统计成功真实页面路由，排除 404/机器人/静态/API，
  匿名会话 Cookie 每日去重；历史膨胀计数已清零。
- 测试 +13（96 全通过）。

## V2.2.1 · 2026-08-10 — 快速资料读取、全球选站与历史再分析工作台

（详见 `docs/PROJECT_STATUS.md` 历史完成记录）
