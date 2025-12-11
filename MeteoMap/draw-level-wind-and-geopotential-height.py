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

def download_era5_data(date, pressure_level, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5再分析数据
    
    参数:
    date : str - 日期时间字符串 (YYYYMMDDHH)
    pressure_level : int - 气压层 (hPa)
    variables : list - 要下载的变量列表
    lon_min, lon_max, lat_min, lat_max : float - 地理边界
    
    返回:
    xr.Dataset - 包含下载数据的数据集
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
        temp_filename = f"era5_temp_{os.getpid()}_{date}_{pressure_level}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        # 删除已存在的临时文件
        if os.path.exists(output_file):
            os.remove(output_file)
            
        # 下载ERA5数据
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
        print(f"下载ERA5数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def get_wind_color_scheme(pressure_level):
    """
    根据气压层返回相应的风速配色方案
    """
    if pressure_level >= 750:  # 对流层低层
        colors = [
            '#FFFFFF', '#D1D1D1', '#188FD8', '#34D259', 
            '#F1B04D', '#FF6200', '#FF0000', '#9C2EBA', '#FF00FF', '#EA00FF'
        ]
        levels = [i * 5 for i in range(10)]  # 0-45 m/s
        max_display = 56
    elif pressure_level >= 400:  # 对流层中层
        colors = [
            '#FFFFFF', '#D1D1D1', '#188FD8', '#34D259', 
            '#F1B04D', '#FF6200', '#FF0000', '#9C2EBA', '#FF00FF', '#EA00FF'
        ]
        levels = [i * 6 for i in range(10)]  # 0-54 m/s
        max_display = 68
    elif pressure_level >= 200:  # 对流层高层
        colors = [
            '#FFFFFF', '#D1D1D1', '#188FD8', '#34D259',
            '#F1B04D', '#FF6200', '#FF0000', '#9C2EBA', '#FF00FF', '#EA00FF'
        ]
        levels = [i * 8 for i in range(10)]  # 0-72 m/s
        max_display = 84
    else:  # 平流层中高层 (10-25hPa等)
        colors = [
            '#FFFFFF', '#D1D1D1', '#188FD8', '#34D259',
            '#F1B04D', '#FF6200', '#FF0000', '#9C2EBA', '#FF00FF', '#EA00FF'
        ]
        levels = [i * 10 for i in range(10)]  # 0-90 m/s
        max_display = 104
    
    return colors, levels, max_display

def get_height_contour_interval(pressure_level):
    """
    根据气压层返回相应的等高线间距
    """
    if pressure_level >= 850:
        return 15  # 边界层
    elif pressure_level >= 500:
        return 20  # 对流层中层
    elif pressure_level >= 350:
        return 50  # 对流层中高层
    elif pressure_level >= 200:
        return 60  # 对流层顶/平流层底
    elif pressure_level >= 100:
        return 100  # 平流层低层
    elif pressure_level >= 30:
        return 200  # 平流层中高层
    else:
        return 500  # 平流层高层

def draw_height_and_wind(date_str='2017082409', pressure_level=600, wind_pressure_level=None, 
                        file_path=None, output_image_path='Output/MeteoMap/map.png', hour=0, 
                        lon_min=80, lon_max=120, lat_min=20, lat_max=40, 
                        data_source='ERA5', smooth_sigma=1, download_data=True,
                        use_china_boundaries=True):
    """
    绘制指定气压层的位势高度场和风场
    
    参数:
    pressure_level : int - 位势高度气压层 (hPa)
    wind_pressure_level : int or None - 风场气压层 (hPa)。如果为None，则使用与高度场相同的层次
    use_china_boundaries : bool - 是否使用DataV.GeoAtlas的中国官方边界
    """
    
    # 如果未指定风压层，则使用高度压层
    if wind_pressure_level is None:
        wind_pressure_level = pressure_level
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    # 数据获取
    if download_data and file_path is None:
        print(f"正在下载 {date_str} 的ERA5数据...")
        print(f"位势高度层: {pressure_level}hPa, 风场层: {wind_pressure_level}hPa")
        
        # 获取需要的唯一气压层
        levels_needed = list(set([pressure_level, wind_pressure_level]))
        
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
        
        # 从指定层提取位势数据并转换为位势高度
        height_ds = datasets[pressure_level]
        geopotential = height_ds['z'].values.squeeze()  # 位势 (m²/s²)
        height = geopotential / 9.80665  # 转换为位势高度 (gpm)
        
        # 从指定层提取风场数据
        wind_ds = datasets[wind_pressure_level]
        u_wind = wind_ds['u'].values.squeeze()  # U风分量 (m/s)
        v_wind = wind_ds['v'].values.squeeze()  # V风分量 (m/s)
        
        # 获取坐标（假设两个层次使用相同网格）
        lon = height_ds.coords['longitude'].values
        lat = height_ds.coords['latitude'].values
        
    elif file_path is not None:
        # 从文件加载数据 - 对于文件输入，假设高度和风使用相同层次
        try:
            if file_path.endswith('.npy'):
                # 处理numpy格式
                data = np.load(file_path)
                geopotential = data[0]  
                # 如果需要，转换位势为位势高度
                if np.max(geopotential) > 100000:  # 检查数据是否为位势 (m²/s²)
                    height = geopotential / 9.80665  # 转换为gpm
                else:
                    height = geopotential  # 已经是gpm
                u_wind = data[1]
                v_wind = data[2]
                
                # 创建坐标网格
                lon = np.linspace(0, 360, height.shape[1])
                lat = np.linspace(90, -90, height.shape[0])
                
            elif file_path.endswith(('.nc', '.grib', '.grb')):
                # 处理NetCDF或GRIB格式
                try:
                    if file_path.endswith('.nc'):
                        ds = xr.open_dataset(file_path)
                    else:
                        for engine in ['netcdf4', 'cfgrib']:
                            try:
                                ds = xr.open_dataset(file_path, engine=engine)
                                break
                            except:
                                continue
                        else:
                            print("错误: 无法使用可用引擎打开文件")
                            print("尝试: pip install cfgrib eccodes")
                            return
                
                    # 如果需要，按气压层过滤 - 对文件输入使用高度层
                    if 'level' in ds.dims:
                        ds = ds.sel(level=pressure_level)
                
                    # 获取变量（尝试各种可能的名称）
                    var_mappings = {
                        'geopotential': ['z', 'gh', 'hgt'],
                        'u_wind': ['u', 'uwnd'],
                        'v_wind': ['v', 'vwnd']
                    }
                    
                    data_vars = {}
                    for var_name, possible_names in var_mappings.items():
                        for name in possible_names:
                            if name in ds:
                                data_vars[var_name] = ds[name].values
                                break
                        else:
                            print(f"错误: 找不到 {var_name} 变量")
                            print("可用变量:", list(ds.variables))
                            return
                    
                    geopotential = data_vars['geopotential']
                    # 如果需要，转换位势为位势高度
                    if np.max(geopotential) > 100000:  # 检查数据是否为位势 (m²/s²)
                        height = geopotential / 9.80665  # 使用标准重力转换为gpm
                    else:
                        height = geopotential  # 已经是gpm
                        
                    u_wind = data_vars['u_wind']
                    v_wind = data_vars['v_wind']
                    
                    # 获取坐标
                    lon = ds.coords['longitude'].values if 'longitude' in ds.coords else ds.coords['lon'].values
                    lat = ds.coords['latitude'].values if 'latitude' in ds.coords else ds.coords['lat'].values
                    
                except Exception as e:
                    print(f"读取文件时出错: {e}")
                    return
            else:
                print(f"不支持的文件格式: {file_path}")
                return
        except Exception as e:
            print(f"处理文件时出错: {e}")
            return
    else:
        print("错误: 未指定数据文件路径且download_data=False")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 计算风速
    wind_speed = np.sqrt(u_wind**2 + v_wind**2)
    
    # 如果使用原始文件，提取感兴趣的区域
    if not download_data:
        # 获取指定范围的索引
        lon_indices = np.where((lon >= lon_min) & (lon <= lon_max))[0]
        lat_indices = np.where((lat >= lat_min) & (lat <= lat_max))[0]
        
        # 提取区域数据
        region_height = height[np.ix_(lat_indices, lon_indices)]
        region_u_wind = u_wind[np.ix_(lat_indices, lon_indices)]
        region_v_wind = v_wind[np.ix_(lat_indices, lon_indices)]
        region_wind_speed = wind_speed[np.ix_(lat_indices, lon_indices)]
        region_lon = lon[lon_indices]
        region_lat = lat[lat_indices]
    else:
        # 已经下载了指定区域的数据
        region_height = height
        region_u_wind = u_wind
        region_v_wind = v_wind
        region_wind_speed = wind_speed
        region_lon, region_lat = lon, lat
    
    # 平滑位势高度数据
    region_height_smooth = gaussian_filter(region_height, sigma=smooth_sigma)
    
    # 为风标降采样
    skip_factor = max(1, min(region_height.shape) // 20)
    region_lon_grid, region_lat_grid = np.meshgrid(region_lon, region_lat)
    
    # 计算指标
    max_wind_speed = np.max(region_wind_speed)
    min_height = np.min(region_height_smooth)
    max_height = np.max(region_height_smooth)
    print(f"最大风速: {max_wind_speed:.2f} m/s")
    print(f"高度范围: {min_height:.0f} - {max_height:.0f} gpm")
    
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
    
    # 设置地图范围以匹配数据范围
    ax.set_extent([region_lon.min(), region_lon.max(), 
                   region_lat.min(), region_lat.max()], 
                  crs=ccrs.PlateCarree())
    
    # 获取风场压层的风速配色方案
    wind_speed_colors, wind_speed_levels, max_wind_display = get_wind_color_scheme(wind_pressure_level)
    
    # 创建具有适当归一化的颜色映射
    # 确保颜色和级别数量相同
    n_colors = min(len(wind_speed_colors), len(wind_speed_levels))
    colors_normalized = wind_speed_colors[:n_colors]
    
    # 创建从0到1的归一化位置
    color_positions = np.linspace(0, 1, n_colors)
    
    cmap = LinearSegmentedColormap.from_list(
        'wind_speed_cmap', 
        list(zip(color_positions, colors_normalized))
    )

    # 根据实际数据调整最大显示值
    actual_max_wind = min(max_wind_display, max(max_wind_display * 0.7, np.ceil(max_wind_speed / 5) * 5))
    
    # 获取高度压层的等高线间距
    height_interval = get_height_contour_interval(pressure_level)
        
    # 计算等高线级别
    height_min_round = int(min_height // height_interval) * height_interval
    height_max_round = int(max_height // height_interval + 1) * height_interval
    height_levels = np.arange(height_min_round, height_max_round + height_interval, height_interval)
    
    # 绘制风速填充等高线
    contourf = ax.contourf(
        region_lon_grid, region_lat_grid, region_wind_speed, 
        levels=np.linspace(0, actual_max_wind, 100), 
        cmap=cmap, 
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='max'
    )
    
    # 添加位势高度等高线 - 根据高度层调整样式
    if pressure_level >= 500:
        contour_linewidth = 1.5
        contour_alpha = 1.0
    elif pressure_level >= 200:
        contour_linewidth = 1.2
        contour_alpha = 0.9
    else:
        contour_linewidth = 1.0
        contour_alpha = 0.8
    
    contour = ax.contour(
        region_lon_grid, region_lat_grid, region_height_smooth, 
        levels=height_levels, 
        colors='black', 
        linewidths=contour_linewidth,
        alpha=contour_alpha
    )
    
    # 根据高度压层调整标签字体大小
    if pressure_level >= 500:
        label_fontsize = 10
    elif pressure_level >= 200:
        label_fontsize = 9
    else:
        label_fontsize = 8
        
    ax.clabel(contour, inline=True, fontsize=label_fontsize, fmt='%d')
    
    # 绘制风标
    barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    ax.barbs(
        region_lon_grid[barb_slice], region_lat_grid[barb_slice],
        region_u_wind[barb_slice], region_v_wind[barb_slice],
        length=5, pivot='middle', color='black'
    )
    
    # 添加海岸线和边界 - 用户选择
    try:
        # 先添加基础海岸线
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        
        if use_china_boundaries:
            # 使用中国官方边界
            print("使用DataV.GeoAtlas中国官方边界")
            china_boundaries_added = add_china_boundaries(
                ax, 
                lon_min=region_lon.min(), 
                lon_max=region_lon.max(),
                lat_min=region_lat.min(), 
                lat_max=region_lat.max()
            )
            
            if not china_boundaries_added:
                print("添加中国边界失败，使用cartopy默认边界")
                ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
        else:
            # 使用cartopy默认边界
            print("使用cartopy默认边界")
            ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
        
    except Exception as e:
        print(f"添加边界时出错: {e}")
        print("使用cartopy默认边界")
        ax.coastlines(resolution='50m')
        ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
    
    # 添加网格线 - 确保它们匹配数据范围
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.7)
    gl.top_labels = False
    gl.right_labels = False
    # 设置网格线的范围
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(region_lon.min()), 
                                           np.ceil(region_lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(region_lat.min()), 
                                           np.ceil(region_lat.max()) + 1, 5))

    # 创建带有适当刻度的色彩条
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    # 根据风速级别设置色彩条刻度 - 使用较少的刻度以保持清晰
    colorbar_ticks = [level for i, level in enumerate(wind_speed_levels[:n_colors]) if i % 2 == 0]
    
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label='Wind Speed (m/s)')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 固定标题间距，稍微加高
    title_spacing = 0.025  # 固定间距，稍微加高
    
    # 左侧标题 - 两行固定间距
    if pressure_level == wind_pressure_level:
        main_title = f'{data_source} {pressure_level}hPa Geopotential Height(gpm) and Wind(m/s)'
    else:
        main_title = f'{data_source} {pressure_level}hPa Height(gpm) + {wind_pressure_level}hPa Wind(m/s)'
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    # 设置左侧标题（主标题和时间）
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧标题 - 两行固定间距，往上抬一点
    height_range_line = f'Height: {min_height:.0f}-{max_height:.0f}gpm'
    max_wind_line = f'Max Wind: {max_wind_speed:.1f}m/s'
    
    ax.text(0.99, 1.015, height_range_line+'\n'+max_wind_line, transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=14, color='black')
    
    # 添加边界使用说明到图片信息
    boundary_info = "China Official Boundaries" if use_china_boundaries else "Cartopy Default Boundaries"
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"Image saved to: {output_image_path}")
    print(f"Configuration - Height({pressure_level}hPa) interval: {height_interval}gpm, Wind({wind_pressure_level}hPa) max: {actual_max_wind:.0f}m/s")
    print(f"Boundaries: {boundary_info}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024072400'  
    height_level = 500  # 位势高度层面
    wind_level = 300    # 风速层面
    
    draw_height_and_wind(
        date_str=date_str, 
        pressure_level=height_level,  # 位势高度层面
        wind_pressure_level=wind_level,  # 风速层面
        output_image_path=f'Output/MeteoMap/ERA5_{height_level}GPH_{wind_level}Wind_{date_str}.png', 
        lon_min=90, 
        lon_max=130, 
        lat_min=20, 
        lat_max=40,
        download_data=True,
        use_china_boundaries=True  # 新参数：是否使用中国官方边界
    )
