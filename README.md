# 云海观象台

云海观象台（CloudyLake's Observatory，项目仓库名为 MeteoStation of CloudyLake）是一个个人气象资料站，集中展示探空、地面实况、数值预报、天气分析图和历史再分析工具。生产站点：[https://meteostation.top/](https://meteostation.top/)。

本文件是项目总说明，也是当前状态的唯一权威文档。代码、配置、数据源、页面、接口、部署方式或待办发生变化时，必须在同一次修改中同步更新 README。不能只改代码而留下失效说明。版本变化另记于 `CHANGELOG.md`。

## 当前状态

- FastAPI 后端加原生 HTML、CSS、JavaScript 前端，交互图主要由浏览器绘制；生产目录为 `/opt/meteostation`。
- 天气分析图为 V3 系列，包含综合、地面、850、500 和 200 hPa，支持中国、全球、华东和管理员自定义区域。
- 探空主链路为 WMO WIS 2.0 实时 TEMP/TEMP-SHIP，Wyoming 用于近三天回填和公开历史查询。
- 单点预报读取本地 ECMWF IFS/AIFS 缓存；ERA5 历史再分析按需下载，解码后清理临时文件。
- 自动高低压、锋面和槽脊只是客观诊断候选，不是官方天气分析或预警。
- 中国专题天气图审图状态仍为 `pending`；天地图底图服务审图号不能代替本站专题图审图号。

## 页面入口

| 地址 | 内容 |
| --- | --- |
| `/` | 首页与最新资料 |
| `/analysis?region=china` | 中国天气分析图 |
| `/analysis?region=world` | 全球天气分析图 |
| `/analysis?region=east-china` | 华东及近海天气分析图 |
| `/observations` | 地面实况 |
| `/forecast`、`/sounding-forecast` | 单点预报、预报探空 |
| `/reanalysis` | ERA5 历史再分析 |
| `/ensemble`、`/cyclones` | 集合预报实验页、热带气旋 |
| `/history/similar` | 历史相似气旋 |
| `/colorbar-translator` | 色条提取和格式转换 |
| `/about`、`/admin` | 网站说明、管理入口 |

Nginx 同时接受 `meteostation.top` 和 `www.meteostation.top`，目前没有互相做 301 跳转。项目以较短的裸域名为正式地址；访问它不会自动出现 `www`，这是配置选择，不是 DNS 或证书异常。

## 架构和目录

```text
WIS 2.0 / Wyoming / q-weather / METAR / OGIMET
ECMWF Open Data / CDS ERA5 / UCAR TCGP
                         │
                         ▼
后台采集与解码 ──> data/raw、data/state、data/products
                         │
                         ▼
                 FastAPI 只读接口
                         │
                         ▼
                  浏览器页面与交互图
```

网页请求不承担大文件下载。采集器先保存原始资料、来源、时间和校验信息，再生成网页数据。临时计算与归档分开，原始观测不随页面改版删除。

| 路径 | 用途 |
| --- | --- |
| `meteostation/` | 探空、观测、预报、天气图、ERA5、气旋等领域代码 |
| `web/` | FastAPI 应用和静态资源 |
| `config/` | 站表、天气图配方、地图和运行配置 |
| `deploy/` | systemd、Nginx、日志和部署文件 |
| `tests/` | 自动化测试 |
| `data/raw/` | 原始资料，不进入 Git |
| `data/state/` | 状态、清单和锁，不进入 Git |
| `data/products/` | 生成产品，不进入 Git |
| `run_*.py` | 各任务入口 |
| `中国_省.geojson` | 中国境界预览数据 |

## 数据来源和边界

### 探空与地面观测

- WIS 2.0 Global Broker 是实时探空主链路，订阅 TEMP/TEMP-SHIP 通知并按 canonical 链接保存 BUFR。
- Wyoming `sounding_json` 用于回填和历史查询。回填器按实际时次站表请求，不用静态全球站表盲扫。
- 中国天气图站点目录来自已核验的 Wyoming 中国站快照。接口只读本地归档，访客点击不触发外部下载。
- 原始 CSV/BUFR 和来源元数据保留；Skew-T、Stüve、风羽、诊断量及导出图由浏览器生成。
- 中国地面逐小时和实时状态主要读取 q-weather，整点切换或空响应时回退上一完整整点。
- 全球站可用 OGIMET SYNOP，METAR 作为航空站补充；来源必须明确，不能混称同一种观测。
- 地面查询只短时缓存。探空地面订正插入临时层并重算诊断，不改写原始归档。

### 数值预报、再分析与气旋

- ECMWF Open Data 提供 IFS/AIFS。当前账号无 `services/mars` 权限，生产固定使用 Open Data 索引和官方镜像。
- 预报下载转为分块 NetCDF，以 `current/previous` 双槽和原子清单切换，避免网页读取半成品。
- 天气图 00/12 UTC 有效场通常使用上一个 ECMWF 起报周期的 `+12 h` 场；产品须写明起报、有效时间和时效。
- ERA5 经 CDS 按需临时下载，响应生成后删除；不能用预报冒充再分析。
- 中国距平可用 ERA5 1991—2020 同月气候态；该中国气候态不得外推到全球。
- 活动气旋优先读取 UCAR TCGP ATCF b-deck 镜像，按海盆识别 JTWC、NHC 或 CPHC；NRL 只作回退。
- 有编号气旋显示编号和符号。风速保留 `kt`，不转成 `m/s`，未来位置不作为当前实况显示。

## 天气分析图 V3

| 图层 | 产品重点 |
| --- | --- |
| 综合 | 850 hPa 温度距平填色、850 hPa 风羽、500 hPa 高度等值线、气旋和受控密度站模 |
| 地面 | 优先显示 ECMWF IFS 累计降水（mm），注明累计时段和“模式累计降水”；不可核验时才回退二米温度 |
| 850 hPa | 低层温度、湿度和风场，判断暖湿输送与低层结构 |
| 500 hPa | 位势高度及中层场，判断槽脊和环流形势 |
| 200 hPa | 高空风和辐散等场，判断急流与高层动力配置 |

地图为白底，青橙为主，紫罗兰、浅棕灰和墙红辅助。标题、图例、色条、站模和说明区统一版式。站点标签必须避碰并控制密度。综合站模对应 850 hPa 温度与露点、500 hPa 高度和 850 hPa 风；点击仍进入探空工作台。

- 全球图用 Natural Earth 海岸线和 1° 展示分辨率，原始 IFS 为 0.25°。
- 中国图继续用登记的中国境界资料，不以 Natural Earth 替换。
- 管理员可用 `--region 名称 --bounds 西 南 东 北` 生成区域。名称仅含小写字母、数字和连字符；范围至少 5°×5°，纬度限 ±80°，输入须覆盖图框。
- 全球图不运行只为中国或北半球区域设计的锋面、槽脊诊断，也不套用中国气候态。
- 图下注释须说明来源、起报和有效时间、单位、累计时段及自动诊断限制。

```powershell
python run_weather_map.py --date YYYY-MM-DD --cycle 12 --region china
python run_weather_map.py --date YYYY-MM-DD --cycle 12 --region world
python run_weather_map.py --date YYYY-MM-DD --cycle 12 --region east-china
python run_weather_map.py --date YYYY-MM-DD --cycle 12 --region custom-name --bounds 110 20 135 42
python run_weather_map_cycle.py
```

配置在 `config/weather_map.json`，区域校验在 `meteostation/weather_map/regions.py`，绘制入口在 `meteostation/weather_map/presentation.py`。不要恢复旧渲染函数，不要把自动诊断说成官方分析。

## 探空图与实验功能

探空工作台支持 Skew-T、Stüve、逐层读值、湿球温度、虚温、气块线、风羽、湿度/云带、风速带和 Ground-relative Hodograph。诊断含 LCL/LFC/EL、零度层、PWAT、LI、K、TT、温度递减率、分层风切变、SRH、Bunkers 风暴运动、临界角、SWEAT、固定层 STP，以及 SB/ML/MU CAPE/CIN 和 DCAPE。

诊断受缺层、观测误差和算法假设影响。页面和导出图必须保证文字不越界、不重叠，来源说明与真实链路一致；桌面和移动端都要截图检查。

- 色条工具支持连续/离散采样、边界调整、近色合并和 Matplotlib、Plotly、CSS、JSON、GMT/CPT 导出。
- 集合页只有读取真实 AIFS ENS 或 WeatherNext 2 成员后才展示，不能拼成虚构集合。
- WeatherNext Cyclones 只有核验来源后的 `data/products/cyclones/wnc-latest.json` 存在时才显示，否则标为未配置。
- 历史相似气旋是归档匹配工具，不能代替预报。

## 主要 API

| 接口 | 用途 |
| --- | --- |
| `/api/v1/health` | 应用健康检查 |
| `/health/live`、`/health/ready`、`/health/data` | 存活、就绪和数据新鲜度 |
| `/metrics`、`/api/v1/status` | 指标和模块状态 |
| `/api/v1/soundings/{station_id}` | 本地探空廓线 |
| `/api/v1/soundings/{station_id}/raw` | 原始探空 CSV |
| `/api/v1/soundings/{station_id}/correct` | 非破坏性地面订正 |
| `/api/v1/observations/realtime/{station_id}` | 地面实时状态 |
| `/api/v1/observations/series/{station_id}` | 地面时序 |
| `/api/v1/weather-maps/products` | 已生成天气图目录 |
| `/api/v1/weather-maps/jobs` | 天气图任务和阻塞原因 |
| `/api/v1/weather-maps/sounding-stations` | 天气图站点层本地资料 |
| `/api/v1/forecast/cache/status` | IFS/AIFS 缓存状态 |
| `/api/v1/forecast/surface/{location}` | 单点地面预报 |
| `/api/v1/forecast/sounding/{location}` | 单点预报探空 |
| `/api/v1/reanalysis/jobs` | 提交 ERA5 临时查询 |

完整参数以 `web/app.py` 和 FastAPI 接口定义为准。

## 本地运行和验证

建议 Python 3.11。Windows 开发地址为 `127.0.0.1:8765`，不要假定默认 8000 端口可用。

```powershell
cd MeteoStation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-web.txt
python run_web.py
```

按任务安装 `requirements-collector.txt` 或 `requirements-weather-map.txt`。后台入口包括 `run_collector.py`、`run_global_sounding_collector.py`、`run_wis2_sounding_collector.py`、`run_forecast_collector.py` 和 `run_weather_map_cycle.py`。

```powershell
python -m pytest -q
python -m pytest tests/test_weather_presentation.py -q
git diff --check
```

界面修改至少检查一个桌面和一个手机尺寸。天气图或探空图还须检查标题、坐标、图例、色条、注释、站模及极端值文字边界。

## 凭据、地图和部署

- `.env`、`.ecmwfapirc`、`.cdsapirc`、令牌、管理员凭据和 SSH 密码不得提交。
- 生产 SSH 账号和密码保存在本仓库上一级目录的 `SERVER_ACCESS.txt`。它位于 Git 工作树之外，只供本机运维；不要复制到 README、日志、Issue 或提交记录。
- CDS 凭据放在生产服务用户的 `/home/meteostation/.cdsapirc`。天地图令牌从 `TIANDITU_TOKEN` 读取并限制到实际域名。
- 中国底图来源为国家地理信息公共服务平台，服务审图号 `GS（2024）0568号`。这不能证明本站专题图已审；`publication_allowed=false` 须保持到合规流程完成。
- 替换 `中国_省.geojson` 后须重验 CRS、范围、要素结构、SHA-256 和来源记录。

部署前备份 `.env`、`data/`、当前提交号和程序目录，不要删除 `data/raw/`。更新后安装依赖、测试，再按改动范围重启：

| systemd 单元 | 职责 |
| --- | --- |
| `meteostation-web.service` | Web 服务 |
| `meteostation-sounding-collector.service` | 配置站探空采集 |
| `meteostation-global-sounding-collector.service` | Wyoming 全球回填 |
| `meteostation-wis2-sounding-collector.service` | WIS 2.0 实时探空 |
| `meteostation-forecast-collector.service` | IFS/AIFS 缓存 |
| `meteostation-weather-map.service` / `.timer` | 天气图生成与定时触发 |
| `meteostation-storage.timer` | 存储清理 |

```bash
cd /opt/meteostation
systemctl --no-pager --full status meteostation-web.service
systemctl --no-pager --full status meteostation-weather-map.timer
curl --fail http://127.0.0.1:8765/api/v1/health
curl --fail https://meteostation.top/api/v1/weather-maps/latest
journalctl -u meteostation-web.service -n 100 --no-pager
```

若以后统一为 `www` 或裸域名，应新增独立的 301 跳转 server block，并同步 canonical URL、站点地图、监控和证书验证；不能只改 DNS。

## 存储、限制和后续工作

- `data/raw/` 是备份重点；`data/state/` 保存状态、租约和清单；`data/products/` 可重建。清理派生产品不能连带删除原始资料。
- IFS/AIFS 各保留当前与上一完整周期。先清日志、临时文件和过宽限期的退役周期，再考虑缩减有效缓存。
- q-weather、Wyoming、OGIMET 等会受限流、格式变化和可用性影响，仍需完善熔断和告警。
- ECMWF 单条 GRIB 仍为全球 0.25° 场，不适合由网页高并发临时下载。ERA5 受 CDS 排队和归档时效影响，不可用时必须明确报错。
- 继续修正探空图文字碰撞、极端值边界、来源说明和移动端表现。
- 天气图继续逐例检查锋面与 H/L 避让、南半球风羽方向、500/200 hPa 色条刻度和 850 hPa 湿度超过 100% 时的表现。
- 中国专题图尚未取得本站审图号；完整天地图城市、水系和矢量底图取决于合规令牌与发布流程。

## 每次修改的检查清单

1. 同步更新 README 中的现状、接口、来源、部署和待办。
2. 来源、单位、时间含义及回退策略与代码一致；不把模式产品写成观测或官方分析。
3. 密钥、密码、原始数据、临时文件、截图和 `.qa` 文件没有进入 Git。
4. `git status --short`、`git diff --check` 和相关测试通过。
5. 界面已检查桌面与移动端；图形已打开真实成图核对。
6. 部署后核对服务、公开 API、静态资源版本和线上图片，排除旧缓存。
7. 回滚时恢复匹配的代码、依赖和配置，不覆盖原始资料。

如果 README 与代码不一致，应在修正代码或说明的同一次提交中恢复一致。不要再新建状态、部署、路线图或数据源 Markdown 文档来分散维护。
