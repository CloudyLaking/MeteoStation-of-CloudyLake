import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter
import xarray as xr
import os
import datetime as dt
from matplotlib.colors import LinearSegmentedColormap
import requests
import json
from shapely.geometry import shape
import matplotlib.patches as mpatches

def download_china_boundaries():
    """
    从 DataV.GeoAtlas 下载中国官方边界数据
    """
    try:
        china_url = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
        print("Downloading China boundaries from DataV.GeoAtlas...")
        response = requests.get(china_url, timeout=30)
        
        if response.status_code == 200:
            china_data = response.json()
            print("Successfully downloaded China boundaries")
            return china_data
        else:
            print(f"Failed to download China boundaries: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"Error downloading China boundaries: {e}")
        return None

def add_china_boundaries(ax, china_geojson=None, lon_min=None, lon_max=None, lat_min=None, lat_max=None):
    """
    添加中国边界到地图，支持范围裁剪
    """
    if china_geojson is None:
        china_geojson = download_china_boundaries()
    
    if china_geojson and 'features' in china_geojson:
        try:
            for feature in china_geojson['features']:
                if feature['geometry']['type'] in ['Polygon', 'MultiPolygon']:
                    geom = shape(feature['geometry'])
                    
                    if all(param is not None for param in [lon_min, lon_max, lat_min, lat_max]):
                        from shapely.geometry import box
                        bbox = box(lon_min, lat_min, lon_max, lat_max)
                        try:
                            geom = geom.intersection(bbox)
                            if geom.is_empty:
                                continue
                        except:
                            bounds = geom.bounds
                            if (bounds[2] < lon_min or bounds[0] > lon_max or 
                                bounds[3] < lat_min or bounds[1] > lat_max):
                                continue
                    
                    if geom.geom_type == 'Polygon':
                        x, y = geom.exterior.xy
                        ax.plot(x, y, color='black', linewidth=0.8, alpha=0.8, 
                               transform=ccrs.PlateCarree())
                        for interior in geom.interiors:
                            x, y = interior.xy
                            ax.plot(x, y, color='black', linewidth=0.6, alpha=0.8, 
                                   transform=ccrs.PlateCarree())
                    
                    elif geom.geom_type == 'MultiPolygon':
                        for polygon in geom.geoms:
                            if polygon.geom_type == 'Polygon':
                                x, y = polygon.exterior.xy
                                ax.plot(x, y, color='black', linewidth=0.8, alpha=0.8, 
                                       transform=ccrs.PlateCarree())
                                for interior in polygon.interiors:
                                    x, y = interior.xy
                                    ax.plot(x, y, color='black', linewidth=0.6, alpha=0.8, 
                                           transform=ccrs.PlateCarree())
            
            print("Added China boundaries from DataV.GeoAtlas")
            return True
            
        except Exception as e:
            print(f"Error processing China boundaries: {e}")
            return False
    
    return False

def download_era5_pressure_data_batch(date, pressure_levels, variables_dict, lon_min, lon_max, lat_min, lat_max):
    """
    批量下载多个气压层的ERA5数据
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        return {}
        
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    c = cdsapi.Client()
    datasets = {}
    
    for level in pressure_levels:
        if level not in variables_dict or not variables_dict[level]:
            continue
            
        print(f"正在下载 {level}hPa 数据...")
        
        try:
            temp_dir = tempfile.gettempdir()
            temp_filename = f"era5_pressure_temp_{os.getpid()}_{date}_{level}.nc"
            output_file = os.path.join(temp_dir, temp_filename)
            
            if os.path.exists(output_file):
                os.remove(output_file)
                
            c.retrieve(
                'reanalysis-era5-pressure-levels',
                {
                    'product_type': 'reanalysis',
                    'format': 'netcdf',
                    'variable': variables_dict[level],
                    'pressure_level': str(level),
                    'year': year,
                    'month': month,
                    'day': day,
                    'time': f'{hour}:00',
                    'area': [lat_max, lon_min, lat_min, lon_max],
                },
                output_file)
            
            with xr.open_dataset(output_file) as ds:
                datasets[level] = ds.load()
            
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except Exception as e:
                    print(f"警告: 无法删除临时文件 {output_file}: {e}")
            
            print(f"完成下载 {level}hPa 数据")
                    
        except Exception as e:
            print(f"下载 {level}hPa 数据时出错: {e}")
            if 'output_file' in locals() and os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except:
                    pass
    
    return datasets

def calculate_freezing_level_height(datasets, pressure_levels):
    """
    计算0°C冻结层高度（使用线性插值）
    
    参数:
    datasets : dict - 各气压层数据集 {level: xr.Dataset}
    pressure_levels : list - 气压层列表，从低到高排列
    
    返回:
    np.array - 冻结层高度 (米)
    """
    # 确保气压层按从高压到低压排序（地面到高空）
    sorted_levels = sorted(pressure_levels, reverse=True)
    
    # 提取温度和位势高度数据
    temperatures = []  # 温度 (K -> °C)
    heights = []       # 位势高度 (m²/s² -> m)
    
    for level in sorted_levels:
        if level in datasets:
            ds = datasets[level]
            temp = ds['t'].values.squeeze() - 273.15  # 转换为摄氏度
            geopotential = ds['z'].values.squeeze()
            height = geopotential / 9.80665  # 转换为几何高度(米)
            
            temperatures.append(temp)
            heights.append(height)
        else:
            print(f"警告: 缺少 {level}hPa 数据")
            return None
    
    if len(temperatures) < 2:
        print("错误: 需要至少2个气压层数据来计算冻结层高度")
        return None
    
    # 转换为numpy数组，形状: (levels, lat, lon)
    temp_array = np.array(temperatures)
    height_array = np.array(heights)
    
    # 初始化冻结层高度数组
    freezing_height = np.full(temp_array.shape[1:], np.nan)
    
    # 对每个格点进行插值
    for i in range(len(sorted_levels) - 1):
        # 当前层和上一层的温度和高度
        temp_lower = temp_array[i]      # 较低层（高压）
        temp_upper = temp_array[i + 1]  # 较高层（低压）
        height_lower = height_array[i]
        height_upper = height_array[i + 1]
        
        # 找到温度跨过0°C的格点（从正温度到负温度）
        mask = (temp_lower >= 0) & (temp_upper < 0) & np.isnan(freezing_height)
        
        if np.any(mask):
            # 线性插值计算0°C高度
            # 插值公式: h = h1 + (0 - t1) / (t2 - t1) * (h2 - h1)
            temp_diff = temp_upper[mask] - temp_lower[mask]
            # 避免除零
            valid_diff = temp_diff != 0
            if np.any(valid_diff):
                mask_final = mask.copy()
                mask_final[mask] = valid_diff
                
                ratio = -temp_lower[mask_final] / temp_diff[valid_diff]
                freezing_height[mask_final] = (height_lower[mask_final] + 
                                              ratio * (height_upper[mask_final] - height_lower[mask_final]))
    
    return freezing_height

def get_freezing_level_color_scheme():
    """
    返回冻结层高度配色方案
    """
    # 冻结层高度配色 (米)
    colors = [
        "#FFFFFF",   # 白色
        "#8DE1DE",   # 浅青色
        "#07a892",  # 浅青蓝
        "#009691",  # 中青蓝
        "#004e4d"  # 深青蓝
    ]
    
    # 高度节点 (米)
    height_points = [0, 1000, 2000, 5000, 8000]
    min_height, max_height = 0, 8000
    
    return colors, height_points, min_height, max_height

def draw_freezing_level_map(date_str='2024072400', 
                           output_image_path='Output/MeteoMap/freezing_level.png',
                           hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                           data_source='ERA5', smooth_sigma=1, download_data=True,
                           use_china_boundaries=True,
                           pressure_levels=[1000, 925, 850, 700, 600, 500, 400, 300],
                           show_contour_lines=True,
                           contour_interval=250):
    """
    绘制冻结层高度分布图
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    pressure_levels : list - 用于计算冻结层的气压层 (hPa)
    show_contour_lines : bool - 是否显示等高线
    contour_interval : int - 等高线间距 (米)
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据用于计算冻结层高度...")
        
        # 需要的变量：温度和位势高度
        variables_dict = {}
        for level in pressure_levels:
            variables_dict[level] = ['temperature', 'geopotential']
        
        # 下载数据
        datasets = download_era5_pressure_data_batch(
            date=date_str,
            pressure_levels=pressure_levels,
            variables_dict=variables_dict,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if not datasets:
            print("数据下载失败，退出...")
            return
        
        # 提取坐标
        coord_ds = list(datasets.values())[0]
        lon = coord_ds.coords['longitude'].values
        lat = coord_ds.coords['latitude'].values
        
        # 计算冻结层高度
        print("正在计算冻结层高度...")
        freezing_height = calculate_freezing_level_height(datasets, pressure_levels)
        
        if freezing_height is None:
            print("冻结层高度计算失败")
            return
        
    else:
        print("错误: 暂不支持从文件加载冻结层数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 应用平滑
    if smooth_sigma > 0:
        freezing_height_smooth = gaussian_filter(freezing_height, sigma=smooth_sigma)
    else:
        freezing_height_smooth = freezing_height
    
    # 计算统计信息
    valid_mask = ~np.isnan(freezing_height_smooth)
    if np.any(valid_mask):
        min_height = np.min(freezing_height_smooth[valid_mask])
        max_height = np.max(freezing_height_smooth[valid_mask])
        mean_height = np.mean(freezing_height_smooth[valid_mask])
        stats_text = f"Freezing Level: {min_height:.0f}-{max_height:.0f}m (avg: {mean_height:.0f}m)"
    else:
        stats_text = "No valid freezing level data"
    
    print(f"数据统计: {stats_text}")
    
    # 设置字体
    try:
        import matplotlib.font_manager as font_manager
        font_manager.fontManager.addfont(r'MeteoStation\MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']
    except:
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图形
    fig = plt.figure(figsize=(15, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], crs=ccrs.PlateCarree())
    
    # 获取配色方案
    colors, height_points, min_display, max_display = get_freezing_level_color_scheme()
    
    # 创建颜色映射
    color_positions = []
    valid_colors = []
    for i, height in enumerate(height_points):
        if i < len(colors):
            pos = (height - min_display) / (max_display - min_display)
            pos = max(0, min(1, pos))
            color_positions.append(pos)
            valid_colors.append(colors[i])
    
    # 排序并确保边界
    sorted_pairs = sorted(zip(color_positions, valid_colors))
    color_positions, valid_colors = zip(*sorted_pairs)
    color_positions = list(color_positions)
    valid_colors = list(valid_colors)
    
    if color_positions[0] > 0:
        color_positions.insert(0, 0)
        valid_colors.insert(0, valid_colors[0])
    if color_positions[-1] < 1:
        color_positions.append(1)
        valid_colors.append(valid_colors[-1])
    
    # 去重
    unique_positions = []
    unique_colors = []
    for i, (pos, color) in enumerate(zip(color_positions, valid_colors)):
        if i == 0 or pos > color_positions[i-1]:
            unique_positions.append(pos)
            unique_colors.append(color)
    
    cmap = LinearSegmentedColormap.from_list('freezing_cmap', 
                                           list(zip(unique_positions, unique_colors)), N=256)
    
    # 绘制填充等值线
    from matplotlib.colors import Normalize
    norm = Normalize(vmin=min_display, vmax=max_display)
    
    # 只绘制有效数据区域
    masked_data = np.ma.masked_invalid(freezing_height_smooth)
    
    levels_plot = np.linspace(min_display, max_display, 100)
    contourf = ax.contourf(lon_grid, lat_grid, masked_data, levels=levels_plot, 
                          cmap=cmap, norm=norm, transform=ccrs.PlateCarree(), 
                          alpha=0.9, extend='both')
    
    # 绘制等高线
    if show_contour_lines and np.any(valid_mask):
        height_min_round = int(min_height // contour_interval) * contour_interval
        height_max_round = int(max_height // contour_interval + 1) * contour_interval
        contour_levels = np.arange(height_min_round, height_max_round + contour_interval, contour_interval)
        
        contour = ax.contour(lon_grid, lat_grid, masked_data, levels=contour_levels, 
                            colors='black', linewidths=1.0, alpha=0.8, transform=ccrs.PlateCarree())
        ax.clabel(contour, inline=True, fontsize=9, fmt='%d', inline_spacing=3)
    
    # 添加地图要素
    try:
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        if use_china_boundaries:
            china_boundaries_added = add_china_boundaries(ax, lon_min=lon.min(), lon_max=lon.max(),
                                                        lat_min=lat.min(), lat_max=lat.max())
            if not china_boundaries_added:
                ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
        else:
            ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
    except Exception as e:
        print(f"添加边界时出错: {e}")
        ax.coastlines(resolution='50m')
        ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
    
    # 添加网格线
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.7)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(lon.min()), np.ceil(lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(lat.min()), np.ceil(lat.max()) + 1, 5))

    # 创建色彩条
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    # 设置色彩条刻度
    tick_interval = 500  # 每500米一个刻度
    tick_start = int(min_display // tick_interval) * tick_interval
    tick_end = int(max_display // tick_interval) * tick_interval
    colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
    
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label='Freezing Level Height (m)')
    
    # 格式化标题
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    main_title = f'{data_source} 0°C Freezing Level Height'
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', fontsize=14, fontweight='bold', color='black')
    
    ax.text(0.99, 1.015, stats_text, transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=12, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"冻结层高度图已保存: {output_image_path}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    # 参数设置
    date_str = '2024072400'
    
    # 绘制冻结层高度图
    draw_freezing_level_map(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_FreezingLevel_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        pressure_levels=[1000, 925, 850, 700, 600, 500, 400, 300, 250],
        show_contour_lines=True,
        contour_interval=250,
        smooth_sigma=1
    )