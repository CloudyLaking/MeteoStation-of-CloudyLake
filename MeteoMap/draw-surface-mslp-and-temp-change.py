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

def download_era5_surface_data(date, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5地面再分析数据
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None
        
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    c = cdsapi.Client()
    
    try:
        temp_dir = tempfile.gettempdir()
        temp_filename = f"era5_surface_temp_{os.getpid()}_{date}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        c.retrieve(
            'reanalysis-era5-single-levels',
            {
                'product_type': 'reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'year': year,
                'month': month,
                'day': day,
                'time': f'{hour}:00',
                'area': [lat_max, lon_min, lat_min, lon_max],
            },
            output_file)
        
        with xr.open_dataset(output_file) as ds:
            loaded_data = ds.load()
        
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception as e:
                print(f"警告: 无法删除临时文件 {output_file}: {e}")
        
        return loaded_data
            
    except Exception as e:
        print(f"下载ERA5地面数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def calculate_previous_datetime(date_str, hours_back):
    """
    计算指定小时数之前的日期时间
    
    参数:
    date_str : str - 当前日期时间字符串 (YYYYMMDDHH)
    hours_back : int - 回推的小时数
    
    返回:
    str - 之前的日期时间字符串 (YYYYMMDDHH)
    """
    try:
        current_dt = dt.datetime.strptime(date_str, '%Y%m%d%H')
        previous_dt = current_dt - dt.timedelta(hours=hours_back)
        return previous_dt.strftime('%Y%m%d%H')
    except Exception as e:
        print(f"计算之前日期时间时出错: {e}")
        return None

def get_temperature_change_color_scheme():
    """
    返回温度变化配色方案 (蓝色-白色-红色)
    """
    colors = [
        "#F9BBFF",  # -30°C
        "#FF13EB",  # -24°C
        "#CC00FF",  # -18°C
        "#6449FF",  # -12°C
        "#009DFF",  # -6°C
        "#B0E0E6",  # -2°C
        "#FFFFFF",  # 0°C
        "#E1FFF1",  # +2°C
        "#FFBB28",  # +6°C
        "#FF6200",  # +12°C
        "#D00000",  # +18°C
        "#754C4C",  # +24°C
        "#C6AFAF",  # +30°C
    ]
    temp_change_points = [-30, -24, -18, -12, -6, -2, 0, 2, 6, 12, 18, 24, 30]
    min_temp_change, max_temp_change = -30, 30
    
    return colors, temp_change_points, min_temp_change, max_temp_change

def draw_temperature_change(current_date_str='2024072400',
                           change_hours=24,
                           output_image_path='Output/MeteoMap/temperature_change_24h.png',
                           hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                           data_source='ERA5', smooth_sigma=1, download_data=True,
                           use_china_boundaries=True,
                           # 温度变化设置
                           show_change_contours=True,
                           change_contour_interval=2,
                           show_change_numbers=True,
                           number_interval=20,
                           # 气压等值线设置
                           show_pressure_contours=True,
                           pressure_contour_interval=4):
    """
    绘制温度变化图：当前时刻与N小时前的温度差
    
    参数:
    current_date_str : str - 当前日期时间字符串 (YYYYMMDDHH)
    change_hours : int - 温度变化时间间隔（小时），支持24, 36, 48, 60等
    show_change_contours : bool - 是否显示温度变化等值线
    change_contour_interval : int - 温度变化等值线间隔
    show_change_numbers : bool - 是否显示温度变化数值
    number_interval : int - 数值显示密度
    show_pressure_contours : bool - 是否显示气压等值线
    pressure_contour_interval : int - 气压等值线间隔
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        # 计算之前的日期时间
        previous_date_str = calculate_previous_datetime(current_date_str, change_hours)
        if previous_date_str is None:
            print("计算之前日期失败，退出...")
            return
        
        print(f"正在下载当前时刻 ({current_date_str}) 的ERA5数据...")
        
        # 下载当前时刻数据
        current_ds = download_era5_surface_data(
            date=current_date_str,
            variables=['2m_temperature', 'mean_sea_level_pressure'],
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if current_ds is None:
            print("当前时刻数据下载失败，退出...")
            return
        
        print(f"正在下载 {change_hours} 小时前 ({previous_date_str}) 的ERA5数据...")
        
        # 下载之前时刻数据
        previous_ds = download_era5_surface_data(
            date=previous_date_str,
            variables=['2m_temperature'],
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if previous_ds is None:
            print("之前时刻数据下载失败，退出...")
            return
        
        # 提取数据
        current_temp = current_ds['t2m'].values.squeeze() - 273.15  # 转换为摄氏度
        previous_temp = previous_ds['t2m'].values.squeeze() - 273.15  # 转换为摄氏度
        current_mslp = current_ds['msl'].values.squeeze() / 100  # 转换为hPa
        
        # 获取坐标
        lon = current_ds.coords['longitude'].values
        lat = current_ds.coords['latitude'].values
        
        print("数据下载完成")
        
    else:
        print("错误: 暂不支持从文件加载温度变化数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 计算温度变化
    temp_change = current_temp - previous_temp
    
    # 应用平滑
    if smooth_sigma > 0:
        temp_change_smooth = gaussian_filter(temp_change, sigma=smooth_sigma)
        mslp_smooth = gaussian_filter(current_mslp, sigma=smooth_sigma)
    else:
        temp_change_smooth = temp_change
        mslp_smooth = current_mslp
    
    # 计算统计信息
    min_temp_change = np.min(temp_change_smooth)
    max_temp_change = np.max(temp_change_smooth)
    mean_temp_change = np.mean(temp_change_smooth)
    min_pressure = np.min(mslp_smooth)
    max_pressure = np.max(mslp_smooth)
    
    print(f"温度变化统计 ({change_hours}小时): {min_temp_change:.1f}°C 到 {max_temp_change:.1f}°C (平均: {mean_temp_change:.1f}°C)")
    print(f"气压范围: {min_pressure:.1f} - {max_pressure:.1f} hPa")
    
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
    
    # 获取温度变化配色方案
    colors, temp_change_points, min_temp_display, max_temp_display = get_temperature_change_color_scheme()
    
    # 创建温度变化配色映射
    color_positions = []
    valid_colors = []
    
    for i, temp in enumerate(temp_change_points):
        if i < len(colors):
            pos = (temp - min_temp_display) / (max_temp_display - min_temp_display)
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
    
    # 创建色彩映射
    cmap = LinearSegmentedColormap.from_list(
        'temp_change_cmap', 
        list(zip(unique_positions, unique_colors)),
        N=256
    )
    
    # 绘制温度变化填充等高线
    from matplotlib.colors import Normalize
    norm = Normalize(vmin=min_temp_display, vmax=max_temp_display)
    
    temp_change_levels_plot = np.linspace(min_temp_display, max_temp_display, 100)
    
    contourf = ax.contourf(
        lon_grid, lat_grid, temp_change_smooth,
        levels=temp_change_levels_plot, 
        cmap=cmap, 
        norm=norm,
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='both'
    )
    
    print(f"绘制温度变化填充")
    
    # 绘制温度变化等值线
    if show_change_contours:
        # 确定等值线范围
        change_min_round = int(min_temp_change // change_contour_interval) * change_contour_interval
        change_max_round = int(max_temp_change // change_contour_interval + 1) * change_contour_interval
        change_levels = np.arange(change_min_round, change_max_round + change_contour_interval, change_contour_interval)
        
        # 确保0度线包含在内
        if 0 not in change_levels and change_min_round <= 0 <= change_max_round:
            change_levels = np.append(change_levels, 0)
            change_levels = np.sort(change_levels)
        
        # 绘制等值线
        change_contour = ax.contour(
            lon_grid, lat_grid, temp_change_smooth, 
            levels=change_levels, 
            colors='black', 
            linewidths=1.2,
            alpha=0.8,
            transform=ccrs.PlateCarree()
        )
        
        # 特殊处理0度线
        zero_line = ax.contour(
            lon_grid, lat_grid, temp_change_smooth,
            levels=[0],
            colors='darkblue',
            linewidths=2.0,
            alpha=1.0,
            transform=ccrs.PlateCarree()
        )
        
        ax.clabel(change_contour, inline=True, fontsize=9, fmt='%+d', colors='black')
        ax.clabel(zero_line, inline=True, fontsize=10, fmt='%+d', colors='darkblue')
        
        print(f"绘制温度变化等值线: 间距 {change_contour_interval}°C")
    
    # 绘制气压等值线
    if show_pressure_contours:
        pressure_min_round = int(min_pressure // pressure_contour_interval) * pressure_contour_interval
        pressure_max_round = int(max_pressure // pressure_contour_interval + 1) * pressure_contour_interval
        pressure_levels = np.arange(pressure_min_round, pressure_max_round + pressure_contour_interval, pressure_contour_interval)
        
        pressure_contour = ax.contour(
            lon_grid, lat_grid, mslp_smooth, 
            levels=pressure_levels, 
            colors='gray', 
            linewidths=1.0,
            alpha=0.6,
            linestyles='-',
            transform=ccrs.PlateCarree()
        )
        ax.clabel(pressure_contour, inline=True, fontsize=8, fmt='%d', colors='gray')
        
        print(f"绘制气压等值线: 间距 {pressure_contour_interval}hPa")
    
    # 显示温度变化数值
    if show_change_numbers:
        print("正在添加温度变化数值...")
        
        # 计算数值显示的采样间隔
        skip_factor = max(1, min(temp_change_smooth.shape) // number_interval)
        
        for i in range(0, temp_change_smooth.shape[0], skip_factor):
            for j in range(0, temp_change_smooth.shape[1], skip_factor):
                if i < temp_change_smooth.shape[0] and j < temp_change_smooth.shape[1]:
                    change_value = temp_change_smooth[i, j]
                    
                    # 只显示绝对值大于0.5度的变化
                    if abs(change_value) >= 0.5:
                        lon_pos = lon_grid[i, j]
                        lat_pos = lat_grid[i, j]
                        
                        # 根据数值大小选择颜色
                        if change_value > 2:
                            text_color = 'darkred'
                        elif change_value < -2:
                            text_color = 'darkblue'
                        else:
                            text_color = 'black'
                        
                        ax.text(lon_pos, lat_pos, f'{change_value:+.1f}',
                               transform=ccrs.PlateCarree(),
                               ha='center', va='center',
                               fontsize=7,
                               color=text_color,
                               weight='bold')
    
    # 添加海岸线和边界
    try:
        ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
        
        if use_china_boundaries:
            china_boundaries_added = add_china_boundaries(
                ax, 
                lon_min=lon.min(), 
                lon_max=lon.max(),
                lat_min=lat.min(), 
                lat_max=lat.max()
            )
            
            if not china_boundaries_added:
                ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.8)
        else:
            ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.8)
        
    except Exception as e:
        print(f"添加边界时出错: {e}")
        ax.coastlines(resolution='50m')
        ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.8)
    
    # 添加网格线
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(lon.min()), 
                                           np.ceil(lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(lat.min()), 
                                           np.ceil(lat.max()) + 1, 5))

    # 创建色彩条
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    # 设置色彩条刻度
    tick_interval = 2
    tick_start = int(min_temp_display // tick_interval) * tick_interval
    tick_end = int(max_temp_display // tick_interval) * tick_interval
    colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
    
    # 确保0包含在刻度中
    if 0 not in colorbar_ticks:
        colorbar_ticks.append(0)
        colorbar_ticks.sort()
    
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label=f'{change_hours}h Temperature Change (°C)')
    
    # 格式化日期以显示
    try:
        current_date_obj = dt.datetime.strptime(current_date_str, '%Y%m%d%H')
        current_date_display = current_date_obj.strftime('%Y-%m-%d %H:00 UTC')
        
        previous_date_obj = dt.datetime.strptime(previous_date_str, '%Y%m%d%H')
        previous_date_display = previous_date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        current_date_display = current_date_str
        previous_date_display = previous_date_str
    
    # 构建标题
    main_title = f'{data_source} {change_hours}h Temperature Change'
    
    if hour > 0:
        time_title = f'{current_date_display} +{hour}h'
    else:
        time_title = current_date_display
    
    # 左侧标题
    ax.text(0.01, 1.025, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧统计信息
    stats_text = f'Temp Change: {min_temp_change:.1f}°C to {max_temp_change:.1f}°C\n'
    stats_text += f'Average: {mean_temp_change:+.1f}°C\n'
    stats_text += f'Comparison: {previous_date_display}'
    
    ax.text(0.99, 1.025, stats_text, transform=ax.transAxes, 
            ha='right', va='bottom', 
            fontsize=10, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"{change_hours}小时温度变化图已保存: {output_image_path}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    current_date_str = '2022120100'
    
    # 选择要生成的温度变化时间间隔
    change_hours = 60  # 可以修改为 24, 36, 48, 60 等
    
    print(f"正在生成 {change_hours} 小时温度变化图...")
    
    try:
        # 根据时间间隔调整等值线间隔
        if change_hours >= 48:
            contour_interval = 3  # 长时间间隔使用更大的等值线间隔
        else:
            contour_interval = 2  # 短时间间隔使用较小的等值线间隔
        
        draw_temperature_change(
            current_date_str=current_date_str,
            change_hours=change_hours,
            output_image_path=f'Output/MeteoMap/ERA5_TempChange_{change_hours}h_{current_date_str}.png',
            hour=0,
            lon_min=40,
            lon_max=140,
            lat_min=20,
            lat_max=70,
            download_data=True,
            use_china_boundaries=True,
            show_change_contours=True,
            change_contour_interval=contour_interval,
            show_change_numbers=True,
            number_interval=20,#越低越稀疏
            show_pressure_contours=True,
            pressure_contour_interval=10
        )
        
        print(f"✅ {change_hours}小时温度变化图生成完成")
        
    except Exception as e:
        print(f"❌ {change_hours}小时温度变化图生成失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n所有温度变化图生成完成！")