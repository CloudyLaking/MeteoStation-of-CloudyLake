# 天气图 V3.0

本次改动重写图形呈现与区域输出，保留分析页的栏目、选项栏及探空工作台位置。

## 产品与限制

- 综合：850 hPa 温度距平、850 hPa 风、500 hPa 高度线。只有气候态覆盖的中国及邻近区域使用 ERA5 1991—2020 同月平均；其他区域明确显示实际温度，不外推距平。
- 地面：优先显示 IFS 累计降水、海平面气压、十米风。GRIB 必须明确给出米单位、小时步长、累计起止步和匹配的有效时刻；转换毫米后显示。缺少可核验的降水则回退二米温度，不伪装成实测降雨。
- 850：湿度、风、等高线。高湿不代表正在降雨。
- 500：高度距平与环流；没有气候态时显示湿度与环流。
- 200：急流风速、等高线与风羽。

颜色阈值固定，避免每张图自动拉伸色标。地下气压面在平滑前遮罩并在平滑后重新遮罩。图内英文统一字号，气旋只标符号和编号，时效、名称及强度在网页既有图注区。等值线标注按实际文本包围盒避让气旋标注、其他等值线数字和南海附图。

H/L 采用八方向闭合极值筛选并避开高地和热带气旋位置；槽脊与锋面沿用原有区域诊断，限制数量并避开热带气旋附近。它们仍是自动诊断候选，未完成逐例独立气象检验，不应作为官方天气分析或预警。全球不套用现有北半球区域锋面、槽脊算法。专题地图审图状态仍为 pending，未改成已审。

热带气旋读取 UCAR TCGP 业务 b-deck 镜像，JTWC 负责的海盆使用 JTWC 资料，美洲海盆明确标 NHC/CPHC；选取图时刻之前六小时内的业务位置，风速保留 kt。NRL 备用源只允许警报分析位置，不把警报内未来预报位置当成实况。源不可用时不编造系统。

## 区域输出与存储

先生成中国图并下载公共源文件：

```sh
sudo -u meteostation .venv/bin/python run_weather_map.py --date 2026-09-06 --cycle 12 --download --render-preview
sudo -u meteostation .venv/bin/python run_weather_map.py --date 2026-09-06 --cycle 12 --region world --render-preview
sudo -u meteostation .venv/bin/python run_weather_map.py --date 2026-09-06 --cycle 12 --region east-china --bounds 105 18 135 43 --render-preview
```

任意自定义区域由管理员用 `--region 名称 --bounds 西 南 东 北` 生成。名称限小写字母、数字和连字符。范围至少 5° × 5°、纬度限制 ±80°，允许经度越过日期变更线，例如 `150 -30 210 30`。输入没有覆盖整个范围则拒绝制图。暂无公开任意范围即时计算接口，避免访客请求无限消耗服务器资源。

网址分别为 `/analysis`、`/analysis?region=world`、`/analysis?region=east-china`，其他已生成区域同样按 region 访问。地区输出独立目录和目录索引，不覆盖中国产品。

定时任务顺序生成中国、全球与华东近海。共用全球原始 GRIB；全球按 1° 抽样展示，不另存全球解码数组；仅追加降水 GRIB（本次样本约 700 KB）及 WebP/JSON。中国与两个预置区域延用三天日期归档清理；手动增加的区域需要管理员制定清理策略。区域失败不撤回已生成中国图，也不重复下载全套场。

## 参考资料

- [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) 与 [官方下载客户端](https://github.com/ecmwf/ecmwf-opendata)：资料种类和读取方式。
- [UCAR TCGP 实时热带气旋](https://hurricanes.ral.ucar.edu/realtime/)：业务轨迹镜像及风速定义。
- [MetPy 锋面符号](https://unidata.github.io/MetPy/latest/examples/plots/Simple_Fronts_Plot.html)：符号绘制，不是锋面识别正确性的证明。
- [Natural Earth 海岸线](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-coastline/)：公共领域；本仓库只收录海岸线，中国境界继续使用原有天地图资料。
- [IFS 冰面过饱和说明](https://www.ecmwf.int/en/elibrary/76723-ice-supersaturation-ecmwf-integrated-forecast-system)：冷区相对湿度可能超过 100%，不得为使图片通过检查而截断原值；地下格点不参与上空气象场的范围核验。

## 检验

`python -m unittest tests.test_weather_presentation tests.test_weather_map -q` 覆盖地下遮罩、南半球中心、跨日期变更线、范围拒绝、距平回退、降水单位读数、精确气压层与位势转换、跨海盆气旋来源和未来时刻拒绝。

另需用真实归档图检查五个层面、全球及区域图，用浏览器核验图幅、图注和切层。统计/物理范围检查不能替代气象上的逐例验证。
