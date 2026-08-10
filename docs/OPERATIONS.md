# 探空与地面实况运行说明

更新日期：2026-08-03

## 进程职责

项目将网页服务与资料采集分开：

```text
run_collector.py
  ├── 检查新时次
  ├── 获取并保存原始资料
  ├── 解析和质量检查
  └── 更新归档与运行状态

run_web.py
  ├── 读取本地原始资料缓存
  ├── 提供交互探空所需数据
  ├── 提供 q-weather 逐小时与实时观测查询
  └── 提供交互式地面实况与图像导出
```

这样即使 Wyoming 或网络暂时不可用，已经归档的网页和图片仍可正常打开。

## 本地运行

终端一：

```powershell
.\.venv\Scripts\python.exe run_collector.py
```

终端二：

```powershell
.\.venv\Scripts\python.exe run_web.py
```

采集器默认每 300 秒运行一轮。停止时按 `Ctrl+C`。

## 站点配置

配置文件：`config/sounding_collector.json`

```json
{
  "poll_interval_seconds": 300,
  "lookback_hours": 24,
  "request_spacing_seconds": 2,
  "generate_static_products": false,
  "cycles": ["00", "12"],
  "stations": [
    {
      "wmo_id": "58362",
      "name": "上海宝山",
      "name_en": "Baoshan, Shanghai",
      "enabled": true,
      "priority": 10
    }
  ]
}
```

- `poll_interval_seconds`：两轮检查的间隔，不得低于 60 秒。
- `lookback_hours`：每轮检查最近多少小时的标准时次。
- `request_spacing_seconds`：实际访问外部来源后的最小间隔。
- `generate_static_products`：是否生成服务器端派生图；当前固定为 `false`，网页使用浏览器交互图。
- `priority`：同一时次内优先处理较高数值的站点。

全球站表完成前，不应手工一次加入数千站并高频轮询 Wyoming。

## 存储结构

```text
data/
├── raw/wyoming/YYYY/MM/DD/
│   ├── 58362_00.csv
│   └── 58362_00.json
└── state/sounding_collector.json
```

这些运行数据已被 `.gitignore` 排除，不进入代码仓库。正式服务器需要单独备份。

## 缺测和退避

资料尚未到达或外部服务暂时失败时，采集器保存失败状态，并按以下间隔重试：

```text
5 分钟 → 10 分钟 → 20 分钟 → 40 分钟 → 60 分钟
```

成功归档后，该站同时次标记为已归档，后续轮次直接跳过。

## 原始归档与派生图

原始 CSV 是可追溯资料，不随界面更新删除。当前关闭服务器端探空 PNG/JSON 生成，旧 `data/products/soundings/` 已清理；Skew‑T 与 Stüve 由浏览器根据归档数据实时绘制和导出。`data/raw/` 和来源元数据始终不进入派生产品清理范围。

## 气象站实况查询

`/observations` 不建立地面实况产品归档。用户可提交 WMO 站号、中文站名或“省份+站名”，也可从七个地区站点图直接选择。

1. “过去 24h”查询最新逐小时观测；
2. “历史日期”查询指定 UTC 日期；
3. 数值经标准化、缺测识别和时间排序后返回统一的逐小时序列；
4. 页面绘制交互式 SVG，并可导出 PNG；
5. 当天资料缓存一小时，历史资料缓存六小时，不保留地面图文件。

实时状态和逐小时序列分别标注观测时刻与资料来源。

## 天气图产品目录

`config/weather_map.json` 已定义综合、地面、850/500/200 hPa 五类环境场及其字段配方。热带气旋、低压、高压中心和主要探空站是环境场上的叠加信息，不是单独产品。`/api/v1/weather-maps/jobs` 给出每层任务及阻塞原因，`/api/v1/weather-maps/products` 只读取 `data/products/weather_maps/catalog.json` 中的已保存产品；在合规地图合成和本站专题地图审图完成前不会发布自绘边界。

### 天地图服务配置

复制环境变量示例并填入从天地图申请的、限制到本站域名的令牌：

```powershell
Copy-Item .env.example .env
# 编辑 .env：TIANDITU_TOKEN=你的域名受限令牌
```

`run_web.py` 和 `run_weather_map.py` 都会读取项目根目录 `.env`。令牌不得提交到 Git。配置后，天气图任务会获取并缓存 `vec_w`、`cva_w`、`ibo_w` 官方瓦片，将 Web Mercator 瓦片重采样到天气图经纬网格，再把境界和注记置于环境场之上。`GS（2024）0568号` 是底层在线地图服务的来源审图号；本站叠加气象专题内容后的地图仍需按实际发布用途送审，未取得本站审图号前不得把 `publication_allowed` 改为 `true`。

无需令牌即可使用仓库根目录的 `中国_省.geojson` 绘制本地边界预览。任务会校验其 CRS、要素结构、坐标范围和 SHA-256；当前登记值为 EPSG:4490、42 个要素、`3af8294f9ad61cc2bf84c1bb7e4bbf86a6336c68d754b699a0e6ddc33ef81486`。替换该文件后必须同步更新 `config/weather_map.json` 中的哈希和来源记录。

### ECMWF Open Data 预报缓存

2026-07-27 实测确认当前账户没有 `services/mars` 权限；`ecmwfapi` 身份认证成功并不赋予 MARS 服务权限。预报后端因此固定为 `open-data`，按变量、层面和时效读取全球0.25° GRIB消息。凭据仍只保存在用户目录的 `.ecmwfapirc`，不得写入项目配置、日志或提交记录。

预报监测器每 60 秒检查 00/06/12/18 UTC 四个时次，并按起报时次交错处理
AIFS 与 IFS，避免首次回填时长时间只有一个模式可用：

- IFS：地面和11个等压面，`0—144 h / 3 h`；
- AIFS：地面和11个等压面，`0—144 h / 6 h`；
- 每个模式只保留最新四个完整周期，约等于一天；
- 网页接口只读本地缓存，缺少周期时返回“尚未缓存”，不会同步下载。

先执行单次检查；首次运行会尝试补齐配置中应保留的最近四个周期：

```powershell
.\.venv\Scripts\python.exe run_forecast_collector.py --once
```

持续监测：

```powershell
.\.venv\Scripts\python.exe run_forecast_collector.py
```

状态保存在 `data/state/forecast_collector.json`，也可读取 `/api/v1/forecast/cache/status`。生产端默认使用 ECMWF 的 Google Cloud 官方镜像，数据内容和许可仍属于 ECMWF Open Data。
网页选择的起报尚未缓存时，接口优先查找不晚于所选时次的最近完整同模式周期。单点预报属于最新业务产品；若旧书签中的起报已退出轮换缓存，则继续使用当前最新完整周期，并在页面显示实际起报。返回资料中的 `initialized_at` 始终是真实时次，不伪装为所选时次。
下载中的周期使用 `.part` 与 `.part.resume` 保存连续的已选 GRIB 字节；服务或网络中断后会按 Open Data 索引裁剪已完成范围继续下载，不会把完整周期前已经落盘的数据重新下载。

完整地面与等压面 GRIB 到齐后，采集器默认将其流式转换为相邻的 `*.fast.nc` 分块随机访问文件。转换先写入 `.part`，字段、维度与格式标识校验通过后再原子替换；随后才删除对应 GRIB 及 cfgrib 索引。网页的站点或任意经纬度查询只解压覆盖目标格点的空间块。`convert_to_fast_store` 或 `discard_grib_after_conversion` 仅用于故障诊断，生产配置应保持为 `true`。

按2026-07-27 00 UTC实际索引估算，IFS每周期约1.67 GiB，AIFS每周期约0.82 GiB；八组配对周期约20 GiB。每天四次完整更新产生约10 GiB下载流量。应至少预留30 GiB磁盘，若还要长期归档，应另设低成本对象存储；不要无限保留全球原始场。

ECMWF 输入计划可在不下载资料的情况下检查：

```powershell
.\.venv\Scripts\python.exe run_weather_map.py --date 2026-07-26 --cycle 00
```

安装 `requirements-weather-map.txt` 后可添加 `--download`，只获取当前有效时次必需的地面 GRIB 与 850/500/200 hPa 等压面 GRIB；MARS 请求将范围限制为 `65—150°E、10—65°N`，为最终地图四周保留5°缓冲。添加 `--include-cyclone-tracks` 才会同时请求可选的 ECMWF 热带气旋 BUFR。00 UTC 有效场自动请求前一日 12 UTC 起报的 `step=12`，12 UTC 有效场自动请求当日 00 UTC 起报的 `step=12`。资料按实际起报日期写入 `data/raw/ecmwf/YYYY/MM/DD/`，并保存哈希、许可、请求参数和实际访问后端；网页访问不会临时下载天气图。

已有完整地面与等压面 GRIB 时，可生成四类带本地省界的开发预览：

```powershell
.\.venv\Scripts\python.exe run_weather_map.py `
  --date 2026-07-26 `
  --cycle 00 `
  --download-climatology

.\.venv\Scripts\python.exe run_weather_map.py `
  --date 2026-07-26 `
  --cycle 00 `
  --render-preview
```

也可以在一次任务中下载并渲染：

```powershell
.\.venv\Scripts\python.exe run_weather_map.py `
  --date 2026-07-26 `
  --cycle 00 `
  --download `
  --download-climatology `
  --render-preview
```

`--download-climatology` 只在目标月份的 ERA5 1991—2020 月平均 500 hPa 高度文件不存在时请求 Copernicus CDS；已有文件时直接复用。500 hPa 填色必须有该常值场，缺失时任务会明确失败，避免把涡度或未订正高度误标为高度距平。

预览写入被 Git 忽略的 `data/previews/weather_maps/`，目录接口为：

```text
/api/v1/weather-maps/previews?date=YYYY-MM-DD&cycle=00&layer=500
```

`--render-preview` 默认刷新 NRL ATCF active warnings，将原始页面和警报归档到 `data/raw/cyclones/YYYY/MM/DD/HH/`，再把最接近分析时次的热带气旋位置叠加到所有环境场。若 NRL 暂时不可访问或本次未取得可用警报，任务自动读取该时次已经归档的 `.wrn`；只有明确不需要气旋叠加时才添加 `--skip-cyclone-overlays`。客观低压和高压中心从平滑后的海平面气压或本层位势高度场识别，属于算法分析而不是权威 best track。

这些图仅用于检验场值、等值线、填色、风羽、天地图省界、南海诸岛小图和态势标记。它们还不含城市、水系或完整在线底图，固定标注不可发布，也不会写入 `data/products/weather_maps/`。每次重绘会替换相同层面和有效时次的旧目录项，不累计重复产品。若出现“缺少 cfgrib/eccodes”，先安装 `requirements-weather-map.txt`。本机已用前一日 12 UTC 起报的 ECMWF `+12 h` 场生成 2026-07-26 00 UTC 四层预览，并叠加 `11W NOUL`；主页在正式产品缺失时会读取对应开发预览。

主页探空站目录来自 `config/china_sounding_stations.json`，当前为 Wyoming 在 2026-07-26 00 UTC 实际发布的 88 个中国站。`GET /api/v1/weather-maps/sounding-stations?date=YYYY-MM-DD&cycle=00` 一次性返回本地已有归档的站点廓线；前端据此把所有站画成无框小圆点，并只为已有资料的站补充站点填图。该接口不触发外部下载，后台 `run_collector.py` 仍只自动采集配置中的宝山 `58362`。

## 交互探空订正

`GET /api/v1/observations/hourly/{station_id}?time=YYYY-MM-DDTHH:00:00+08:00` 读取指定北京时间整点。网页以该小时的本站气压、温度和湿度计算露点，再调用 `POST /api/v1/soundings/{station_id}/correct?date=YYYY-MM-DD&cycle=00`。服务端插入临时地面层并重算气块廓线、CAPE/CIN、LCL/LFC/EL、PWAT、LI、K、TT、零度层、风切变和温度递减率。该接口不改写 `data/raw/`；网页“恢复原始”可立即撤销当前订正。

## 历史再分析查询

`/reanalysis` 使用 CDS API 即时请求 ERA5 小区域 NetCDF。生产服务以 `meteostation` 用户运行，因此凭据应安装为 `/home/meteostation/.cdsapirc`，权限设为仅该用户可读；不要写入仓库或应用日志。部署后先以服务用户执行一个小区域、单时次、单变量测试，再开放页面。

每个查询只在系统临时目录保存下载文件，解码并生成响应后自动删除。网页层限制最大经纬跨度、最多两个并发任务、任务状态保留一小时，并拒绝通常尚未进入 ERA5 归档的最近五天。CDS 排队时间不属于应用计算耗时，应在监控中与解码失败分开判断。

## 当前限制

- Wyoming 没有更新推送，只能由后台探测。
- 当前只配置一个已验证站点，尚未形成全球站表。
- 当前交互图包括英文 Skew‑T/Stüve、湿度云带、风速带、虚温、气块线、LCL/LFC/EL、零度层、CAPE/CIN 和图内右侧诊断列；还未加入异常高低值、逆温层和干湿层标注。
- 采集状态目前使用 JSON 文件；多实例部署前应改为数据库或带锁的任务状态存储。

## WIS 2.0 全球实时探空

生产服务器已订阅 WIS 2.0 Global Broker：

```text
MQTT 通知
  → 读取通知中的 canonical 下载地址
  → 下载 BUFR
  → 解码并匹配站点/时次
  → 复用现有归档、统一模型和出图流程
```

运行状态：

```bash
systemctl status meteostation-wis2-sounding-collector
systemctl status meteostation-global-sounding-collector
```

WIS2 原始 BUFR 位于 `data/raw/wis2_soundings/`，Wyoming CSV 回填位于
`data/raw/wyoming/`，均采用三天滚动策略；宝山 `58362` 的旧归档不随全球
清理器删除。WIS2 连接状态记录在
`data/state/wis2_sounding_collector.json`。

回填器每小时读取 Wyoming 最近 72 小时六个 00/12 UTC 时次的
`sounding_json` 实际站表，只请求对应时次确实发布的五位 WMO 站。部署时
三天并集为 664 站、约 3301 个实际站次；按逐秒高分辨率 CSV 与 BUFR
实测大小预计约 0.4—0.8 GB，为元数据、状态和临时文件预留 1—2 GB。
