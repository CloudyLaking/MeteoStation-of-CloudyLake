# MeteoStation-of-CloudyLake 

本项目旨在基于公开的气象数据 API 搭建一套包含中国国家站地面观测查询与欧洲中期天气预报中心（ECMWF）ERA5 再分析数据可视化的综合气象制图系统。

## 📖 项目简介
MeteoStation 是一个模块化的气象数据下载与可视化工具集，支持：
1. **实况与观测站点查询制图**：根据站号一键生成包含降水、温湿度等要素的精美实况图表，包含体感温度、露点分析及模糊查询。
2. **ERA5 各气象要素可视化**：通过配置字典自动化下载目标区域和时间的 ERA5 气象要素，绘制极具出版级别的高质量组合气象图。支持填色图（Shaded）、等值线（Contour）和风场矢量（Wind Barbs）的任意灵活组合叠加。
3. **历年气候平均态分析 (Climatology)**：基于 ERA5 月平均气候资料快速生成几十年维度的环境平均态或环流场。

---

## 📁 目录结构

本仓库代码主要集中在 `MeteoStation/` 目录下，运行时会在工作区的同级目录自动生成 `Output/` 文件夹用于存放外部数据和生图：

```text
工作区根目录/
├── MeteoStation/              # 本项目核心代码文件夹
│   ├── Basic_function/        # (版本 1.x 遗留) 地面观测站点图表旧业务代码
│   ├── MeteoMap/              # (主业务逻辑) ERA5 再分析数据绘图模块
│   │   ├── main_plot.py       # ERA5 常规分析图主程序
│   │   ├── main_plot_climate.py # ERA5 气候态平均绘图主程序
│   │   ├── data_fetcher.py    # 负责对接 CDS API 下载文件的组件
│   │   └── components/        # 重构后的核心绘图组件库（完全解耦）
│   └── MeteoMap-ERA5average/  # 旧版与过渡期的平均气候文件存档
└── Output/                    # (仓库外) 项目自动生成的数据与图片输出目录
    ├── MeteoMap/              # 常规生图的输出目录及缓存
    └── MeteoMap-Average/      # 气候态生图的输出目录及缓存
```

---

## 🚀 核心功能与使用说明 (MeteoMap)

### 1. 绘制单次/当前 ERA5 分析图 (`main_plot.py`)
在这份文件中，修改底部的 `config_example` 参数后直接运行即可。工具支持图层自由组合：
- **`shaded_type / shaded_level`**：设置填色。针对 `WindSpeed`, `CAPE`, `Temperature` 工具已配好色彩；亦支持传入任意 CDS 变量 (如 `relative_humidity`, `vorticity`)，程序将采用推断自适应绘制。
- **`contour_type / contour_level`**：设置等值线，比如 `SLP` (海压)、 `Geopotential` (位势高度) 或任意系统变量。
- **`show_wind`**：若开启此项，自动覆盖底层风羽。

### 2. 绘制气候平均态对比图 (`main_plot_climate.py`)
此模块的操作方式与常规版极像。除以上基本绘制参数外，只需控制时间线：
- **`years_range`**: 比如 `(1991, 2020)` 指明气候态的算力跨度。
- **`months`**: 比如 `[7]` 或 `[12,1,2]` 用来规定你想取哪些月份进行合成。这部分计算全自动在本地内存降维并生成高质量气象底图。

---

## 📦 环境与依赖
使用此工具前，请确保 Python 环境中已经安装如下依赖：
```bash
pip install xarray numpy scipy matplotlib cartopy cdsapi netCDF4
```
> **注意**：下载 ERA5 数据需已注册 [Copernicus CDS](https://cds.climate.copernicus.eu/api-how-to) 并成功配好您本地的 `.cdsapirc` 密钥文件。

---

## 📝 历史更新日志 (Changelog)

### Version 3.x (代码模块重构与气候场) 
- **底层解耦重构**: 抛弃旧有臃肿杂糅单脚本制，将功能原子化拆分成 `base_map`, `layer_shaded`, `layer_contour`, `layer_wind`。图片配色格式彻底一统。
- **自适应变量防呆(Fallback)**: 无论用户通过 API 输入什么奇葩新变量，如果没有设死颜色表，通通启动 `Spectral_r` 取间距通用配色+自适应等值线策略！自带高空气压未输入探测警告拦截。
- **自动气候计算 `main_plot_climate.py`**: 零计算痛点！在字典中输入时间跨度即可自动完成月均量获取、压缩降维与精美气候图渲染。此工具库与常规绘图库共享渲染器。

### Version 2.x (ERA5要素引入)
- 逐步引入 10m风+MSLP、高空风+位势场 的下载与渲染。
- 构建 CAPE，K-Index，相对湿度散度等多种要素的原始公式组合制图。

### Version 1.x (单点实况)
- 查询并画出指定观测站点历史信息的精良图标，并内置露点、体感计算模块。
- 添加网站查询交互及静态地图底图渲染探索。


