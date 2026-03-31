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

def get_water_transport_color_scheme():
    """
    返回水汽输送配色方案（kg/m/s）
    """
    colors = [
        "#8B4513",  # 深褐色 (0) - 无输送
        "#D2B48C",  # 棕褐色 (50)
        "#F5DEB3",  # 小麦色 (100)
        "#F0E68C",  # 卡其色 (150)
        "#FFFACD",  # 柠檬薄纱 (200)
        "#E0FFFF",  # 淡青色 (300)
        "#B4F6FF",  # 粉蓝色 (400)
        "#9BE3FF",  # 天蓝色 (500)
        "#74B9FF",  # 道奇蓝 (600)
        "#0084FF",  # 蓝色 (700)
        "#0066CC",  # 深蓝色 (800) - 强输送
    ]
    transport_points = [0, 50, 100, 150, 200, 300, 400, 500, 600, 700, 800]
    min_transport, max_transport = 0, 800
    
    return colors, transport_points, min_transport, max_transport

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
    np.array - 比湿(kg/kg)
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
    specific_humidity = 0.622 * e / (pressure_hpa - 0.378 * e)
    
    return specific_humidity

def calculate_water_transport(u_wind, v_wind, specific_humidity, pressure_level):
    """
    计算水汽输送通量
    
    参数:
    u_wind : np.array - 纬向风速 (m/s)
    v_wind : np.array - 经向风速 (m/s)
    specific_humidity : np.array - 比湿 (kg/kg)
    pressure_level : float - 气压层面 (hPa)
    
    返回:
    tuple - (qu, qv, transport_magnitude) 水汽输送分量和大小 (kg/m/s)
    """
    # 水汽输送通量 = 风速 × 比湿 × 压力层厚度因子
    # 简化计算，使用压力层面代表的大气柱厚度
    # 对于单层，使用标准大气的近似厚度
    
    # 计算气压层的近似厚度 (m)
    # 使用静力学方程的近似: Δz ≈ -RT/g * ln(p2/p1)
    # 对于单个气压层，使用标准厚度
    if pressure_level >= 850:
        layer_thickness = 1500  # m，边界层
    elif pressure_level >= 700:
        layer_thickness = 1800  # m
    elif pressure_level >= 500:
        layer_thickness = 2000  # m
    elif pressure_level >= 300:
        layer_thickness = 2500  # m
    else:
        layer_thickness = 3000  # m，高层
    
    # 计算水汽输送通量 (kg/m/s)
    # qu = u * q * ρ * Δz，其中 ρ ≈ P/(R*T)，简化为使用层厚度
    qu = u_wind * specific_humidity * layer_thickness
    qv = v_wind * specific_humidity * layer_thickness

    # 水汽输送大小
    transport_magnitude = np.sqrt(qu**2 + qv**2)
    return qu, qv, transport_magnitude

def calculate_total_water_transport(datasets, surface_ds, transport_levels):
    """
    计算总水汽输送（积分多个气压层）
    
    参数:
    datasets : dict - 各层数据集
    surface_ds : xr.Dataset - 地面数据
    transport_levels : list - 参与积分的气压层面
    
    返回:
    tuple - (total_qu, total_qv, total_transport) 总水汽输送
    """
    total_qu = None
    total_qv = None
    
    for level in sorted(transport_levels, reverse=True):  # 从高压到低压
        if level in datasets:
            ds = datasets[level]
            
            # 获取风场和湿度数据
            u_wind = ds['u'].values.squeeze()
            v_wind = ds['v'].values.squeeze()
            
            # 计算比湿
            if 't' in ds and 'r' in ds:
                temp_k = ds['t'].values.squeeze()
                rh = ds['r'].values.squeeze()
                specific_humidity = calculate_specific_humidity(temp_k, rh, level)
            else:
                print(f"警告: {level}hPa层缺少温度或湿度数据，跳过")
                continue
            
            # 计算该层的水汽输送
            qu, qv, _ = calculate_water_transport(u_wind, v_wind, specific_humidity, level)
            
            # 累加到总输送
            if total_qu is None:
                total_qu = qu.copy()
                total_qv = qv.copy()
            else:
                total_qu += qu
                total_qv += qv
    
    # 计算总输送大小
    total_transport = np.sqrt(total_qu**2 + total_qv**2) if total_qu is not None else None
    
    return total_qu, total_qv, total_transport

def download_era5_pressure_data_batch(date, pressure_levels, variables_dict, lon_min, lon_max, lat_min, lat_max):
    """
    批量下载多个气压层的ERA5数据
    
    参数:
    pressure_levels : list - 需要下载的气压层面列表
    variables_dict : dict - {level: [variables]} 每个层面需要的变量
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        return {}
        
    # 解析日期
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    
    # 初始化CDS API客户端
    c = cdsapi.Client()
    
    datasets = {}
    
    for level in pressure_levels:
        if level not in variables_dict or not variables_dict[level]:
            continue
            
        print(f"正在下载 {level}hPa 数据...")
        
        try:
            # 创建临时文件名
            temp_dir = tempfile.gettempdir()
            temp_filename = f"era5_pressure_temp_{os.getpid()}_{date}_{level}.nc"
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
                    'variable': variables_dict[level],
                    'pressure_level': str(level),
                    'year': year,
                    'month': month,
                    'day': day,
                    'time': f'{hour}:00',
                    'area': [lat_max, lon_min, lat_min, lon_max],
                },
                output_file)
            
            # 将数据加载到内存
            with xr.open_dataset(output_file) as ds:
                datasets[level] = ds.load()
            
            # 删除临时文件
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

def draw_multi_level_composite_water_transport(date_str='2024012400', 
                                             output_image_path='Output/MeteoMap/multi_level_composite_water_transport.png',
                                             hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                                             data_source='ERA5', smooth_sigma=1, download_data=True,
                                             use_china_boundaries=True,
                                             # 水汽输送设置
                                             show_water_transport=True,
                                             water_level='total',  # 'total' 或具体气压层面数字 (如 850)
                                             transport_levels=[1000, 925, 850, 700, 600, 500],
                                             # 位势高度层设置
                                             show_height=True, 
                                             height_level=500,
                                             height_contour_interval=None,
                                             # 风场层设置
                                             show_wind=True,
                                             wind_level=500,
                                             wind_density=20):
    """
    绘制多层复合图：水汽输送填充 + 位势高度等值线 + 风场矢量
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    water_level : str or int - 水汽输送层面 ('total' 表示总输送, 或具体气压层面如 850)
    transport_levels : list - 总水汽输送时的积分层面列表 (hPa)
    show_water_transport : bool - 是否显示水汽输送填充
    height_level : int - 位势高度层面 (hPa)
    wind_level : int - 风场层面 (hPa)
    show_height : bool - 是否显示位势高度等值线
    show_wind : bool - 是否显示风场矢量
    wind_density : int - 风矢量密度 (数值越大越密集)
    height_contour_interval : int or None - 位势高度等值线间距，None表示自动
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    # 确定水汽输送类型
    if str(water_level).lower() == 'total':
        transport_type = 'total'
        transport_level = None
    else:
        transport_type = 'level'
        try:
            transport_level = int(water_level)
        except ValueError:
            print(f"错误: water_level 必须是 'total' 或数字，得到: {water_level}")
            return

    if download_data:
        print(f"正在下载 {date_str} 的ERA5数据...")
        
        # 收集需要下载的气压层和变量
        pressure_levels_needed = set()
        variables_dict = {}
        
        if show_water_transport:
            if transport_type == 'level':
                pressure_levels_needed.add(transport_level)
                variables_dict[transport_level] = ['u_component_of_wind', 'v_component_of_wind', 
                                                 'temperature', 'relative_humidity']
            elif transport_type == 'total':
                pressure_levels_needed.update(transport_levels)
                for level in transport_levels:
                    variables_dict[level] = ['u_component_of_wind', 'v_component_of_wind', 
                                           'temperature', 'relative_humidity']
                
        if show_height:
            pressure_levels_needed.add(height_level)
            if height_level not in variables_dict:
                variables_dict[height_level] = []
            variables_dict[height_level].append('geopotential')
            
        if show_wind:
            pressure_levels_needed.add(wind_level)
            if wind_level not in variables_dict:
                variables_dict[wind_level] = []
            variables_dict[wind_level].extend(['u_component_of_wind', 'v_component_of_wind'])
        
        # 去重变量
        for level in variables_dict:
            variables_dict[level] = list(set(variables_dict[level]))
        
        # 批量下载数据
        datasets = download_era5_pressure_data_batch(
            date=date_str,
            pressure_levels=list(pressure_levels_needed),
            variables_dict=variables_dict,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if not datasets:
            print("数据下载失败，退出...")
            return
        
        # 提取数据
        coord_ds = list(datasets.values())[0]
        lon = coord_ds.coords['longitude'].values
        lat = coord_ds.coords['latitude'].values
        
        # 提取水汽输送数据
        transport_data = None
        transport_qu, transport_qv = None, None
        if show_water_transport:
            if transport_type == 'level':
                ds = datasets[transport_level]
                u_wind = ds['u'].values.squeeze()
                v_wind = ds['v'].values.squeeze()
                temp_k = ds['t'].values.squeeze()
                rh = ds['r'].values.squeeze()
                
                specific_humidity = calculate_specific_humidity(temp_k, rh, transport_level)
                transport_qu, transport_qv, transport_data = calculate_water_transport(
                    u_wind, v_wind, specific_humidity, transport_level)
                
            elif transport_type == 'total':
                transport_qu, transport_qv, transport_data = calculate_total_water_transport(
                    datasets, None, transport_levels)
        
        # 提取位势高度数据
        height_data = None
        if show_height:
            geopotential = datasets[height_level]['z'].values.squeeze()
            height_data = geopotential / 9.80665
        
        # 提取风场数据
        u_wind, v_wind = None, None
        if show_wind:
            u_wind = datasets[wind_level]['u'].values.squeeze()
            v_wind = datasets[wind_level]['v'].values.squeeze()
        
    else:
        print("错误: 暂不支持从文件加载多层复合数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 计算统计信息
    transport_stats = ""
    height_stats = ""
    wind_stats = ""
    
    if show_water_transport and transport_data is not None:
        min_transport = np.min(transport_data)
        max_transport = np.max(transport_data)
        if transport_type == 'level':
            transport_stats = f"{transport_level}hPa Water Transport: {min_transport:.0f}-{max_transport:.0f}kg/m/s"
        else:
            transport_stats = f"Total Water Transport: {min_transport:.0f}-{max_transport:.0f}kg/m/s"
    
    if show_height and height_data is not None:
        height_data_smooth = gaussian_filter(height_data, sigma=smooth_sigma)
        min_height = np.min(height_data_smooth)
        max_height = np.max(height_data_smooth)
        height_stats = f"Height: {min_height:.0f}-{max_height:.0f}gpm"
    
    if show_wind and u_wind is not None and v_wind is not None:
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        max_wind = np.max(wind_speed)
        wind_stats = f"Wind: max {max_wind:.1f}m/s"
    
    print(f"数据统计: {transport_stats} {height_stats} {wind_stats}")
    
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
    
    # 绘制水汽输送填充
    contourf = None
    if show_water_transport and transport_data is not None:
        transport_colors, transport_points, min_transport_display, max_transport_display = get_water_transport_color_scheme()
        
        color_positions = []
        valid_colors = []
        for i, transport in enumerate(transport_points):
            if i < len(transport_colors):
                pos = (transport - min_transport_display) / (max_transport_display - min_transport_display)
                pos = max(0, min(1, pos))
                color_positions.append(pos)
                valid_colors.append(transport_colors[i])
        
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
        
        unique_positions = []
        unique_colors = []
        for i, (pos, color) in enumerate(zip(color_positions, valid_colors)):
            if i == 0 or pos > color_positions[i-1]:
                unique_positions.append(pos)
                unique_colors.append(color)
        
        cmap = LinearSegmentedColormap.from_list('transport_cmap', 
                                               list(zip(unique_positions, unique_colors)), N=256)
        
        from matplotlib.colors import Normalize
        norm = Normalize(vmin=min_transport_display, vmax=max_transport_display)
        transport_levels_plot = np.linspace(min_transport_display, max_transport_display, 100)
        
        contourf = ax.contourf(lon_grid, lat_grid, transport_data, levels=transport_levels_plot, 
                              cmap=cmap, norm=norm, transform=ccrs.PlateCarree(), alpha=0.8, extend='both')
    
    # 绘制位势高度等值线
    if show_height and height_data is not None:
        if height_contour_interval is None:
            interval = get_height_contour_interval(height_level)
        else:
            interval = height_contour_interval
        
        height_min_round = int(min_height // interval) * interval
        height_max_round = int(max_height // interval + 1) * interval
        height_levels = np.arange(height_min_round, height_max_round + interval, interval)
        
        contour = ax.contour(lon_grid, lat_grid, height_data_smooth, levels=height_levels, 
                            colors='black', linewidths=1.5, alpha=1.0, transform=ccrs.PlateCarree())
        ax.clabel(contour, inline=True, fontsize=9, fmt='%d')
    
    # 绘制风场矢量
    if show_wind and u_wind is not None and v_wind is not None:
        skip_factor = max(1, min(u_wind.shape) // wind_density)
        barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
        ax.barbs(lon_grid[barb_slice], lat_grid[barb_slice], u_wind[barb_slice], v_wind[barb_slice],
                length=5, pivot='middle', color='darkblue', alpha=0.8, transform=ccrs.PlateCarree())
    
    # 绘制水汽输送矢量
    if show_water_transport and transport_qu is not None and transport_qv is not None:
        skip_factor_transport = max(1, min(transport_qu.shape) // 15)
        transport_slice = (slice(None, None, skip_factor_transport), slice(None, None, skip_factor_transport))
        scale_factor = 0.0001
        ax.quiver(lon_grid[transport_slice], lat_grid[transport_slice],
                 transport_qu[transport_slice] * scale_factor, transport_qv[transport_slice] * scale_factor,
                 color='red', alpha=0.7, scale=1, scale_units='xy', angles='xy',
                 transform=ccrs.PlateCarree(), width=0.003)
    
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
    if show_water_transport and contourf is not None:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
        tick_interval = 100
        tick_start = int(min_transport_display // tick_interval) * tick_interval
        tick_end   = int(max_transport_display // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
        cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                           ticks=colorbar_ticks, label='Water Transport (kg/m/s)')
    
    # 格式化标题
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    title_parts = []
    if show_water_transport:
        if transport_type == 'level':
            title_parts.append(f'{transport_level}hPa WT')
        else:
            title_parts.append('Total WT')
    if show_height:
        title_parts.append(f'{height_level}hPa GPH')
    if show_wind:
        title_parts.append(f'{wind_level}hPa Wind')
    
    main_title = f'{data_source} ' + ' + '.join(title_parts)
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    stats_lines = []
    if transport_stats:
        stats_lines.append(transport_stats)
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
    
    # 参数设置
    date_str = '2024072400'
    height_level = 500  # 位势高度层面
    wind_level = 850    # 风场层面
    water_level = 850   # 水汽输送层面: 'total' 或具体数字如 850
    
    # 绘制复合图
    draw_multi_level_composite_water_transport(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_{height_level}GPH_{water_level}WT_{wind_level}Wind_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        show_water_transport=True,
        water_level=water_level, 
        show_height=True,
        height_level=height_level,
        height_contour_interval=None,
        show_wind=True,
        wind_level=wind_level,
        wind_density=20
    )