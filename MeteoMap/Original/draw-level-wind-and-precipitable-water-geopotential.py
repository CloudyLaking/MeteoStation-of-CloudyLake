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
        # 中国全境边界（包含官方边界）
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
            # 遍历所有地理要素
            for feature in china_geojson['features']:
                if feature['geometry']['type'] in ['Polygon', 'MultiPolygon']:
                    # 创建shapely几何对象
                    geom = shape(feature['geometry'])
                    
                    # 如果指定了范围，则裁剪几何对象
                    if all(param is not None for param in [lon_min, lon_max, lat_min, lat_max]):
                        from shapely.geometry import box
                        bbox = box(lon_min, lat_min, lon_max, lat_max)
                        try:
                            geom = geom.intersection(bbox)
                            if geom.is_empty:
                                continue
                        except:
                            # 如果裁剪失败，检查是否在范围内
                            bounds = geom.bounds
                            if (bounds[2] < lon_min or bounds[0] > lon_max or 
                                bounds[3] < lat_min or bounds[1] > lat_max):
                                continue
                    
                    # 转换为matplotlib路径并添加到地图
                    if geom.geom_type == 'Polygon':
                        # 单个多边形
                        x, y = geom.exterior.xy
                        ax.plot(x, y, color='black', linewidth=0.8, alpha=0.8, 
                               transform=ccrs.PlateCarree())
                        
                        # 添加内部孔洞（如果有）
                        for interior in geom.interiors:
                            x, y = interior.xy
                            ax.plot(x, y, color='black', linewidth=0.6, alpha=0.8, 
                                   transform=ccrs.PlateCarree())
                    
                    elif geom.geom_type == 'MultiPolygon':
                        # 多个多边形
                        for polygon in geom.geoms:
                            if polygon.geom_type == 'Polygon':
                                x, y = polygon.exterior.xy
                                ax.plot(x, y, color='black', linewidth=0.8, alpha=0.8, 
                                       transform=ccrs.PlateCarree())
                                
                                # 添加内部孔洞（如果有）
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

def download_era5_pressure_data(date, pressure_level, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5气压层数据
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        print("并配置CDS API密钥: https://cds.climate.copernicus.eu/api-how-to")
        return None
        
    # 解析日期
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    
    # 初始化CDS API客户端
    c = cdsapi.Client()
    
    try:
        # 创建临时文件名
        temp_dir = tempfile.gettempdir()
        temp_filename = f"era5_pressure_temp_{os.getpid()}_{date}_{pressure_level}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        # 删除已存在的临时文件
        if os.path.exists(output_file):
            os.remove(output_file)
            
        # 下载ERA5气压层数据
        c.retrieve(
            'reanalysis-era5-pressure-levels',
            {
                'product_type': 'reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'pressure_level': str(pressure_level),
                'year': year,
                'month': month,
                'day': day,
                'time': f'{hour}:00',
                'area': [lat_max, lon_min, lat_min, lon_max],  # 北，西，南，东
            },
            output_file)
        
        # 将数据加载到内存
        with xr.open_dataset(output_file) as ds:
            loaded_data = ds.load()
        
        # 删除临时文件
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception as e:
                print(f"警告: 无法删除临时文件 {output_file}: {e}")
        
        return loaded_data
            
    except Exception as e:
        print(f"下载ERA5气压层数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def download_era5_surface_data(date, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5地面数据
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        print("并配置CDS API密钥: https://cds.climate.copernicus.eu/api-how-to")
        return None
        
    # 解析日期
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    
    # 初始化CDS API客户端
    c = cdsapi.Client()
    
    try:
        # 创建临时文件名
        temp_dir = tempfile.gettempdir()
        temp_filename = f"era5_surface_temp_{os.getpid()}_{date}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        # 删除已存在的临时文件
        if os.path.exists(output_file):
            os.remove(output_file)
            
        # 下载ERA5地面数据
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
                'area': [lat_max, lon_min, lat_min, lon_max],  # 北，西，南，东
            },
            output_file)
        
        # 将数据加载到内存
        with xr.open_dataset(output_file) as ds:
            loaded_data = ds.load()
        
        # 删除临时文件
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

def get_tcwv_color_scheme():
    """
    返回总可降水量配色方案（kg/m²或mm）
    """
    colors = [
        "#8B4513",  # 深褐色 (0mm) - 极干燥
        "#D2B48C",  # 棕褐色 (5mm)
        "#F5DEB3",  # 小麦色 (10mm)
        "#F0E68C",  # 卡其色 (15mm)
        "#FFFACD",  # 柠檬薄纱 (20mm)
        "#E0FFFF",  # 淡青色 (30mm)
        "#B4F6FF",  # 粉蓝色 (40mm)
        "#9BE3FF",  # 天蓝色 (50mm)
        "#9DD3FF",  # 钢蓝色 (60mm)
        "#74B9FF",  # 道奇蓝 (70mm)
        "#0084FF",  # 蓝色 (80mm) - 极湿润
    ]
    tcwv_points = [0, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80]
    min_tcwv, max_tcwv = 0, 80
    
    return colors, tcwv_points, min_tcwv, max_tcwv

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

def draw_multi_level_composite_tcwv(date_str='2024012400', 
                                   output_image_path='Output/MeteoMap/multi_level_composite_tcwv.png',
                                   hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                                   data_source='ERA5', smooth_sigma=1, download_data=True,
                                   use_china_boundaries=True,
                                   # 总可降水量层设置
                                   show_tcwv=True,
                                   # 位势高度层设置
                                   show_height=True, 
                                   height_level=500,
                                   height_contour_interval=None,  # None表示自动
                                   # 风场层设置
                                   show_wind=True,
                                   wind_level=500,
                                   wind_density=20):  # 风矢量密度
    """
    绘制多层复合图：总可降水量填充 + 位势高度等值线 + 风场矢量
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    show_tcwv : bool - 是否显示总可降水量填充
    height_level : int - 位势高度层面 (hPa)
    wind_level : int - 风场层面 (hPa)
    show_height : bool - 是否显示位势高度等值线
    show_wind : bool - 是否显示风场矢量
    wind_density : int - 风矢量密度 (数值越大越密集)
    height_contour_interval : int or None - 位势高度等值线间距，None表示自动
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据...")
        
        # 收集需要下载的气压层和地面变量
        pressure_levels_needed = set()
        surface_vars_needed = []
        
        if show_tcwv:
            surface_vars_needed.append('total_column_water_vapour')
            
        if show_height:
            pressure_levels_needed.add(height_level)
            
        if show_wind:
            pressure_levels_needed.add(wind_level)
        
        # 下载地面数据（总可降水量）
        surface_ds = None
        if surface_vars_needed:
            print("正在下载地面数据（总可降水量）...")
            surface_ds = download_era5_surface_data(
                date=date_str,
                variables=surface_vars_needed,
                lon_min=lon_min,
                lon_max=lon_max,
                lat_min=lat_min,
                lat_max=lat_max
            )
            
            if surface_ds is None:
                print("地面数据下载失败，退出...")
                return
        
        # 下载气压层数据
        datasets = {}
        for level in pressure_levels_needed:
            print(f"正在下载 {level}hPa 数据...")
            variables = []
            
            # 收集该层需要的变量
            if show_height and height_level == level:
                variables.append('geopotential')
            if show_wind and wind_level == level:
                variables.extend(['u_component_of_wind', 'v_component_of_wind'])
            
            # 去重
            variables = list(set(variables))
            
            if variables:  # 只有当需要变量时才下载
                ds = download_era5_pressure_data(
                    date=date_str,
                    pressure_level=level,
                    variables=variables,
                    lon_min=lon_min,
                    lon_max=lon_max,
                    lat_min=lat_min,
                    lat_max=lat_max
                )
                
                if ds is None:
                    print(f"{level}hPa数据下载失败，退出...")
                    return
                
                datasets[level] = ds
        
        # 提取数据
        # 获取坐标（从第一个可用数据集）
        coord_ds = surface_ds if surface_ds is not None else list(datasets.values())[0]
        lon = coord_ds.coords['longitude'].values
        lat = coord_ds.coords['latitude'].values
        
        # 提取总可降水量数据
        tcwv_data = None
        if show_tcwv and surface_ds is not None:
            tcwv_data = surface_ds['tcwv'].values.squeeze()
            print(f"提取总可降水量数据")
        
        # 提取位势高度数据
        height_data = None
        if show_height:
            geopotential = datasets[height_level]['z'].values.squeeze()
            height_data = geopotential / 9.80665  # 转换为位势高度 (gpm)
            print(f"提取{height_level}hPa位势高度数据")
        
        # 提取风场数据
        u_wind, v_wind = None, None
        if show_wind:
            u_wind = datasets[wind_level]['u'].values.squeeze()
            v_wind = datasets[wind_level]['v'].values.squeeze()
            print(f"提取{wind_level}hPa风场数据")
        
    else:
        print("错误: 暂不支持从文件加载多层复合数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 计算统计信息
    tcwv_stats = ""
    height_stats = ""
    wind_stats = ""
    
    if show_tcwv and tcwv_data is not None:
        min_tcwv = np.min(tcwv_data)
        max_tcwv = np.max(tcwv_data)
        tcwv_stats = f"TCWV: {min_tcwv:.1f}-{max_tcwv:.1f}kg/m²"
    
    if show_height and height_data is not None:
        height_data_smooth = gaussian_filter(height_data, sigma=smooth_sigma)
        min_height = np.min(height_data_smooth)
        max_height = np.max(height_data_smooth)
        height_stats = f"Height: {min_height:.0f}-{max_height:.0f}gpm"
    
    if show_wind and u_wind is not None and v_wind is not None:
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        max_wind = np.max(wind_speed)
        wind_stats = f"Wind: max {max_wind:.1f}m/s"
    
    print(f"数据统计: {tcwv_stats} {height_stats} {wind_stats}")
    
    # 设置字体
    try:
        import matplotlib.font_manager as font_manager
        font_manager.fontManager.addfont(r'MeteoStation\MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']
    except:
        print("无法加载MiSans字体，使用系统默认字体")
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图形
    fig = plt.figure(figsize=(15, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    # 设置地图范围
    ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], 
                  crs=ccrs.PlateCarree())
    
    # 绘制总可降水量填充（底层）
    contourf = None
    if show_tcwv and tcwv_data is not None:
        tcwv_colors, tcwv_points, min_tcwv_display, max_tcwv_display = get_tcwv_color_scheme()
        
        # 创建总可降水量配色映射
        color_positions = []
        valid_colors = []
        
        for i, tcwv in enumerate(tcwv_points):
            if i < len(tcwv_colors):
                pos = (tcwv - min_tcwv_display) / (max_tcwv_display - min_tcwv_display)
                pos = max(0, min(1, pos))
                color_positions.append(pos)
                valid_colors.append(tcwv_colors[i])
        
        # 确保位置列表是递增的
        sorted_pairs = sorted(zip(color_positions, valid_colors))
        color_positions, valid_colors = zip(*sorted_pairs)
        color_positions = list(color_positions)
        valid_colors = list(valid_colors)
        
        # 确保颜色位置列表以0开始，以1结束
        if color_positions[0] > 0:
            color_positions.insert(0, 0)
            valid_colors.insert(0, valid_colors[0])
        
        if color_positions[-1] < 1:
            color_positions.append(1)
            valid_colors.append(valid_colors[-1])
        
        # 移除重复的位置
        unique_positions = []
        unique_colors = []
        for i, (pos, color) in enumerate(zip(color_positions, valid_colors)):
            if i == 0 or pos > color_positions[i-1]:
                unique_positions.append(pos)
                unique_colors.append(color)
        
        # 创建色彩映射
        cmap = LinearSegmentedColormap.from_list(
            'tcwv_cmap', 
            list(zip(unique_positions, unique_colors)),
            N=256
        )
        
        # 绘制总可降水量填充等高线
        from matplotlib.colors import Normalize
        norm = Normalize(vmin=min_tcwv_display, vmax=max_tcwv_display)
        
        tcwv_levels_plot = np.linspace(min_tcwv_display, max_tcwv_display, 100)
        
        contourf = ax.contourf(
            lon_grid, lat_grid, tcwv_data,
            levels=tcwv_levels_plot, 
            cmap=cmap, 
            norm=norm,
            transform=ccrs.PlateCarree(), 
            alpha=0.8, 
            extend='both'
        )
        
        print(f"绘制总可降水量填充")
    
    # 绘制位势高度等值线（中层）
    if show_height and height_data is not None:
        # 确定等高线间距
        if height_contour_interval is None:
            interval = get_height_contour_interval(height_level)
        else:
            interval = height_contour_interval
        
        # 计算等高线级别
        height_min_round = int(min_height // interval) * interval
        height_max_round = int(max_height // interval + 1) * interval
        height_levels = np.arange(height_min_round, height_max_round + interval, interval)
        
        # 绘制等高线
        contour = ax.contour(
            lon_grid, lat_grid, height_data_smooth, 
            levels=height_levels, 
            colors='black', 
            linewidths=1.5,
            alpha=1.0,
            transform=ccrs.PlateCarree()
        )
        ax.clabel(contour, inline=True, fontsize=9, fmt='%d')
        
        print(f"绘制位势高度等值线: {height_level}hPa, 间距: {interval}gpm")
    
    # 绘制风场矢量（顶层）
    if show_wind and u_wind is not None and v_wind is not None:
        # 为风标降采样
        skip_factor = max(1, min(u_wind.shape) // wind_density)
        
        barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
        ax.barbs(
            lon_grid[barb_slice], lat_grid[barb_slice],
            u_wind[barb_slice], v_wind[barb_slice],
            length=5, pivot='middle', color='darkblue', alpha=0.8,
            transform=ccrs.PlateCarree()
        )
        
        print(f"绘制风场矢量: {wind_level}hPa, 密度: 每{skip_factor}个网格点")
    
    # 添加海岸线和边界
    try:
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        
        if use_china_boundaries:
            china_boundaries_added = add_china_boundaries(
                ax, 
                lon_min=lon.min(), 
                lon_max=lon.max(),
                lat_min=lat.min(), 
                lat_max=lat.max()
            )
            
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
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(lon.min()), 
                                           np.ceil(lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(lat.min()), 
                                           np.ceil(lat.max()) + 1, 5))

    # 创建色彩条（如果显示总可降水量）
    if show_tcwv and contourf is not None:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
        
        # 设置色彩条刻度
        tick_interval = 10
        tick_start = int(min_tcwv_display // tick_interval) * tick_interval
        tick_end   = int(max_tcwv_display // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
        
        cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                           ticks=colorbar_ticks, label='Total Column Water Vapour (kg/m²)')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 构建标题
    title_parts = []
    if show_tcwv:
        title_parts.append('TCWV')
    if show_height:
        title_parts.append(f'{height_level}hPa GPH')
    if show_wind:
        title_parts.append(f'{wind_level}hPa Wind')
    
    main_title = f'{data_source} ' + ' + '.join(title_parts)
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    # 左侧标题
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧标题
    stats_lines = []
    if tcwv_stats:
        stats_lines.append(tcwv_stats)
    if height_stats:
        stats_lines.append(height_stats)
    if wind_stats:
        stats_lines.append(wind_stats)
    
    ax.text(0.99, 1.015, '\n'.join(stats_lines), transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=12, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"图像已保存: {output_image_path}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024072400'
    height_level = 500  # 位势高度层面
    wind_level = 850  # 风场层面
    
    draw_multi_level_composite_tcwv(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_{height_level}GPH_TCWV_{wind_level}Wind_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        show_tcwv=True,
        show_height=True,
        height_level=height_level,
        height_contour_interval=None,
        show_wind=True,
        wind_level=wind_level,
        wind_density=20
    )