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

def get_temperature_color_scheme():
    """
    返回温度配色方案
    """
    colors = [
        "#B3B0B0",  # 灰色 (-60)
        "#7EE1E1",  # 青绿色 (-50)
        "#8EB2EB",  # 青色 (-40)
        "#C881E6",  # 深紫色 (-30)
        "#87A3FC",  # 深蓝色 (-20)
        '#87CEEB',  # 天蓝 (-10)
        '#FFFFFF',  # 白色 (0)
        "#52FF52",  # 淡绿 (10)
        '#FFFF00',  # 黄色 (20)
        '#FF0000',  # 红色 (30)
        '#C71585',  # 中紫罗兰红 (35)
        '#8A2BE2',  # 蓝紫色 (40)
        '#E6E6FA',  # 淡紫色/泛白 (45)
        '#FFFFFF',  # 纯白 (50)
    ]
    temp_points = [-60, -50, -40, -30, -20, -10, 0, 10, 20, 30, 35, 40, 45, 50]
    min_temp, max_temp = -60, 50
    
    return colors, temp_points, min_temp, max_temp

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

def calculate_potential_temperature(temp_k, pressure_hpa):
    """
    计算位温
    
    参数:
    temp_k : np.array - 温度(开尔文)
    pressure_hpa : float - 气压(hPa)
    
    返回:
    np.array - 位温(开尔文)
    """
    # 位温公式: θ = T * (1000/P)^(R/cp)
    # R/cp = 0.286 (干空气)
    potential_temp = temp_k * (1000.0 / pressure_hpa) ** 0.286
    return potential_temp

def calculate_dewpoint_from_pressure_level(temp_k, rh_percent):
    """
    从气压层温度和相对湿度计算露点温度
    
    参数:
    temp_k : np.array - 温度(开尔文)
    rh_percent : np.array - 相对湿度(%)
    
    返回:
    np.array - 露点温度(开尔文)
    """
    # Magnus公式计算露点
    temp_c = temp_k - 273.15
    a = 17.27
    b = 237.7
    
    # 饱和水汽压
    es = 6.112 * np.exp((a * temp_c) / (b + temp_c))
    
    # 实际水汽压
    e = rh_percent / 100.0 * es
    
    # 露点温度
    dewpoint_c = (b * np.log(e / 6.112)) / (a - np.log(e / 6.112))
    
    return dewpoint_c + 273.15

def get_temperature_variables_for_type(temp_type, temp_level):
    """
    根据温度类型返回需要下载的变量
    
    参数:
    temp_type : str - 温度类型 ('temperature', 'potential_temperature', 'dewpoint')
    temp_level : int or str - 温度层面
    
    返回:
    list - 需要下载的变量列表
    """
    if temp_level == '2m':
        # 地面数据
        if temp_type == 'temperature':
            return ['2m_temperature']
        elif temp_type == 'dewpoint':
            return ['2m_dewpoint_temperature']
        elif temp_type == 'potential_temperature':
            return ['2m_temperature']  # 需要温度和气压计算位温
        else:
            return ['2m_temperature']
    else:
        # 气压层数据
        if temp_type == 'temperature':
            return ['temperature']
        elif temp_type == 'potential_temperature':
            return ['temperature']  # 位温从温度和气压计算
        elif temp_type == 'dewpoint':
            return ['temperature', 'relative_humidity']  # 露点从温度和湿度计算
        else:
            return ['temperature']

def process_temperature_by_type(datasets, surface_ds, temp_type, temp_level):
    """
    根据温度类型处理温度数据
    
    参数:
    datasets : dict - 气压层数据集
    surface_ds : xr.Dataset - 地面数据集
    temp_type : str - 温度类型
    temp_level : int or str - 温度层面
    
    返回:
    np.array - 处理后的温度数据(摄氏度)
    """
    if temp_level == '2m':
        # 地面数据处理
        if temp_type == 'temperature':
            temp_data = surface_ds['t2m'].values.squeeze() - 273.15
            print(f"提取2m温度数据")
        elif temp_type == 'dewpoint':
            temp_data = surface_ds['d2m'].values.squeeze() - 273.15
            print(f"提取2m露点温度数据")
        elif temp_type == 'potential_temperature':
            temp_k = surface_ds['t2m'].values.squeeze()
            # 地面位温近似使用1000hPa
            potential_temp_k = calculate_potential_temperature(temp_k, 1000.0)
            temp_data = potential_temp_k - 273.15
            print(f"计算2m位温数据")
        else:
            temp_data = surface_ds['t2m'].values.squeeze() - 273.15
            print(f"默认使用2m温度数据")
    else:
        # 气压层数据处理
        ds = datasets[temp_level]
        
        if temp_type == 'temperature':
            temp_data = ds['t'].values.squeeze() - 273.15
            print(f"提取{temp_level}hPa温度数据")
        elif temp_type == 'potential_temperature':
            temp_k = ds['t'].values.squeeze()
            potential_temp_k = calculate_potential_temperature(temp_k, temp_level)
            temp_data = potential_temp_k - 273.15
            print(f"计算{temp_level}hPa位温数据")
        elif temp_type == 'dewpoint':
            if 'r' in ds:
                temp_k = ds['t'].values.squeeze()
                rh = ds['r'].values.squeeze()
                dewpoint_k = calculate_dewpoint_from_pressure_level(temp_k, rh)
                temp_data = dewpoint_k - 273.15
                print(f"计算{temp_level}hPa露点温度数据")
            else:
                print(f"警告: 无法获取{temp_level}hPa相对湿度数据，使用温度代替")
                temp_data = ds['t'].values.squeeze() - 273.15
        else:
            temp_data = ds['t'].values.squeeze() - 273.15
            print(f"默认使用{temp_level}hPa温度数据")
    
    return temp_data

def get_temperature_type_label(temp_type, temp_level):
    """
    返回温度类型的显示标签
    """
    level_str = '2m' if temp_level == '2m' else f'{temp_level}hPa'
    
    labels = {
        'temperature': f'{level_str} Temperature',
        'potential_temperature': f'{level_str} Potential Temperature',
        'dewpoint': f'{level_str} Dewpoint Temperature'
    }
    
    return labels.get(temp_type, f'{level_str} Temperature')

def draw_multi_level_composite(date_str='2024012400', 
                              output_image_path='Output/MeteoMap/multi_level_composite.png',
                              hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                              data_source='ERA5', smooth_sigma=1, download_data=True,
                              use_china_boundaries=True,
                              # 温度层设置
                              show_temperature=True,
                              temp_level=500,  # 温度层面，'2m'表示2米温度
                              temp_type='temperature',  # 温度类型: 'temperature', 'potential_temperature', 'dewpoint'
                              # 位势高度层设置
                              show_height=True, 
                              height_level=500,
                              height_contour_interval=None,  # None表示自动
                              # 风场层设置
                              show_wind=True,
                              wind_level=500,
                              wind_density=20,  # 风矢量密度
                              # 地面场模式参数
                              use_surface_mode=False,  # True时使用地面MSLP和10m风替代高空数据
                              surface_temp_type='2mT'):  # 地面温度类型: '2mT'=2m温度, 'dew'=露点
    """
    绘制多层复合图：温度填充 + 位势高度等值线 + 风场矢量
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    temp_level : int or str - 温度层面 (hPa) 或 '2m' 表示2米温度
    temp_type : str - 温度类型 ('temperature', 'potential_temperature', 'dewpoint')
    height_level : int - 位势高度层面 (hPa)
    wind_level : int - 风场层面 (hPa)
    show_temperature : bool - 是否显示温度填充
    show_height : bool - 是否显示位势高度等值线
    show_wind : bool - 是否显示风场矢量
    wind_density : int - 风矢量密度 (数值越大越密集)
    height_contour_interval : int or None - 位势高度等值线间距，None表示自动
    use_china_boundaries : bool - True显示中国边界，False仅显示海陆和河流
    use_surface_mode : bool - True时使用地面MSLP和10m风替代高空数据
    surface_temp_type : str - 地面温度类型 ('2mT'=2m温度, 'dew'=露点)
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据...")
        
        if use_surface_mode:
            print("使用地面场模式：MSLP + 地面温度 + 10m风")
            # 地面模式：只需要地面数据
            surface_vars_needed = ['mean_sea_level_pressure']
            
            if show_temperature:
                if surface_temp_type == '2mT':
                    surface_vars_needed.append('2m_temperature')
                elif surface_temp_type == 'dew':
                    surface_vars_needed.append('2m_dewpoint_temperature')
            
            if show_wind:
                surface_vars_needed.extend(['10m_u_component_of_wind', '10m_v_component_of_wind'])
            
            # 只下载地面数据
            print(f"正在下载地面数据: {surface_vars_needed}...")
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
            
            # 在地面模式下，直接处理地面数据
            lon = surface_ds.coords['longitude'].values
            lat = surface_ds.coords['latitude'].values
            
            # 提取温度数据
            temp_data = None
            if show_temperature:
                if surface_temp_type == '2mT':
                    temp_data = surface_ds['t2m'].values.squeeze() - 273.15
                    print("提取2m温度数据")
                elif surface_temp_type == 'dew':
                    temp_data = surface_ds['d2m'].values.squeeze() - 273.15
                    print("提取2m露点温度数据")
            
            # 提取MSLP数据（替代位势高度）
            height_data = None
            if show_height:
                mslp = surface_ds['msl'].values.squeeze() / 100  # 转换为hPa
                height_data = mslp  # 用MSLP替代位势高度
                print("提取海平面气压数据（作为高度场显示）")
            
            # 提取10m风场
            u_wind, v_wind = None, None
            if show_wind:
                u_wind = surface_ds['u10'].values.squeeze()
                v_wind = surface_ds['v10'].values.squeeze()
                print("提取10m风场数据")
            
            datasets = {}
            height_level = None  # 地面模式无层级
            wind_level = '10m'  # 标记为10m风
            
        else:
            # 原始高空模式
            # 收集需要下载的气压层和变量
            pressure_levels_needed = set()
            surface_vars_needed = []
            
            if show_temperature and temp_level != '2m':
                pressure_levels_needed.add(temp_level)
            elif show_temperature and temp_level == '2m':
                temp_vars = get_temperature_variables_for_type(temp_type, temp_level)
                surface_vars_needed.extend(temp_vars)
                
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
                if show_temperature and temp_level == level:
                    temp_vars = get_temperature_variables_for_type(temp_type, temp_level)
                    variables.extend(temp_vars)
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
            
            # 提取温度数据
            temp_data = None
            if show_temperature:
                temp_data = process_temperature_by_type(datasets, surface_ds, temp_type, temp_level)
            
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
    temp_stats = ""
    height_stats = ""
    wind_stats = ""
    
    if show_temperature and temp_data is not None:
        min_temp = np.min(temp_data)
        max_temp = np.max(temp_data)
        if use_surface_mode:
            temp_label_short = "2m T" if surface_temp_type == '2mT' else "2m Dew"
        else:
            temp_label_short = get_temperature_type_label(temp_type, temp_level)
        temp_stats = f"{temp_label_short}: {min_temp:.1f}-{max_temp:.1f}°C"
    
    if show_height and height_data is not None:
        height_data_smooth = gaussian_filter(height_data, sigma=smooth_sigma)
        min_height = np.min(height_data_smooth)
        max_height = np.max(height_data_smooth)
        if use_surface_mode:
            height_stats = f"MSLP: {min_height:.1f}-{max_height:.1f}hPa"
        else:
            height_stats = f"Height: {min_height:.0f}-{max_height:.0f}gpm"
    
    if show_wind and u_wind is not None and v_wind is not None:
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        max_wind = np.max(wind_speed)
        wind_label = "10m Wind" if use_surface_mode else f"{wind_level}hPa Wind"
        wind_stats = f"{wind_label}: max {max_wind:.1f}m/s"
    
    print(f"数据统计: {temp_stats} {height_stats} {wind_stats}")
    
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
    
    # 绘制温度填充（底层）
    contourf = None
    if show_temperature and temp_data is not None:
        temp_colors, temp_points, min_temp_display, max_temp_display = get_temperature_color_scheme()
        
        # 创建温度配色映射
        color_positions = []
        valid_colors = []
        
        for i, temp in enumerate(temp_points):
            if i < len(temp_colors):
                pos = (temp - min_temp_display) / (max_temp_display - min_temp_display)
                pos = max(0, min(1, pos))
                color_positions.append(pos)
                valid_colors.append(temp_colors[i])
        
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
            'temperature_cmap', 
            list(zip(unique_positions, unique_colors)),
            N=256
        )
        
        # 绘制温度填充等高线
        from matplotlib.colors import Normalize
        norm = Normalize(vmin=min_temp_display, vmax=max_temp_display)
        
        temp_levels_plot = np.linspace(min_temp_display, max_temp_display, 100)
        
        contourf = ax.contourf(
            lon_grid, lat_grid, temp_data,
            levels=temp_levels_plot, 
            cmap=cmap, 
            norm=norm,
            transform=ccrs.PlateCarree(), 
            alpha=0.8, 
            extend='both'
        )
        
        if use_surface_mode:
            print(f"绘制地面温度填充: {surface_temp_type}")
        else:
            temp_type_label = get_temperature_type_label(temp_type, temp_level)
            print(f"绘制温度填充: {temp_type_label}")
    
    # 绘制MSLP或位势高度等值线（中层）
    if show_height and height_data is not None:
        height_data_smooth = gaussian_filter(height_data, sigma=smooth_sigma)
        
        if use_surface_mode:
            # 地面模式：MSLP等值线，间距20hPa
            min_height = np.min(height_data_smooth)
            max_height = np.max(height_data_smooth)
            interval = 10  # MSLP间距固定为10hPa
            
            height_min_round = int(min_height // interval) * interval
            height_max_round = int(max_height // interval + 1) * interval
            height_levels = np.arange(height_min_round, height_max_round + interval, interval)
            
            print(f"绘制海平面气压等值线: 间距 {interval}hPa")
        else:
            # 高空模式：位势高度等值线
            # 确定等高线间距
            if height_contour_interval is None:
                interval = get_height_contour_interval(height_level)
            else:
                interval = height_contour_interval
            
            # 计算等高线级别
            min_height = np.min(height_data_smooth)
            max_height = np.max(height_data_smooth)
            height_min_round = int(min_height // interval) * interval
            height_max_round = int(max_height // interval + 1) * interval
            height_levels = np.arange(height_min_round, height_max_round + interval, interval)
            
            print(f"绘制位势高度等值线: {height_level}hPa, 间距: {interval}gpm")
        
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
        
        if use_surface_mode:
            print(f"绘制10m风场矢量: 密度: 每{skip_factor}个网格点")
        else:
            print(f"绘制风场矢量: {wind_level}hPa, 密度: 每{skip_factor}个网格点")
    
    # 添加海岸线和边界
    try:
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        
        if use_china_boundaries:
            # True: 显示中国边界
            china_boundaries_added = add_china_boundaries(
                ax, 
                lon_min=lon.min(), 
                lon_max=lon.max(),
                lat_min=lat.min(), 
                lat_max=lat.max()
            )
            
            if not china_boundaries_added:
                print("未能添加中国边界，仅显示海陆和河流")
        else:
            # False: 仅显示海陆和河流，不显示任何边界
            print("仅显示海陆和河流边界")
        
    except Exception as e:
        print(f"添加边界时出错: {e}")
        ax.coastlines(resolution='50m')
    
    # 添加网格线
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.7)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(lon.min()), 
                                           np.ceil(lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(lat.min()), 
                                           np.ceil(lat.max()) + 1, 5))

    # 创建色彩条（如果显示温度）
    if show_temperature and contourf is not None:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
        
        # 设置色彩条刻度
        tick_interval = 5
        tick_start = int(min_temp_display // tick_interval) * tick_interval
        tick_end   = int(max_temp_display // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
        
        # 确保0度包含在刻度中
        if 0 not in colorbar_ticks and min_temp_display <= 0 <= max_temp_display:
            colorbar_ticks.append(0)
            colorbar_ticks.sort()
        
        if use_surface_mode:
            temp_label = "2m Temperature" if surface_temp_type == '2mT' else "2m Dewpoint"
        else:
            temp_label = get_temperature_type_label(temp_type, temp_level)
        cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                           ticks=colorbar_ticks, label=f'{temp_label} (°C)')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 构建标题
    title_parts = []
    if show_temperature:
        if use_surface_mode:
            temp_abbr = 'T' if surface_temp_type == '2mT' else 'Td'
            temp_part = f'2m {temp_abbr}'
        else:
            temp_abbr = {
                'temperature': 'T',
                'potential_temperature': 'θ',
                'dewpoint': 'Td'
            }
            level_str = '2m' if temp_level == '2m' else f'{temp_level}hPa'
            temp_part = f'{level_str} {temp_abbr.get(temp_type, "T")}'
        title_parts.append(temp_part)
    
    if show_height:
        if use_surface_mode:
            title_parts.append('MSLP')
        else:
            title_parts.append(f'{height_level}hPa GPH')
    
    if show_wind:
        if use_surface_mode:
            title_parts.append('10m Wind')
        else:
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
    if temp_stats:
        stats_lines.append(temp_stats)
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
    
    date_str = '2022112800'
    
    # ===== 高空模式 =====
    gph_level = 500
    t_level = 1000
    wind_level = 1000
    temp_type = 'temperature'  # 选择: 'temperature', 'potential_temperature', 'dewpoint'
    draw_multi_level_composite(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_{gph_level}hPaGPH_{t_level}hPa{temp_type}_{wind_level}hPaWind_{date_str}.png', 
        hour=0,
        lon_min=40,
        lon_max=140,
        lat_min=20,
        lat_max=70,
        download_data=True,
        use_china_boundaries=False,
        show_temperature=True,
        temp_level=t_level,
        temp_type=temp_type, # 选择: 'temperature', 'potential_temperature', 'dewpoint'
        show_height=True,
        height_level=gph_level,
        height_contour_interval=50,
        show_wind=True,
        wind_level=wind_level,
        wind_density=20,
        use_surface_mode=False  # 高空模式
    )
    
    # ===== 地面模式 =====
    t_level = '2mT'
    draw_multi_level_composite(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_Surface_MSLP_{t_level}_10mWind_{date_str}.png', 
        hour=0,
        lon_min=40,
        lon_max=140,
        lat_min=20,
        lat_max=70,
        download_data=True,
        use_china_boundaries=False,
        show_temperature=True,
        show_height=True,
        show_wind=True,
        wind_density=20,
        use_surface_mode=True,  # 地面模式
        surface_temp_type=t_level  # 选择: '2mT' 或 'dew'
    )
