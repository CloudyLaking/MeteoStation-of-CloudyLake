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

def get_humidity_color_scheme():
    """
    返回湿度配色方案（淡色版本）
    """
    # 简化后的配色方案：从浅棕色平滑过渡到浅蓝色
    colors = [
        "#D2B48C",  # 棕褐色 (0%) - 干燥
        "#F5F5DC",  # 米色 (30%) - 过渡
        "#E0FFFF",  # 淡青色 (60%) - 开始湿润
        "#ADD8E6",  # 浅蓝色 (90%) - 湿润
    ]
    humidity_points = [0, 30, 60, 90]
    min_humidity, max_humidity = 0, 100
    
    return colors, humidity_points, min_humidity, max_humidity

def get_specific_humidity_color_scheme():
    """
    返回比湿配色方案（淡色版本，g/kg）
    """
    colors = [
        "#F5DEB3",  # 小麦色 (0) - 最干燥
        "#F0E68C",  # 卡其色 (2)
        "#FFFACD",  # 柠檬薄纱 (4)
        "#F5FFFA",  # 薄荷奶油 (6)
        "#F0FFFF",  # 天蓝色1 (8)
        "#E0FFFF",  # 浅青色 (10)
        "#B0E0E6",  # 粉蓝色 (12)
        "#ADD8E6",  # 浅蓝色 (14)
        "#87CEEB",  # 天蓝色 (16)
        "#87CEFA",  # 浅天蓝色 (18)
        "#B0C4DE",  # 浅钢蓝色 (20) - 最湿润
    ]
    specific_humidity_points = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
    min_specific_humidity, max_specific_humidity = 0, 20
    
    return colors, specific_humidity_points, min_specific_humidity, max_specific_humidity

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

def calculate_specific_humidity(temp_k, rh_percent, pressure_hpa):
    """
    从温度、相对湿度和气压计算比湿
    
    参数:
    temp_k : np.array - 温度(开尔文)
    rh_percent : np.array - 相对湿度(%)
    pressure_hpa : float - 气压(hPa)
    
    返回:
    np.array - 比湿(g/kg)
    """
    # Magnus公式计算饱和水汽压
    temp_c = temp_k - 273.15
    a = 17.27
    b = 237.7
    
    # 饱和水汽压 (hPa)
    es = 6.112 * np.exp((a * temp_c) / (b + temp_c))
    
    # 实际水汽压 (hPa)
    e = rh_percent / 100.0 * es
    
    # 比湿公式: q = 0.622 * e / (P - 0.378 * e)
    # 转换为 g/kg
    specific_humidity = 0.622 * e / (pressure_hpa - 0.378 * e) * 1000
    
    return specific_humidity

def get_humidity_variables_for_type(humidity_type, humidity_level):
    """
    根据湿度类型返回需要下载的变量
    
    参数:
    humidity_type : str - 湿度类型 ('relative_humidity', 'specific_humidity')
    humidity_level : int or str - 湿度层面
    
    返回:
    list - 需要下载的变量列表
    """
    if humidity_level == '2m':
        # 地面数据
        if humidity_type == 'relative_humidity':
            return ['2m_relative_humidity']
        elif humidity_type == 'specific_humidity':
            return ['2m_temperature', '2m_relative_humidity']  # 比湿需要温度和相对湿度
        else:
            return ['2m_relative_humidity']
    else:
        # 气压层数据
        if humidity_type == 'relative_humidity':
            return ['relative_humidity']
        elif humidity_type == 'specific_humidity':
            return ['temperature', 'relative_humidity']  # 比湿需要温度和相对湿度
        else:
            return ['relative_humidity']

def process_humidity_by_type(datasets, surface_ds, humidity_type, humidity_level):
    """
    根据湿度类型处理湿度数据
    
    参数:
    datasets : dict - 气压层数据集
    surface_ds : xr.Dataset - 地面数据集
    humidity_type : str - 湿度类型
    humidity_level : int or str - 湿度层面
    
    返回:
    np.array - 处理后的湿度数据
    """
    if humidity_level == '2m':
        # 地面数据处理
        if humidity_type == 'relative_humidity':
            humidity_data = surface_ds['r2'].values.squeeze()
            print(f"提取2m相对湿度数据")
        elif humidity_type == 'specific_humidity':
            temp_k = surface_ds['t2m'].values.squeeze()
            rh = surface_ds['r2'].values.squeeze()
            # 地面比湿使用1000hPa近似
            humidity_data = calculate_specific_humidity(temp_k, rh, 1000.0)
            print(f"计算2m比湿数据")
        else:
            humidity_data = surface_ds['r2'].values.squeeze()
            print(f"默认使用2m相对湿度数据")
    else:
        # 气压层数据处理
        ds = datasets[humidity_level]
        
        if humidity_type == 'relative_humidity':
            humidity_data = ds['r'].values.squeeze()
            print(f"提取{humidity_level}hPa相对湿度数据")
        elif humidity_type == 'specific_humidity':
            if 't' in ds and 'r' in ds:
                temp_k = ds['t'].values.squeeze()
                rh = ds['r'].values.squeeze()
                humidity_data = calculate_specific_humidity(temp_k, rh, humidity_level)
                print(f"计算{humidity_level}hPa比湿数据")
            else:
                print(f"警告: 无法获取{humidity_level}hPa温度或相对湿度数据，使用相对湿度代替")
                humidity_data = ds['r'].values.squeeze()
        else:
            humidity_data = ds['r'].values.squeeze()
            print(f"默认使用{humidity_level}hPa相对湿度数据")
    
    return humidity_data

def get_humidity_type_label(humidity_type, humidity_level):
    """
    返回湿度类型的显示标签
    """
    level_str = '2m' if humidity_level == '2m' else f'{humidity_level}hPa'
    
    labels = {
        'relative_humidity': f'{level_str} Relative Humidity',
        'specific_humidity': f'{level_str} Specific Humidity'
    }
    
    return labels.get(humidity_type, f'{level_str} Relative Humidity')

def draw_multi_level_composite_humidity(date_str='2024012400', 
                                       output_image_path='Output/MeteoMap/multi_level_composite_humidity.png',
                                       hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                                       data_source='ERA5', smooth_sigma=1, download_data=True,
                                       use_china_boundaries=True,
                                       # 湿度层设置
                                       show_humidity=True,
                                       humidity_level=500,  # 湿度层面，'2m'表示2米湿度
                                       humidity_type='relative_humidity',  # 湿度类型: 'relative_humidity', 'specific_humidity'
                                       # 位势高度层设置
                                       show_height=True, 
                                       height_level=500,
                                       height_contour_interval=None,  # None表示自动
                                       # 风场层设置
                                       show_wind=True,
                                       wind_level=500,
                                       wind_density=20):  # 风矢量密度
    """
    绘制多层复合图：湿度填充 + 位势高度等值线 + 风场矢量
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    humidity_level : int or str - 湿度层面 (hPa) 或 '2m' 表示2米湿度
    humidity_type : str - 湿度类型 ('relative_humidity', 'specific_humidity')
    height_level : int - 位势高度层面 (hPa)
    wind_level : int - 风场层面 (hPa)
    show_humidity : bool - 是否显示湿度填充
    show_height : bool - 是否显示位势高度等值线
    show_wind : bool - 是否显示风场矢量
    wind_density : int - 风矢量密度 (数值越大越密集)
    height_contour_interval : int or None - 位势高度等值线间距，None表示自动
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据...")
        
        # 收集需要下载的气压层和变量
        pressure_levels_needed = set()
        surface_vars_needed = []
        
        if show_humidity and humidity_level != '2m':
            pressure_levels_needed.add(humidity_level)
        elif show_humidity and humidity_level == '2m':
            humidity_vars = get_humidity_variables_for_type(humidity_type, humidity_level)
            surface_vars_needed.extend(humidity_vars)
            
        if show_height:
            pressure_levels_needed.add(height_level)
            
        if show_wind:
            pressure_levels_needed.add(wind_level)
        
        # 下载气压层数据
        datasets = {}
        for level in pressure_levels_needed:
            print(f"正在下载 {level}hPa 数据...")
            variables = []
            
            # 收集该层需要的变量
            if show_humidity and humidity_level == level:
                humidity_vars = get_humidity_variables_for_type(humidity_type, humidity_level)
                variables.extend(humidity_vars)
            if show_height and height_level == level:
                variables.append('geopotential')
            if show_wind and wind_level == level:
                variables.extend(['u_component_of_wind', 'v_component_of_wind'])
            
            # 去重
            variables = list(set(variables))
            
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
        
        # 下载地面数据（如果需要）
        surface_ds = None
        if surface_vars_needed:
            print("正在下载地面数据...")
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
        
        # 提取数据
        # 获取坐标（从第一个可用数据集）
        coord_ds = surface_ds if surface_ds is not None else list(datasets.values())[0]
        lon = coord_ds.coords['longitude'].values
        lat = coord_ds.coords['latitude'].values
        
        # 提取湿度数据
        humidity_data = None
        if show_humidity:
            humidity_data = process_humidity_by_type(datasets, surface_ds, humidity_type, humidity_level)
        
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
    humidity_stats = ""
    height_stats = ""
    wind_stats = ""
    
    if show_humidity and humidity_data is not None:
        min_humidity = np.min(humidity_data)
        max_humidity = np.max(humidity_data)
        humidity_label_short = get_humidity_type_label(humidity_type, humidity_level)
        if humidity_type == 'relative_humidity':
            humidity_stats = f"{humidity_label_short}: {min_humidity:.1f}-{max_humidity:.1f}%"
        else:
            humidity_stats = f"{humidity_label_short}: {min_humidity:.1f}-{max_humidity:.1f}g/kg"
    
    if show_height and height_data is not None:
        height_data_smooth = gaussian_filter(height_data, sigma=smooth_sigma)
        min_height = np.min(height_data_smooth)
        max_height = np.max(height_data_smooth)
        height_stats = f"Height: {min_height:.0f}-{max_height:.0f}gpm"
    
    if show_wind and u_wind is not None and v_wind is not None:
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        max_wind = np.max(wind_speed)
        wind_stats = f"Wind: max {max_wind:.1f}m/s"
    
    print(f"数据统计: {humidity_stats} {height_stats} {wind_stats}")
    
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
    
    # 绘制湿度填充（底层）
    contourf = None
    if show_humidity and humidity_data is not None:
        if humidity_type == 'relative_humidity':
            humidity_colors, humidity_points, min_humidity_display, max_humidity_display = get_humidity_color_scheme()
        else:
            humidity_colors, humidity_points, min_humidity_display, max_humidity_display = get_specific_humidity_color_scheme()
        
        # 创建湿度配色映射
        color_positions = []
        valid_colors = []
        
        for i, humidity in enumerate(humidity_points):
            if i < len(humidity_colors):
                pos = (humidity - min_humidity_display) / (max_humidity_display - min_humidity_display)
                pos = max(0, min(1, pos))
                color_positions.append(pos)
                valid_colors.append(humidity_colors[i])
        
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
            'humidity_cmap', 
            list(zip(unique_positions, unique_colors)),
            N=256
        )
        
        # 绘制湿度填充等高线
        from matplotlib.colors import Normalize
        norm = Normalize(vmin=min_humidity_display, vmax=max_humidity_display)
        
        humidity_levels_plot = np.linspace(min_humidity_display, max_humidity_display, 100)
        
        contourf = ax.contourf(
            lon_grid, lat_grid, humidity_data,
            levels=humidity_levels_plot, 
            cmap=cmap, 
            norm=norm,
            transform=ccrs.PlateCarree(), 
            alpha=0.8, 
            extend='both'
        )
        
        humidity_type_label = get_humidity_type_label(humidity_type, humidity_level)
        print(f"绘制湿度填充: {humidity_type_label}")
    
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

    # 创建色彩条（如果显示湿度）
    if show_humidity and contourf is not None:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
        
        # 设置色彩条刻度
        if humidity_type == 'relative_humidity':
            tick_interval = 10
            tick_start = int(min_humidity_display // tick_interval) * tick_interval
            tick_end   = int(max_humidity_display // tick_interval) * tick_interval
            colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
            unit = '%'
        else:
            tick_interval = 2
            tick_start = int(min_humidity_display // tick_interval) * tick_interval
            tick_end   = int(max_humidity_display // tick_interval) * tick_interval
            colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
            unit = 'g/kg'
        
        humidity_label = get_humidity_type_label(humidity_type, humidity_level)
        cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                           ticks=colorbar_ticks, label=f'{humidity_label} ({unit})')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 构建标题
    title_parts = []
    if show_humidity:
        humidity_abbr = {
            'relative_humidity': 'RH',
            'specific_humidity': 'Q'
        }
        level_str = '2m' if humidity_level == '2m' else f'{humidity_level}hPa'
        humidity_part = f'{level_str} {humidity_abbr.get(humidity_type, "RH")}'
        title_parts.append(humidity_part)
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
    if humidity_stats:
        stats_lines.append(humidity_stats)
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
    
    date_str = '2024012400'
    humidity_level = 850  # 湿度层面
    height_level = 500  # 位势高度层面
    wind_level = 850  # 风场层面
    humidity_type = 'relative_humidity'  # 湿度类型: 'relative_humidity', 'specific_humidity'
    
    # 修复文件名中的缩写
    humidity_abbr_filename = {
        'relative_humidity': 'RH',
        'specific_humidity': 'Q'
    }
    
    draw_multi_level_composite_humidity(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_{height_level}GPH_{humidity_level}{humidity_abbr_filename.get(humidity_type, "RH")}_{wind_level}Wind_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        show_humidity=True,
        humidity_level=humidity_level,
        humidity_type=humidity_type,  # 湿度类型参数
        show_height=True,
        height_level=height_level,
        height_contour_interval=None,
        show_wind=True,
        wind_level=wind_level,
        wind_density=20
    )