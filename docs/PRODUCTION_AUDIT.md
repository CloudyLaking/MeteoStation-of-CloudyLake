# 生产环境审计基线（PRODUCTION AUDIT）

> 建立时间：2026-08-18 17:10 CST（09:10 UTC）
> 审计方式：只读检查（本地仓库、生产服务器、服务状态、数据目录、日志、公开 API）
> 下一期审计：每阶段完成后更新本文件并附日期。

## 1. 版本基线

| 项目 | 值 |
| --- | --- |
| 本地 Git 提交 | `0784b24`（main = origin/main，"style: enlarge weather map interface typography"） |
| 本地未提交改动 | web/app.py、styles.css、index/forecast/observations/sounding-forecast/about/colorbar-translator.html、observations.js（再分析边界校验、站点地图省市边界、CSS 收敛等，属进行中工作） |
| 生产部署位置 | `/opt/meteostation`（**不是 Git 检出**，历史上通过 tarball 部署，无 version.txt、无 releases/<commit> 结构） |
| 生产版本标识 | 无（需修复，见阶段十二） |

## 2. 服务器资源

| 指标 | 值 |
| --- | --- |
| 主机 | Alibaba Cloud Linux 8（内核 5.10.134-17.al8），x86_64 |
| 内存 | 3.5 GiB 总量，2.1 GiB 可用，Swap 2.0 GiB（已用 596 MiB） |
| 磁盘 | /dev/vda3 40 GB，已用 23 GB，剩余 15 GB（61%） |
| 负载 | 0.13 / 0.68 / 0.58，uptime 21 天 |
| 数据目录占用 | data/raw 7.0 GB（ecmwf_forecast 4.9 GB、wis2_soundings 1.6 GB、wyoming 541 MB、ecmwf 123 MB、era5_climatology 1.9 MB、cyclones 68 KB）、previews 21 MB、geo 7.3 MB、state 1.4 MB、products 空 |

## 3. systemd 服务与 timer

| 单元 | 状态 | 说明 |
| --- | --- | --- |
| meteostation-web.service | active (enabled) | FastAPI/uvicorn :8765 |
| meteostation-forecast-collector.service | active (enabled) | IFS/AIFS 周期采集 |
| meteostation-global-sounding-collector.service | active (enabled) | 全球三天探空回填 |
| meteostation-wis2-sounding-collector.service | active (enabled) | WIS2 实时 TEMP 采集 |
| meteostation-weather-map.service | inactive（disabled，由 timer 触发） | 天气图分析（oneshot） |
| meteostation-weather-map.timer | active (enabled) | 上次 17:01，下次 18:00（每小时） |
| 失败单元 | 0 | — |

## 4. IFS/AIFS 预报缓存（问题确认区）

- 磁盘上实际文件（4.9 GB 目录内）**只有** 2026-08-17 18Z 一个时次：
  - ifs 18Z：surface 380 MB + pressure 3.07 GB
  - aifs 18Z：surface 202 MB + pressure 1.42 GB
  - 每个时次两模式合计约 5.07 GB
  - 另有 1 个残留 `aifs_20260817_12z_forecast_surface_144h_6hourly.grib2.part.resume`
- 状态文件 `data/state/forecast_collector.json`：
  - 114 个条目，其中 **104 条声明 complete**，但对应文件已被 `prune_forecast_cycles` 删除（状态与文件系统不一致，确认存在）
  - aifs 2026-08-18 00Z 为 waiting（Google storage 404，尚未发布）
- **线上 500 根因**（2026-08-18 13:04:33，7 天内共 2 次）：
  请求 `/api/v1/forecast/surface/58362?model=ifs` → `_latest_cached_forecast_cycle`
  扫描目录命中 `ifs_20260812_18z` → 采集器同时执行 `prune_forecast_cycles` 删除该文件
  → `extract_surface_forecast` → `read_fast_point_fields` 抛出 `FileNotFoundError`
  → 该段代码没有 try/except（TOCTOU 竞争 + 异常未捕获）→ 500。
- 采集器在磁盘不足时 `pre_download_rotation` 先删旧周期，删除时不保护
  "最后一个完整周期"，也不更新状态 JSON 的 complete 声明。
- **容量测算**（按真实文件大小）：IFS 周期 ≈ 3.45 GB，AIFS 周期 ≈ 1.62 GB。
  每模型保留 4 个周期需 ≈ 20.3 GB；保留 8 个周期需 ≈ 40.6 GB（超出整盘 40 GB）。
  **未扩容前策略：每模型 current + previous 共 2 个完整周期 ≈ 10.2 GB**；
  若需每模型 4 个周期，数据盘需扩至 ≥ 80 GB。

## 5. 天气图

- 最新有效时次：2026-08-18 00Z，cycle 00，status complete（timer 每小时运行）。
- **全部输出为 development-preview**，写在 `/previews/weather_maps/...`；
  `data/products/weather_maps/catalog.json` 不存在/为空。
- 配置 `weather_map.json`：`publication_allowed=false`，
  `base_map.status=official-service-selected-review-pending`，
  `service_review_number=GS（2024）0568号`，`thematic_map_review_status=pending`。
- 已知上游问题：NRL 台风 ATCF 域名解析失败（`science.nrlmry.navy.mil` NameResolutionError），不影响主图产出。
- 首页当前静默展示开发预览（阶段八合规项）。

## 6. 探空资料

- Wyoming（weather.uwyo.edu 清单，fetched 08:53Z）：追踪 3926 条目（3830 archived / 96 waiting）；
  最近时次约 520 站/时次；中国站（如 54511、58362）每时次 4 个要素档。
  原始目录 `data/raw/wyoming/2026`：7,660 个文件，仅 07–08 两个月。
- WIS2：连接正常，download_count 842,992、累计 10.96 GB、error_count 2,358
  （最近错误 "Server disconnected"）。
  原始目录 `data/raw/wis2_soundings/2026`：**247,236 个文件，跨度 2026-03 至 08** ——
  三天保留策略失效（阶段六问题），且 WIS2 目前只归档原始报文，未解码为统一廓线。
- 未来时间报文/异常报文计数：**未记录**（需在健康系统补齐）。
- 公开探空接口仍从 Wyoming 本地缓存读取。

## 7. 公开 API 响应时间（2026-08-18 09:10 UTC 实测）

| 接口 | 状态 | 耗时 |
| --- | --- | --- |
| `/`（首页 HTML） | 200 | 93 ms |
| `/api/v1/status` | 200 | 20 ms |
| `/api/v1/forecast/cache/status` | 200 | 46 ms（27 KB） |
| `/api/v1/forecast/surface/58362` | 200 | 2,128 ms（首次） |
| `/api/v1/forecast/sounding/58362?step=24` | 200 | 165 ms |
| `/api/v1/observations/series/58362?mode=past24h` | 200 | 31 ms（热缓存） |
| `/api/v1/observations/realtime/58362` | 200 | 2,668 ms（q-weather 直查） |
| `/api/v1/soundings/58362?date=...&hour=00` | 200 | 53 ms |
| `/api/v1/weather-maps/latest` | 200 | 41 ms |

## 8. 首页资源

- HTML 15.7 KB + app.js 98.0 KB + site.js 5.4 KB + styles.css 109.1 KB + logo 34.6 KB
  ≈ 253 KB（未压缩），**无 gzip/Brotli、无内容哈希、无 immutable 缓存**；
- MiSans VF.ttf 20 MB（未分包、未转 WOFF2，经 FastAPI 路由提供）；
- 关键资源总量当前 < 3 MB，但无压缩与缓存策略（阶段五）。

## 9. 错误率与访问统计

- 近 7 天：500 共 2 次（均为预报文件竞争），404 以机器人探测为主（/error.php 等）。
- traffic.json（2026-08 月累计）：requests 152,256；2xx 64,530；**4xx 87,423（57%，机器人）**；
  5xx 28；3xx 275；响应 6.29 GB；monthly_page_views 92,510（含非页面路由，统计口径需修正）。

## 10. 测试基线

- 本地：`69 passed, 306 warnings in 44.74s`（冷）/ 6.22s（热）。
- 警告来源：NumPy 2.5 shape-set 弃用（`fast_store.py:341/358`）、
  Matplotlib 3.11 `interval_contains`（metpy skewt）、xarray `data[key]=value` 弃用。

## 11. Nginx 与安全

- nginx/1.24.0（含 gzip_static 模块，**无 brotli 模块**），TLS 由 Certbot 管理。
- 全部流量 `proxy_pass http://127.0.0.1:8765`；**无 /static 直接服务、无 gzip 配置、
  无 HSTS/CSP/X-Content-Type-Options/Referrer-Policy/Permissions-Policy**。

## 12. 阶段验收对照（P0 完成后复核，2026-08-18 17:45 CST）

| 验收项 | 状态 |
| --- | --- |
| 1. IFS/AIFS 查询 200 且无静默过期 | ✅ 120/120 次查询 200；响应携带 meta（起报时次/资料年龄/降级） |
| 2. 更新缓存期间连续请求无 500 | ✅ 回填下载期间 120 次连续查询零 500；结构化 503 替代 |
| 3. `/health/ready` 数据过期时正确失败 | ⏳ 待阶段四健康系统 |
| 4. 首页首屏资源 < 3 MB | ✅ 253 KB（但无压缩/缓存/字体分包，阶段五处理） |
| 5. 全部基准尺寸无重叠 | 未测（阶段九截图回归） |
| 6. 24h 实况缓存 1 秒内返回 | ✅ 31 ms（热缓存） |
| 7. WIS 未来报文隔离 | ❌ 未实现（阶段六） |
| 8. 公开天气图非未标识预览 | ❌ 未实现（阶段八） |
| 9. 天气图置信等级有案例验证 | ❌ 未实现（阶段七） |
| 10. 统一模板与设计系统 | ❌ 未实现（阶段九） |
| 11. 一键回滚 | ✅ 已有 tarball 回滚点 + OPERATIONS.md 步骤；releases/<commit> 结构待阶段十二 |
| 12. 文档与线上一致 | ✅ 审计基线已建，P0 后已更新 |

## 13. P0 部署记录

- 部署提交：`2f8d8ba`（本地 main = origin/main）。
- 回滚点：`/opt/backups/meteostation/pre-p0-20260818-1726.tar.gz`。
- manifest 引导：ifs/aifs current 均指向 2026-08-17 18Z，previous 空。
- 生产 `.leases` 目录属主已修正为 meteostation:meteostation。
- 已知遗留：aifs 12Z 回填（previous 周期）在常驻采集器中继续下载；
  完成后 manifest previous 自动填上。
