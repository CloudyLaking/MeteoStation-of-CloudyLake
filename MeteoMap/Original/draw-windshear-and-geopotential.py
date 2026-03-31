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

def calculate_wind_shear(u_upper, v_upper, u_lower, v_lower):
    """
    计算风切变矢量和风切变强度
    
    参数:
    u_upper, v_upper : np.array - 上层风场分量 (m/s)
    u_lower, v_lower : np.array - 下层风场分量 (m/s)
    
    返回:
    tuple - (shear_u, shear_v, shear_magnitude) 风切变分量和强度
    """
    # 风切变 = 上层风 - 下层风
    shear_u = u_upper - u_lower
    shear_v = v_upper - v_lower
    
    # 风切变强度
    shear_magnitude = np.sqrt(shear_u**2 + shear_v**2)
    
    return shear_u, shear_v, shear_magnitude

def get_wind_shear_color_scheme():
    """
    返回风切变强度配色方案 (m/s)
    """
    # 调整后的配色方案，10m/s左右为绿色
    colors = [
        "#FFFFFF",  # 白色 (0 m/s) - 无风切变
        "#CCE7FF",  # 浅蓝 (2 m/s)
        "#99D6FF",  # 蓝 (4 m/s)
        "#66C2FF",  # 中蓝 (6 m/s)
        "#00CC99",  # 青绿色 (8 m/s)
        "#00FF66",  # 绿色 (10 m/s) - 弱到中等风切变
        "#66FF33",  # 浅绿色 (12 m/s)
        "#CCFF00",  # 黄绿色 (14 m/s)
        "#FFE666",  # 黄色 (16 m/s)
        "#FFCC33",  # 金黄 (18 m/s)
        "#FF9900",  # 橙色 (20 m/s) - 中等到强风切变
        "#FF6600",  # 橙红 (24 m/s)
        "#FF3300",  # 红色 (28 m/s)
        "#CC0000",  # 深红 (32 m/s)
        "#A50026",  # 更深的红色 (36 m/s) - 强风切变
    ]
    
    shear_points = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36]
    min_shear, max_shear = 0, 40
    
    return colors, shear_points, min_shear, max_shear

def get_height_contour_interval(pressure_level):
    """
    根据气压层返回相应的等高线间距
    """
    if pressure_level >= 850:
        return 15  # 边界层
    elif pressure_level >= 500:
        return 30  # 对流层中层
    elif pressure_level >= 350:
        return 60  # 对流层中高层
    elif pressure_level >= 200:
        return 100  # 对流层顶/平流层底
    elif pressure_level >= 100:
        return 150  # 平流层低层
    elif pressure_level >= 30:
        return 200  # 平流层中高层
    else:
        return 500  # 平流层高层

def draw_wind_shear_map(date_str, output_image_path, upper_level, lower_level, 
                       lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                       datasets=None, smooth_sigma=1, use_china_boundaries=True,
                       vector_density=20):
    """
    绘制单个风切变图
    
    参数:
    upper_level, lower_level : int - 上层和下层气压层面 (hPa)
    datasets : dict - 包含所有层面数据的字典
    vector_density : int - 风切变矢量密度
    """
    
    # 提取坐标
    coord_ds = list(datasets.values())[0]
    lon = coord_ds.coords['longitude'].values
    lat = coord_ds.coords['latitude'].values
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 提取风场数据
    u_upper = datasets[upper_level]['u'].values.squeeze()
    v_upper = datasets[upper_level]['v'].values.squeeze()
    u_lower = datasets[lower_level]['u'].values.squeeze()
    v_lower = datasets[lower_level]['v'].values.squeeze()
    
    # 计算风切变
    shear_u, shear_v, shear_magnitude = calculate_wind_shear(u_upper, v_upper, u_lower, v_lower)
    
    # 提取500hPa位势高度数据
    geopotential_500 = datasets[500]['z'].values.squeeze()
    height_500 = geopotential_500 / 9.80665  # 转换为位势高度 (gpm)
    
    # 应用平滑
    if smooth_sigma > 0:
        shear_magnitude_smooth = gaussian_filter(shear_magnitude, sigma=smooth_sigma)
        height_500_smooth = gaussian_filter(height_500, sigma=smooth_sigma)
    else:
        shear_magnitude_smooth = shear_magnitude
        height_500_smooth = height_500
    
    # 计算统计信息
    min_shear = np.min(shear_magnitude_smooth)
    max_shear = np.max(shear_magnitude_smooth)
    mean_shear = np.mean(shear_magnitude_smooth)
    min_height = np.min(height_500_smooth)
    max_height = np.max(height_500_smooth)
    
    shear_stats = f"Wind Shear: {min_shear:.1f}-{max_shear:.1f}m/s (avg: {mean_shear:.1f}m/s)"
    height_stats = f"500hPa GPH: {min_height:.0f}-{max_height:.0f}gpm"
    
    print(f"风切变统计 ({upper_level}-{lower_level}hPa): {shear_stats}")
    print(f"位势高度统计: {height_stats}")
    
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
    
    # 获取风切变配色方案
    colors, shear_points, min_display, max_display = get_wind_shear_color_scheme()
    
    # 创建颜色映射
    color_positions = []
    valid_colors = []
    for i, shear in enumerate(shear_points):
        if i < len(colors):
            pos = (shear - min_display) / (max_display - min_display)
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
    
    cmap = LinearSegmentedColormap.from_list('shear_cmap', 
                                           list(zip(unique_positions, unique_colors)), N=256)
    
    # 绘制风切变强度填充等值线
    from matplotlib.colors import Normalize
    norm = Normalize(vmin=min_display, vmax=max_display)
    
    levels_plot = np.linspace(min_display, max_display, 100)
    contourf = ax.contourf(lon_grid, lat_grid, shear_magnitude_smooth, levels=levels_plot, 
                          cmap=cmap, norm=norm, transform=ccrs.PlateCarree(), 
                          alpha=0.8, extend='max')
    
    # 绘制500hPa位势高度等值线
    interval = get_height_contour_interval(500)
    height_min_round = int(min_height // interval) * interval
    height_max_round = int(max_height // interval + 1) * interval
    height_levels = np.arange(height_min_round, height_max_round + interval, interval)
    
    contour = ax.contour(lon_grid, lat_grid, height_500_smooth, levels=height_levels, 
                        colors='black', linewidths=1.5, alpha=1.0, transform=ccrs.PlateCarree())
    ax.clabel(contour, inline=True, fontsize=9, fmt='%d', colors='black')
    
    # 绘制风切变矢量
    skip_factor = max(1, min(shear_u.shape) // vector_density)
    barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    ax.barbs(lon_grid[barb_slice], lat_grid[barb_slice], 
             shear_u[barb_slice], shear_v[barb_slice],
             length=5, pivot='middle', color='darkred', alpha=0.9, 
             transform=ccrs.PlateCarree())
    
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
    tick_interval = 5  # 每5m/s一个刻度
    tick_start = int(min_display // tick_interval) * tick_interval
    tick_end = int(max_display // tick_interval) * tick_interval
    colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
    
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label='Wind Shear Magnitude (m/s)')
    
    # 格式化标题
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    main_title = f'ERA5 Wind Shear ({upper_level}-{lower_level}hPa) + 500hPa GPH'
    time_title = date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', fontsize=14, fontweight='bold', color='black')
    
    ax.text(0.99, 1.015, f'{shear_stats}\n{height_stats}', transform=ax.transAxes, 
            ha='right', va='bottom', fontsize=12, color='black')
    
    # 保存图像
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"风切变图已保存: {output_image_path}")
    plt.close()

def draw_wind_shear_analysis(date_str='2024072400',
                           output_dir='Output/MeteoMap',
                           lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                           smooth_sigma=1, use_china_boundaries=True,
                           vector_density=20):
    """
    绘制风切变分析图：850-500hPa、500-250hPa和850-250hPa三种风切变
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    output_dir : str - 输出目录
    vector_density : int - 风切变矢量密度
    """
    
    print(f"开始分析 {date_str} 的风切变数据...")
    
    # 需要的气压层和变量
    pressure_levels = [850, 500, 250]
    variables_dict = {}
    for level in pressure_levels:
        variables_dict[level] = ['u_component_of_wind', 'v_component_of_wind', 'geopotential']
    
    # 下载数据
    print("正在下载ERA5多层风场数据...")
    datasets = download_era5_pressure_data_batch(
        date=date_str,
        pressure_levels=pressure_levels,
        variables_dict=variables_dict,
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max
    )
    
    if not datasets or len(datasets) < 3:
        print("数据下载失败或不完整，退出...")
        return
    
    # 检查数据完整性
    for level in pressure_levels:
        if level not in datasets:
            print(f"缺少 {level}hPa 数据，退出...")
            return
    
    print("数据下载完成，开始绘制风切变图...")
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 定义风切变层对
    shear_pairs = [
        (500, 850, "500-850hPa"),  # 对流层低层到中层
        (250, 500, "250-500hPa"),  # 对流层中层到高层  
        (250, 850, "250-850hPa")   # 对流层低层到高层
    ]
    
    # 生成三张风切变图
    for upper, lower, name in shear_pairs:
        print(f"\n正在绘制 {name} 风切变图...")
        
        output_path = os.path.join(output_dir, f'ERA5_WindShear_{name}_{date_str}.png')
        
        draw_wind_shear_map(
            date_str=date_str,
            output_image_path=output_path,
            upper_level=upper,
            lower_level=lower,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            datasets=datasets,
            smooth_sigma=smooth_sigma,
            use_china_boundaries=use_china_boundaries,
            vector_density=vector_density
        )
        
        print(f"完成 {name} 风切变图")
    
    print(f"\n所有风切变分析图已完成！")

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    # 参数设置
    date_str = '2024072400'
    
    # 生成风切变分析图
    draw_wind_shear_analysis(
        date_str=date_str,
        output_dir='Output/MeteoMap',
        lon_min=80,
        lon_max=140,
        lat_min=20,
        lat_max=55,
        smooth_sigma=1,
        use_china_boundaries=True,
        vector_density=20
    )