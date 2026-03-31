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

def download_era5_data(date, pressure_level, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5再分析数据
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
        temp_filename = f"era5_temp_{os.getpid()}_{date}_{pressure_level}.nc"
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
        print(f"下载ERA5数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def calculate_vorticity_divergence(u_wind, v_wind, lon, lat):
    """
    计算相对涡度和散度
    
    参数:
    u_wind, v_wind : 2D array - U和V风分量 (m/s)
    lon, lat : 1D array - 经纬度坐标
    
    返回:
    vorticity : 2D array - 相对涡度 (s^-1)
    divergence : 2D array - 散度 (s^-1)
    """
    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 计算网格间距（米）
    earth_radius = 6.371e6  # 地球半径 (m)
    deg_to_rad = np.pi / 180
    
    # 经度方向的网格间距（随纬度变化）
    dx = earth_radius * np.cos(lat_grid * deg_to_rad) * (lon[1] - lon[0]) * deg_to_rad
    # 纬度方向的网格间距（常数）
    dy = earth_radius * (lat[1] - lat[0]) * deg_to_rad
    
    # 计算偏导数
    # ∂u/∂x
    du_dx = np.zeros_like(u_wind)
    du_dx[:, 1:-1] = (u_wind[:, 2:] - u_wind[:, :-2]) / (2 * dx[:, 1:-1])
    du_dx[:, 0] = (u_wind[:, 1] - u_wind[:, 0]) / dx[:, 0]
    du_dx[:, -1] = (u_wind[:, -1] - u_wind[:, -2]) / dx[:, -1]
    
    # ∂v/∂y  
    dv_dy = np.zeros_like(v_wind)
    dv_dy[1:-1, :] = (v_wind[2:, :] - v_wind[:-2, :]) / (2 * dy)
    dv_dy[0, :] = (v_wind[1, :] - v_wind[0, :]) / dy
    dv_dy[-1, :] = (v_wind[-1, :] - v_wind[-2, :]) / dy
    
    # ∂u/∂y
    du_dy = np.zeros_like(u_wind)
    du_dy[1:-1, :] = (u_wind[2:, :] - u_wind[:-2, :]) / (2 * dy)
    du_dy[0, :] = (u_wind[1, :] - u_wind[0, :]) / dy
    du_dy[-1, :] = (u_wind[-1, :] - u_wind[-2, :]) / dy
    
    # ∂v/∂x
    dv_dx = np.zeros_like(v_wind)
    dv_dx[:, 1:-1] = (v_wind[:, 2:] - v_wind[:, :-2]) / (2 * dx[:, 1:-1])
    dv_dx[:, 0] = (v_wind[:, 1] - v_wind[:, 0]) / dx[:, 0]
    dv_dx[:, -1] = (v_wind[:, -1] - v_wind[:, -2]) / dx[:, -1]
    
    # 计算相对涡度: ζ = ∂v/∂x - ∂u/∂y
    vorticity = dv_dx - du_dy
    
    # 计算散度: D = ∂u/∂x + ∂v/∂y
    divergence = du_dx + dv_dy
    
    return vorticity, divergence

def get_vorticity_color_scheme():
    """
    返回涡度配色方案（橙-白-青渐变）
    """
    # 负涡度（橙色系） -> 零（白色） -> 正涡度（青色系）
    colors = [
        "#FF6B35",   # 深橙色 (强负涡度)
        "#FF9F4B",   # 橙色 
        '#FFE4C4',   # 浅橙色
        '#FFFFFF',   # 零涡度 (白色)
        "#7CE0D9",   # 浅青色
        "#4FC3D7",   # 青色
        "#2BA5C4"    # 深青色 (强正涡度)
    ]
    
    # 使用更多级别来创建平滑渐变
    levels = np.linspace(-15, 15, 101)  # 101个级别用于平滑渐变
    
    return colors, levels

def get_divergence_color_scheme():
    """
    返回散度配色方案（黄-白-蓝渐变）
    """
    # 负散度/辐合（黄色系） -> 零（白色） -> 正散度/辐散（蓝色系）
    colors = [
        "#FFA500",   # 深橙黄色 (强辐合)
        "#FFD900",   # 黄色
        '#FFFACD',   # 浅黄色
        '#FFFFFF',   # 零散度 (白色)
        "#87CEEB",   # 浅蓝色
        "#5FB5D1",   # 蓝色
        "#4682B4"    # 深蓝色 (强辐散)
    ]
    
    # 使用更多级别来创建平滑渐变
    levels = np.linspace(-30, 30, 121)  # 121个级别用于平滑渐变
    
    return colors, levels

def get_height_contour_interval(pressure_level):
    """
    根据气压层返回相应的等高线间距
    """
    if pressure_level >= 850:
        return 15
    elif pressure_level >= 500:
        return 20
    elif pressure_level >= 350:
        return 50
    elif pressure_level >= 200:
        return 60
    elif pressure_level >= 100:
        return 100
    elif pressure_level >= 30:
        return 200
    else:
        return 500

def draw_vorticity_divergence_with_height(date_str='2024072400', 
                                        output_image_path_vort='Output/MeteoMap/vorticity_with_height.png',
                                        output_image_path_div='Output/MeteoMap/divergence_with_height.png',
                                        pressure_level=500,  # 位势高度气压层
                                        vort_div_pressure_level=None,  # 涡度散度气压层
                                        hour=0, 
                                        lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                                        data_source='ERA5', smooth_sigma=1, download_data=True,
                                        use_china_boundaries=True):
    """
    绘制涡度场和散度场，叠加位势高度等值线
    
    参数:
    output_image_path_vort : str - 涡度图输出路径
    output_image_path_div : str - 散度图输出路径
    pressure_level : int - 位势高度气压层 (hPa)
    vort_div_pressure_level : int or None - 涡度散度气压层 (hPa)。如果为None，则使用与高度场相同的层次
    """
    
    # 如果未指定涡度散度气压层，则使用高度气压层
    if vort_div_pressure_level is None:
        vort_div_pressure_level = pressure_level
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path_vort), exist_ok=True)
    os.makedirs(os.path.dirname(output_image_path_div), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据...")
        print(f"位势高度层: {pressure_level}hPa, 涡度散度层: {vort_div_pressure_level}hPa")
        
        # 获取需要的唯一气压层
        levels_needed = list(set([pressure_level, vort_div_pressure_level]))
        
        # 下载所有需要层次的数据
        datasets = {}
        for level in levels_needed:
            print(f"正在下载 {level}hPa 数据...")
            ds = download_era5_data(
                date=date_str,
                pressure_level=level,
                variables=['geopotential', 'u_component_of_wind', 'v_component_of_wind'],
                lon_min=lon_min,
                lon_max=lon_max,
                lat_min=lat_min,
                lat_max=lat_max
            )
            
            if ds is None:
                print(f"{level}hPa数据下载失败，退出...")
                return
            
            datasets[level] = ds
        
        # 从指定层提取位势高度数据
        height_ds = datasets[pressure_level]
        geopotential = height_ds['z'].values.squeeze()
        height = geopotential / 9.80665  # 转换为位势高度 (gpm)
        
        # 从指定层提取风场数据
        wind_ds = datasets[vort_div_pressure_level]
        u_wind = wind_ds['u'].values.squeeze()
        v_wind = wind_ds['v'].values.squeeze()
        
        # 获取坐标（假设两个层次使用相同网格）
        lon = height_ds.coords['longitude'].values
        lat = height_ds.coords['latitude'].values
        
    else:
        print("错误: 暂不支持从文件加载数据")
        return

    # 计算涡度和散度
    print("正在计算涡度和散度...")
    vorticity, divergence = calculate_vorticity_divergence(u_wind, v_wind, lon, lat)
    
    # 转换为常用单位 (×10^-5 s^-1)
    vorticity_scaled = vorticity * 1e5
    divergence_scaled = divergence * 1e5
    
    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 平滑数据
    if smooth_sigma > 0:
        height_smooth = gaussian_filter(height, sigma=smooth_sigma)
        vorticity_smooth = gaussian_filter(vorticity_scaled, sigma=smooth_sigma)
        divergence_smooth = gaussian_filter(divergence_scaled, sigma=smooth_sigma)
    else:
        height_smooth = height
        vorticity_smooth = vorticity_scaled
        divergence_smooth = divergence_scaled
    
    # 计算统计信息
    min_height = np.min(height_smooth)
    max_height = np.max(height_smooth)
    max_vort = np.max(np.abs(vorticity_smooth))
    max_div = np.max(np.abs(divergence_smooth))
    
    print(f"高度范围: {min_height:.0f} - {max_height:.0f} gpm")
    print(f"最大涡度: ±{max_vort:.1f} ×10^-5 s^-1")
    print(f"最大散度: ±{max_div:.1f} ×10^-5 s^-1")
    
    # 设置字体
    try:
        import matplotlib.font_manager as font_manager
        font_manager.fontManager.addfont(r'MeteoStation\MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']
    except:
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 获取配色方案
    vort_colors, vort_levels = get_vorticity_color_scheme()
    div_colors, div_levels = get_divergence_color_scheme()
    
    # 获取等高线间距（基于位势高度层）
    height_interval = get_height_contour_interval(pressure_level)
    height_min_round = int(min_height // height_interval) * height_interval
    height_max_round = int(max_height // height_interval + 1) * height_interval
    height_levels = np.arange(height_min_round, height_max_round + height_interval, height_interval)
    
    # 格式化日期
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 绘制涡度图
    print("正在绘制涡度图...")
    fig = plt.figure(figsize=(15, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], crs=ccrs.PlateCarree())
    
    # 创建涡度颜色映射 - 平滑渐变
    vort_cmap = LinearSegmentedColormap.from_list(
        'vorticity_cmap', 
        vort_colors,
        N=256  # 增加颜色级别数量以获得更平滑的渐变
    )
    
    # 绘制涡度填充 - 使用平滑级别
    vort_contourf = ax.contourf(lon_grid, lat_grid, vorticity_smooth, 
                               levels=vort_levels, cmap=vort_cmap, 
                               transform=ccrs.PlateCarree(), alpha=0.8, extend='both')
    
    # 绘制位势高度等值线
    contour = ax.contour(lon_grid, lat_grid, height_smooth, levels=height_levels, 
                        colors='black', linewidths=1.5, alpha=1.0, transform=ccrs.PlateCarree())
    ax.clabel(contour, inline=True, fontsize=9, fmt='%d', colors='black')
    
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
    cbar = plt.colorbar(vort_contourf, cax=cax, orientation='vertical', 
                       label='Relative Vorticity (×10⁻⁵ s⁻¹)')
    # 设置色彩条刻度为主要值
    cbar.set_ticks([-10, -5, 0, 5, 10])
    
    # 添加标题
    if pressure_level == vort_div_pressure_level:
        main_title = f'{data_source} {pressure_level}hPa Relative Vorticity and Geopotential Height'
    else:
        main_title = f'{data_source} {vort_div_pressure_level}hPa Vorticity + {pressure_level}hPa Height'
    
    time_title = f'{date_display} +{hour}h' if hour > 0 else date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', fontsize=14, fontweight='bold', color='black')
    
    # 右侧统计信息
    stats_text = f'Height: {min_height:.0f}-{max_height:.0f}gpm\nMax Vorticity: ±{max_vort:.1f}×10⁻⁵s⁻¹'
    ax.text(0.99, 1.015, stats_text, transform=ax.transAxes, 
            ha='right', va='bottom', fontsize=10, color='black')
    
    # 保存涡度图
    plt.savefig(output_image_path_vort, bbox_inches='tight', dpi=300)
    print(f"涡度图已保存: {output_image_path_vort}")
    plt.close()
    
    # 绘制散度图
    print("正在绘制散度图...")
    fig = plt.figure(figsize=(15, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], crs=ccrs.PlateCarree())
    
    # 创建散度颜色映射 - 平滑渐变
    div_cmap = LinearSegmentedColormap.from_list(
        'divergence_cmap', 
        div_colors,
        N=256  # 增加颜色级别数量以获得更平滑的渐变
    )
    
    # 绘制散度填充 - 使用平滑级别
    div_contourf = ax.contourf(lon_grid, lat_grid, divergence_smooth, 
                              levels=div_levels, cmap=div_cmap, 
                              transform=ccrs.PlateCarree(), alpha=0.8, extend='both')
    
    # 绘制位势高度等值线
    contour = ax.contour(lon_grid, lat_grid, height_smooth, levels=height_levels, 
                        colors='black', linewidths=1.5, alpha=1.0, transform=ccrs.PlateCarree())
    ax.clabel(contour, inline=True, fontsize=9, fmt='%d', colors='black')
    
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
    cbar = plt.colorbar(div_contourf, cax=cax, orientation='vertical', 
                       label='Divergence (×10⁻⁵ s⁻¹)')
    # 设置色彩条刻度为主要值
    cbar.set_ticks([-20, -10, -5, 0, 5, 10, 20])
    
    # 添加标题
    if pressure_level == vort_div_pressure_level:
        main_title = f'{data_source} {pressure_level}hPa Divergence and Geopotential Height'
    else:
        main_title = f'{data_source} {vort_div_pressure_level}hPa Divergence + {pressure_level}hPa Height'
    
    time_title = f'{date_display} +{hour}h' if hour > 0 else date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', fontsize=14, fontweight='bold', color='black')
    
    # 右侧统计信息
    stats_text = f'Height: {min_height:.0f}-{max_height:.0f}gpm\nMax Divergence: ±{max_div:.1f}×10⁻⁵s⁻¹'
    ax.text(0.99, 1.015, stats_text, transform=ax.transAxes, 
            ha='right', va='bottom', fontsize=10, color='black')
    
    # 保存散度图
    plt.savefig(output_image_path_div, bbox_inches='tight', dpi=300)
    print(f"散度图已保存: {output_image_path_div}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024072400'
    height_level = 500   # 位势高度层面
    vort_div_level = 300 # 涡度散度层面
    
    print(f"正在生成涡度散度图...")
    print(f"位势高度层: {height_level}hPa, 涡度散度层: {vort_div_level}hPa")
    
    try:
        draw_vorticity_divergence_with_height(
            date_str=date_str, 
            output_image_path_vort=f'Output/MeteoMap/ERA5_{vort_div_level}Vort_{height_level}GPH_{date_str}.png',
            output_image_path_div=f'Output/MeteoMap/ERA5_{vort_div_level}Div_{height_level}GPH_{date_str}.png',
            pressure_level=height_level,  # 位势高度层面
            vort_div_pressure_level=vort_div_level,  # 涡度散度层面
            hour=0,
            lon_min=80, 
            lon_max=140, 
            lat_min=20, 
            lat_max=55,
            download_data=True,
            use_china_boundaries=True
        )
        print(f"✅ 涡度和散度图生成完成")
        print(f"📁 涡度图: Output/MeteoMap/ERA5_{vort_div_level}Vort_{height_level}GPH_{date_str}.png")
        print(f"📁 散度图: Output/MeteoMap/ERA5_{vort_div_level}Div_{height_level}GPH_{date_str}.png")
        
    except Exception as e:
        print(f"❌ 图像生成失败: {e}")
        import traceback
        traceback.print_exc()