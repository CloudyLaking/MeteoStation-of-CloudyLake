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

def download_era5_pressure_data(date, pressure_level, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5气压层数据
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
        temp_filename = f"era5_pressure_temp_{os.getpid()}_{date}_{pressure_level}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
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

def get_cape_color_scheme():
    """
    返回CAPE值配色方案 (J/kg)
    """
    # 从白色到浅红色的色阶
    colors = [
        "#FFFFFF",  # 白色 (0 J/kg)
        "#FFFFFF",  # 极浅红 (500 J/kg)
        "#FFB0B0",  # (1000 J/kg)
        "#FF6666",  # (2000 J/kg)
        "#FF0000",  # 浅红 (3000 J/kg)
        "#FF9900",  # (4000 J/kg)
        "#FFEA00",  # 中等红色 (5000 J/kg)
    ]
    
    cape_points = [0, 500, 1000, 2000, 3000, 4000, 5000]
    min_cape, max_cape = 0, 5000
    
    return colors, cape_points, min_cape, max_cape

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

def draw_cape_composite(date_str='2024072400', 
                       output_image_path='Output/MeteoMap/cape_composite.png',
                       hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                       data_source='ERA5', smooth_sigma=1, download_data=True,
                       use_china_boundaries=True,
                       # CAPE设置
                       show_cape=True,
                       # 位势高度等值线设置
                       show_height_contour=True, 
                       height_contour_level=500,
                       height_contour_interval=None,
                       # 风场设置
                       show_wind=True,
                       wind_level=850,
                       wind_density=20):
    """
    绘制CAPE复合图：CAPE填充 + 位势高度等值线 + 风场矢量
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    show_cape : bool - 是否显示CAPE填充
    height_contour_level : int - 位势高度等值线层面 (hPa)
    wind_level : int - 风场层面 (hPa)
    show_height_contour : bool - 是否显示位势高度等值线
    show_wind : bool - 是否显示风场矢量
    wind_density : int - 风矢量密度
    height_contour_interval : int or None - 位势高度等值线间距，None表示自动
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据...")
        
        # 下载地面数据（CAPE）
        surface_ds = None
        if show_cape:
            print("正在下载地面数据（CAPE）...")
            surface_ds = download_era5_surface_data(
                date=date_str,
                variables=['convective_available_potential_energy'],
                lon_min=lon_min,
                lon_max=lon_max,
                lat_min=lat_min,
                lat_max=lat_max
            )
            
            if surface_ds is None:
                print("地面数据下载失败，退出...")
                return
        
        # 收集需要下载的气压层
        pressure_levels_needed = set()
        
        if show_height_contour:
            pressure_levels_needed.add(height_contour_level)
            
        if show_wind:
            pressure_levels_needed.add(wind_level)
        
        # 下载气压层数据
        datasets = {}
        for level in pressure_levels_needed:
            print(f"正在下载 {level}hPa 数据...")
            variables = []
            
            # 收集该层需要的变量
            if show_height_contour and height_contour_level == level:
                variables.append('geopotential')
            if show_wind and wind_level == level:
                variables.extend(['u_component_of_wind', 'v_component_of_wind'])
            
            # 去重
            variables = list(set(variables))
            
            if variables:
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
        
        # 提取坐标
        coord_ds = surface_ds if surface_ds is not None else list(datasets.values())[0]
        lon = coord_ds.coords['longitude'].values
        lat = coord_ds.coords['latitude'].values
        
        # 提取CAPE数据
        cape_data = None
        if show_cape and surface_ds is not None:
            cape_data = surface_ds['cape'].values.squeeze()
            print(f"提取CAPE数据")
        
        # 提取位势高度等值线数据
        height_contour_data = None
        if show_height_contour:
            geopotential_contour = datasets[height_contour_level]['z'].values.squeeze()
            height_contour_data = geopotential_contour / 9.80665  # 转换为位势高度 (gpm)
            print(f"提取{height_contour_level}hPa位势高度等值线数据")
        
        # 提取风场数据
        u_wind, v_wind = None, None
        if show_wind:
            u_wind = datasets[wind_level]['u'].values.squeeze()
            v_wind = datasets[wind_level]['v'].values.squeeze()
            print(f"提取{wind_level}hPa风场数据")
        
    else:
        print("错误: 暂不支持从文件加载CAPE复合数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 应用平滑
    if smooth_sigma > 0:
        if cape_data is not None:
            cape_data_smooth = gaussian_filter(cape_data, sigma=smooth_sigma)
        else:
            cape_data_smooth = None
        
        if height_contour_data is not None:
            height_contour_smooth = gaussian_filter(height_contour_data, sigma=smooth_sigma)
        else:
            height_contour_smooth = None
    else:
        cape_data_smooth = cape_data
        height_contour_smooth = height_contour_data
    
    # 计算统计信息
    cape_stats = ""
    height_stats = ""
    wind_stats = ""
    
    if show_cape and cape_data_smooth is not None:
        min_cape = np.min(cape_data_smooth)
        max_cape = np.max(cape_data_smooth)
        mean_cape = np.mean(cape_data_smooth)
        cape_stats = f"CAPE: {min_cape:.0f}-{max_cape:.0f}J/kg (avg: {mean_cape:.0f}J/kg)"
    
    if show_height_contour and height_contour_smooth is not None:
        min_height = np.min(height_contour_smooth)
        max_height = np.max(height_contour_smooth)
        height_stats = f"{height_contour_level}hPa Height: {min_height:.0f}-{max_height:.0f}gpm"
    
    if show_wind and u_wind is not None and v_wind is not None:
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        max_wind = np.max(wind_speed)
        wind_stats = f"{wind_level}hPa Wind: max {max_wind:.1f}m/s"
    
    print(f"数据统计: {cape_stats}")
    if height_stats:
        print(f"位势高度统计: {height_stats}")
    if wind_stats:
        print(f"风场统计: {wind_stats}")
    
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
    
    # 绘制CAPE填充（底层）
    contourf = None
    if show_cape and cape_data_smooth is not None:
        cape_colors, cape_points, min_cape_display, max_cape_display = get_cape_color_scheme()
        
        # 创建CAPE配色映射
        color_positions = []
        valid_colors = []
        
        for i, cape in enumerate(cape_points):
            if i < len(cape_colors):
                pos = (cape - min_cape_display) / (max_cape_display - min_cape_display)
                pos = max(0, min(1, pos))
                color_positions.append(pos)
                valid_colors.append(cape_colors[i])
        
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
            'cape_cmap', 
            list(zip(unique_positions, unique_colors)),
            N=256
        )
        
        # 绘制CAPE填充等高线
        from matplotlib.colors import Normalize
        norm = Normalize(vmin=min_cape_display, vmax=max_cape_display)
        
        cape_levels_plot = np.linspace(min_cape_display, max_cape_display, 100)
        
        contourf = ax.contourf(
            lon_grid, lat_grid, cape_data_smooth,
            levels=cape_levels_plot, 
            cmap=cmap, 
            norm=norm,
            transform=ccrs.PlateCarree(), 
            alpha=0.8, 
            extend='max'
        )
        
        print(f"绘制CAPE填充")
    
    # 绘制位势高度等值线（中层）
    if show_height_contour and height_contour_smooth is not None:
        # 确定等高线间距
        if height_contour_interval is None:
            interval = get_height_contour_interval(height_contour_level)
        else:
            interval = height_contour_interval
        
        # 计算等高线级别
        height_min_round = int(min_height // interval) * interval
        height_max_round = int(max_height // interval + 1) * interval
        height_levels = np.arange(height_min_round, height_max_round + interval, interval)
        
        # 绘制等高线
        contour = ax.contour(
            lon_grid, lat_grid, height_contour_smooth, 
            levels=height_levels, 
            colors='black', 
            linewidths=1.5,
            alpha=1.0,
            transform=ccrs.PlateCarree()
        )
        ax.clabel(contour, inline=True, fontsize=9, fmt='%d')
        
        print(f"绘制位势高度等值线: {height_contour_level}hPa, 间距: {interval}gpm")
    
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

    # 创建色彩条（如果显示CAPE）
    if show_cape and contourf is not None:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
        
        # 设置色彩条刻度
        tick_interval = 500  # 每500 J/kg一个刻度
        tick_start = int(min_cape_display // tick_interval) * tick_interval
        tick_end = int(max_cape_display // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
        
        cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                           ticks=colorbar_ticks, label='CAPE (J/kg)')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 构建标题
    title_parts = []
    if show_cape:
        title_parts.append('CAPE')
    if show_height_contour:
        title_parts.append(f'{height_contour_level}hPa GPH')
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
    if cape_stats:
        stats_lines.append(cape_stats)
    if height_stats:
        stats_lines.append(height_stats)
    if wind_stats:
        stats_lines.append(wind_stats)
    
    ax.text(0.99, 1.015, '\n'.join(stats_lines), transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=12, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"CAPE复合图已保存: {output_image_path}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024072400'
    height_level = 500  # 位势高度层面
    wind_level = 850   # 风场层面
    
    draw_cape_composite(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_CAPE_{height_level}GPH_{wind_level}Wind_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        show_cape=True,
        show_height_contour=True,
        height_contour_level=height_level,
        height_contour_interval=None,
        show_wind=True,
        wind_level=wind_level,
        wind_density=20
    )