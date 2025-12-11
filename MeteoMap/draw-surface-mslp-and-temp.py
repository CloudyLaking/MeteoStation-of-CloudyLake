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

def download_era5_surface_data(date, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5地面再分析数据
    
    参数:
    date : str - 日期时间字符串 (YYYYMMDDHH)
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

def download_era5_climatology_surface_data(variables, lon_min, lon_max, lat_min, lat_max, 
                                         start_year=1991, end_year=2020):
    """
    下载ERA5地面气候态数据（用于计算距平）
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None
        
    c = cdsapi.Client()
    
    try:
        temp_dir = tempfile.gettempdir()
        temp_filename = f"era5_surface_climatology_temp_{os.getpid()}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        # 下载地面气候态数据（1991-2020年平均）
        years = [str(year) for year in range(start_year, end_year + 1)]
        
        c.retrieve(
            'reanalysis-era5-single-levels-monthly-means',
            {
                'product_type': 'monthly_averaged_reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'year': years,
                'month': ['01', '02', '03', '04', '05', '06', 
                         '07', '08', '09', '10', '11', '12'],
                'time': '00:00',
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
        print(f"下载ERA5地面气候态数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def calculate_temperature_anomaly(current_temp, climatology_data, target_date):
    """
    计算温度距平
    
    参数:
    current_temp : np.array - 当前温度 (°C)
    climatology_data : xr.Dataset - 气候态数据
    target_date : str - 目标日期 (YYYYMMDDHH)
    
    返回:
    np.array - 温度距平 (°C)
    """
    try:
        # 解析目标日期的月份
        target_month = int(target_date[4:6])
        
        # 检查时间维度名称
        time_dim = None
        if 'time' in climatology_data.dims:
            time_dim = 'time'
        elif 'valid_time' in climatology_data.dims:
            time_dim = 'valid_time'
        else:
            print(f"错误: 找不到时间维度，可用维度: {list(climatology_data.dims.keys())}")
            return None
        
        print(f"使用时间维度: {time_dim}")
        
        # 提取对应月份的气候态数据
        time_coord = climatology_data[time_dim]
        climatology_month = climatology_data.sel({time_dim: time_coord.dt.month == target_month})
        
        # 计算多年平均
        climatology_mean = climatology_month['t2m'].mean(dim=time_dim).values.squeeze()
        
        # 转换为摄氏度
        climatology_temp = climatology_mean - 273.15
        
        # 计算距平
        temp_anomaly = current_temp - climatology_temp
        
        print(f"成功计算{target_month}月份的温度距平")
        return temp_anomaly
        
    except Exception as e:
        print(f"计算温度距平时出错: {e}")
        print(f"气候态数据维度: {list(climatology_data.dims.keys())}")
        print(f"气候态数据坐标: {list(climatology_data.coords.keys())}")
        return None

def calculate_apparent_temperature(temp_c, dewpoint_c, wind_speed_ms):
    """
    计算体感温度 (Apparent Temperature) 使用澳大利亚气象局公式
    
    参数:
    temp_c : np.array - 温度 (°C)
    dewpoint_c : np.array - 露点温度 (°C)
    wind_speed_ms : np.array - 风速 (m/s)
    
    返回:
    np.array - 体感温度 (°C)
    """
    try:
        # 计算相对湿度
        # 使用Magnus公式计算饱和水汽压
        def vapor_pressure(temp):
            return 6.112 * np.exp((17.67 * temp) / (temp + 243.5))
        
        es = vapor_pressure(temp_c)  # 饱和水汽压
        e = vapor_pressure(dewpoint_c)  # 实际水汽压
        rh = (e / es) * 100  # 相对湿度 (%)
        
        # 确保相对湿度在合理范围内
        rh = np.clip(rh, 0, 100)
        
        # 转换风速为km/h
        wind_speed_kmh = wind_speed_ms * 3.6
        
        # 澳大利亚气象局体感温度公式
        apparent_temp = temp_c + (0.33 * (e - 10)) - (0.70 * wind_speed_kmh) - 4.00
        
        return apparent_temp
        
    except Exception as e:
        print(f"计算体感温度时出错: {e}")
        return temp_c  # 如果计算失败，返回原始温度

def calculate_wet_bulb_temperature(temp_c, dewpoint_c):
    """
    计算湿球温度 (Wet Bulb Temperature) 使用Stull公式的近似方法
    
    参数:
    temp_c : np.array - 温度 (°C)
    dewpoint_c : np.array - 露点温度 (°C)
    
    返回:
    np.array - 湿球温度 (°C)
    """
    try:
        # 使用Stull (2011)的湿球温度近似公式
        # 这是一个相对简单但精度较高的近似方法
        
        # 计算相对湿度
        def vapor_pressure(temp):
            return 6.112 * np.exp((17.67 * temp) / (temp + 243.5))
        
        es = vapor_pressure(temp_c)  # 饱和水汽压
        e = vapor_pressure(dewpoint_c)  # 实际水汽压
        rh = (e / es) * 100  # 相对湿度 (%)
        
        # 确保相对湿度在合理范围内
        rh = np.clip(rh, 0, 100)
        
        # Stull (2011) 湿球温度公式
        wet_bulb = temp_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + \
                   np.arctan(temp_c + rh) - \
                   np.arctan(rh - 1.676331) + \
                   0.00391838 * (rh ** 1.5) * np.arctan(0.023101 * rh) - \
                   4.686035
        
        return wet_bulb
        
    except Exception as e:
        print(f"计算湿球温度时出错: {e}")
        return temp_c  # 如果计算失败，返回原始温度

def calculate_heat_index(temp_c, rh):
    """
    计算热指数 (Heat Index) - 高温高湿环境下的体感温度
    
    参数:
    temp_c : np.array - 温度 (°C)
    rh : np.array - 相对湿度 (%)
    
    返回:
    np.array - 热指数 (°C)
    """
    try:
        # 转换为华氏温度进行计算
        temp_f = temp_c * 9/5 + 32
        
        # 美国国家气象局热指数公式
        # 只在温度 >= 80°F (26.7°C) 且相对湿度 >= 40% 时使用
        
        # 简化公式（温度较低时）
        hi_f = 0.5 * (temp_f + 61.0 + ((temp_f - 68.0) * 1.2) + (rh * 0.094))
        
        # 如果温度较高，使用完整公式
        mask = temp_f >= 80
        if np.any(mask):
            # Rothfusz回归方程系数
            c1 = -42.379
            c2 = 2.04901523
            c3 = 10.14333127
            c4 = -0.22475541
            c5 = -0.00683783
            c6 = -0.05481717
            c7 = 0.00122874
            c8 = 0.00085282
            c9 = -0.00000199
            
            # 完整公式
            hi_full = (c1 + c2*temp_f[mask] + c3*rh[mask] + 
                      c4*temp_f[mask]*rh[mask] + c5*temp_f[mask]**2 + 
                      c6*rh[mask]**2 + c7*temp_f[mask]**2*rh[mask] + 
                      c8*temp_f[mask]*rh[mask]**2 + c9*temp_f[mask]**2*rh[mask]**2)
            
            hi_f[mask] = hi_full
        
        # 转换回摄氏度
        hi_c = (hi_f - 32) * 5/9
        
        return hi_c
        
    except Exception as e:
        print(f"计算热指数时出错: {e}")
        return temp_c

def get_temperature_color_scheme_by_type(temp_type):
    """
    根据温度类型返回相应的配色方案
    """
    if temp_type == 'anomaly':
        # 距平专用配色：蓝色(负距平) -> 白色(无距平) -> 红色(正距平)
        colors = [
            "#000080",  # 深蓝 (-15°C)
            "#0000FF",  # 蓝色 (-10°C)
            "#4169E1",  # 皇家蓝 (-8°C)
            "#87CEEB",  # 天蓝 (-6°C)
            "#B0E0E6",  # 粉蓝 (-4°C)
            "#E0F6FF",  # 极浅蓝 (-2°C)
            "#FFFFFF",  # 白色 (0°C) - 无距平
            "#FFE4E1",  # 极浅红 (+2°C)
            "#FFB6C1",  # 浅粉红 (+4°C)
            "#FF69B4",  # 热粉红 (+6°C)
            "#FF1493",  # 深粉红 (+8°C)
            "#FF0000",  # 红色 (+10°C)
            "#8B0000",  # 深红 (+15°C)
        ]
        temp_points = [-15, -10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10, 15]
        min_temp, max_temp = -15, 15
        levels = list(range(-15, 16, 1))
        
    elif temp_type in ['wetbulb', 'heatindex']:
        # 湿球温度和热指数配色：较低范围，强调高温危险区
        colors = [
            "#000080",  # 深蓝 (0°C)
            "#4169E1",  # 皇家蓝 (5°C)
            "#87CEEB",  # 天蓝 (10°C)
            "#B0E0E6",  # 粉蓝 (15°C)
            "#FFFFFF",  # 白色 (20°C)
            "#FFFF00",  # 黄色 (25°C)
            "#FFA500",  # 橙色 (30°C)
            "#FF4500",  # 橙红 (35°C)
            "#FF0000",  # 红色 (40°C)
            "#8B0000",  # 深红 (45°C)
            "#4B0000",  # 栗色 (50°C)
        ]
        temp_points = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        min_temp, max_temp = 0, 50
        levels = list(range(0, 51, 2))
        
    elif temp_type == 'apparent':
        # 体感温度配色：考虑人体舒适度
        colors = [
            "#000080",  # 深蓝 (-20°C)
            "#4169E1",  # 皇家蓝 (-10°C)
            "#87CEEB",  # 天蓝 (0°C)
            "#B0E0E6",  # 粉蓝 (10°C)
            "#FFFFFF",  # 白色 (20°C) - 舒适温度
            "#FFFF7F",  # 浅黄 (25°C)
            "#FFFF00",  # 黄色 (30°C)
            "#FFA500",  # 橙色 (35°C)
            "#FF4500",  # 橙红 (40°C)
            "#FF0000",  # 红色 (45°C)
            "#8B0000",  # 深红 (50°C)
        ]
        temp_points = [-20, -10, 0, 10, 20, 25, 30, 35, 40, 45, 50]
        min_temp, max_temp = -20, 50
        levels = list(range(-20, 51, 2))
        
    elif temp_type == 'dew':
        # 露点温度配色：强调湿度舒适度
        colors = [
            "#000080",  # 深蓝 (-20°C)
            "#4169E1",  # 皇家蓝 (-10°C)
            "#87CEEB",  # 天蓝 (0°C)
            "#B0E0E6",  # 粉蓝 (10°C)
            "#E0F6FF",  # 极浅蓝 (15°C) - 舒适
            "#FFFFFF",  # 白色 (20°C)
            "#FFE4E1",  # 极浅红 (22°C)
            "#FFFF00",  # 黄色 (25°C) - 开始不舒适
            "#FFA500",  # 橙色 (28°C)
            "#FF0000",  # 红色 (30°C) - 非常不舒适
            "#8B0000",  # 深红 (35°C)
        ]
        temp_points = [-20, -10, 0, 10, 15, 20, 22, 25, 28, 30, 35]
        min_temp, max_temp = -20, 35
        levels = list(range(-20, 36, 2))
        
    elif temp_type == 'ground':
        # 地表温度配色：范围更广，强调极端值
        colors = [
            "#4B0082",  # 靛青 (-40°C)
            "#000080",  # 深蓝 (-20°C)
            "#4169E1",  # 皇家蓝 (0°C)
            "#87CEEB",  # 天蓝 (10°C)
            "#FFFFFF",  # 白色 (20°C)
            "#FFFF00",  # 黄色 (30°C)
            "#FFA500",  # 橙色 (40°C)
            "#FF0000",  # 红色 (50°C)
            "#8B0000",  # 深红 (60°C)
            "#4B0000",  # 栗色 (70°C)
            "#2F0000",  # 极深红 (80°C)
        ]
        temp_points = [-40, -20, 0, 10, 20, 30, 40, 50, 60, 70, 80]
        min_temp, max_temp = -40, 80
        levels = list(range(-40, 81, 5))
        
    else:
        # 默认通用温度配色方案 (适用于 2mT, 100mT, min, max 等)
        colors = [
            "#B3B0B0",  # 灰色 (-60°C)
            "#7EE1E1",  # 青绿色 (-50°C)
            "#8EB2EB",  # 青色 (-40°C)
            "#C881E6",  # 深紫色 (-30°C)
            "#87A3FC",  # 深蓝色 (-20°C)
            '#87CEEB',  # 天蓝 (-10°C)
            '#FFFFFF',  # 白色 (0°C)
            "#52FF52",  # 淡绿 (10°C)
            '#FFFF00',  # 黄色 (20°C)
            '#FF0000',  # 红色 (30°C)
            '#C71585',  # 中紫罗兰红 (35°C)
            '#8A2BE2',  # 蓝紫色 (40°C)
            '#E6E6FA',  # 淡紫色 (45°C)
            '#FFFFFF',  # 纯白 (50°C)
        ]
        temp_points = [-60, -50, -40, -30, -20, -10, 0, 10, 20, 30, 35, 40, 45, 50]
        min_temp, max_temp = -60, 50
        levels = list(range(int(min_temp), int(max_temp) + 1, 2))
    
    return colors, temp_points, levels, min_temp, max_temp

def download_era5_surface_data(date, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5地面再分析数据
    
    参数:
    date : str - 日期时间字符串 (YYYYMMDDHH)
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

def download_era5_climatology_surface_data(variables, lon_min, lon_max, lat_min, lat_max, 
                                         start_year=1991, end_year=2020):
    """
    下载ERA5地面气候态数据（用于计算距平）
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None
        
    c = cdsapi.Client()
    
    try:
        temp_dir = tempfile.gettempdir()
        temp_filename = f"era5_surface_climatology_temp_{os.getpid()}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        # 下载地面气候态数据（1991-2020年平均）
        years = [str(year) for year in range(start_year, end_year + 1)]
        
        c.retrieve(
            'reanalysis-era5-single-levels-monthly-means',
            {
                'product_type': 'monthly_averaged_reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'year': years,
                'month': ['01', '02', '03', '04', '05', '06', 
                         '07', '08', '09', '10', '11', '12'],
                'time': '00:00',
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
        print(f"下载ERA5地面气候态数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def calculate_temperature_anomaly(current_temp, climatology_data, target_date):
    """
    计算温度距平
    
    参数:
    current_temp : np.array - 当前温度 (°C)
    climatology_data : xr.Dataset - 气候态数据
    target_date : str - 目标日期 (YYYYMMDDHH)
    
    返回:
    np.array - 温度距平 (°C)
    """
    try:
        # 解析目标日期的月份
        target_month = int(target_date[4:6])
        
        # 检查时间维度名称
        time_dim = None
        if 'time' in climatology_data.dims:
            time_dim = 'time'
        elif 'valid_time' in climatology_data.dims:
            time_dim = 'valid_time'
        else:
            print(f"错误: 找不到时间维度，可用维度: {list(climatology_data.dims.keys())}")
            return None
        
        print(f"使用时间维度: {time_dim}")
        
        # 提取对应月份的气候态数据
        time_coord = climatology_data[time_dim]
        climatology_month = climatology_data.sel({time_dim: time_coord.dt.month == target_month})
        
        # 计算多年平均
        climatology_mean = climatology_month['t2m'].mean(dim=time_dim).values.squeeze()
        
        # 转换为摄氏度
        climatology_temp = climatology_mean - 273.15
        
        # 计算距平
        temp_anomaly = current_temp - climatology_temp
        
        print(f"成功计算{target_month}月份的温度距平")
        return temp_anomaly
        
    except Exception as e:
        print(f"计算温度距平时出错: {e}")
        print(f"气候态数据维度: {list(climatology_data.dims.keys())}")
        print(f"气候态数据坐标: {list(climatology_data.coords.keys())}")
        return None

def calculate_apparent_temperature(temp_c, dewpoint_c, wind_speed_ms):
    """
    计算体感温度 (Apparent Temperature) 使用澳大利亚气象局公式
    
    参数:
    temp_c : np.array - 温度 (°C)
    dewpoint_c : np.array - 露点温度 (°C)
    wind_speed_ms : np.array - 风速 (m/s)
    
    返回:
    np.array - 体感温度 (°C)
    """
    try:
        # 计算相对湿度
        # 使用Magnus公式计算饱和水汽压
        def vapor_pressure(temp):
            return 6.112 * np.exp((17.67 * temp) / (temp + 243.5))
        
        es = vapor_pressure(temp_c)  # 饱和水汽压
        e = vapor_pressure(dewpoint_c)  # 实际水汽压
        rh = (e / es) * 100  # 相对湿度 (%)
        
        # 确保相对湿度在合理范围内
        rh = np.clip(rh, 0, 100)
        
        # 转换风速为km/h
        wind_speed_kmh = wind_speed_ms * 3.6
        
        # 澳大利亚气象局体感温度公式
        apparent_temp = temp_c + (0.33 * (e - 10)) - (0.70 * wind_speed_kmh) - 4.00
        
        return apparent_temp
        
    except Exception as e:
        print(f"计算体感温度时出错: {e}")
        return temp_c  # 如果计算失败，返回原始温度

def calculate_wet_bulb_temperature(temp_c, dewpoint_c):
    """
    计算湿球温度 (Wet Bulb Temperature) 使用Stull公式的近似方法
    
    参数:
    temp_c : np.array - 温度 (°C)
    dewpoint_c : np.array - 露点温度 (°C)
    
    返回:
    np.array - 湿球温度 (°C)
    """
    try:
        # 使用Stull (2011)的湿球温度近似公式
        # 这是一个相对简单但精度较高的近似方法
        
        # 计算相对湿度
        def vapor_pressure(temp):
            return 6.112 * np.exp((17.67 * temp) / (temp + 243.5))
        
        es = vapor_pressure(temp_c)  # 饱和水汽压
        e = vapor_pressure(dewpoint_c)  # 实际水汽压
        rh = (e / es) * 100  # 相对湿度 (%)
        
        # 确保相对湿度在合理范围内
        rh = np.clip(rh, 0, 100)
        
        # Stull (2011) 湿球温度公式
        wet_bulb = temp_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + \
                   np.arctan(temp_c + rh) - \
                   np.arctan(rh - 1.676331) + \
                   0.00391838 * (rh ** 1.5) * np.arctan(0.023101 * rh) - \
                   4.686035
        
        return wet_bulb
        
    except Exception as e:
        print(f"计算湿球温度时出错: {e}")
        return temp_c  # 如果计算失败，返回原始温度

def calculate_heat_index(temp_c, rh):
    """
    计算热指数 (Heat Index) - 高温高湿环境下的体感温度
    
    参数:
    temp_c : np.array - 温度 (°C)
    rh : np.array - 相对湿度 (%)
    
    返回:
    np.array - 热指数 (°C)
    """
    try:
        # 转换为华氏温度进行计算
        temp_f = temp_c * 9/5 + 32
        
        # 美国国家气象局热指数公式
        # 只在温度 >= 80°F (26.7°C) 且相对湿度 >= 40% 时使用
        
        # 简化公式（温度较低时）
        hi_f = 0.5 * (temp_f + 61.0 + ((temp_f - 68.0) * 1.2) + (rh * 0.094))
        
        # 如果温度较高，使用完整公式
        mask = temp_f >= 80
        if np.any(mask):
            # Rothfusz回归方程系数
            c1 = -42.379
            c2 = 2.04901523
            c3 = 10.14333127
            c4 = -0.22475541
            c5 = -0.00683783
            c6 = -0.05481717
            c7 = 0.00122874
            c8 = 0.00085282
            c9 = -0.00000199
            
            # 完整公式
            hi_full = (c1 + c2*temp_f[mask] + c3*rh[mask] + 
                      c4*temp_f[mask]*rh[mask] + c5*temp_f[mask]**2 + 
                      c6*rh[mask]**2 + c7*temp_f[mask]**2*rh[mask] + 
                      c8*temp_f[mask]*rh[mask]**2 + c9*temp_f[mask]**2*rh[mask]**2)
            
            hi_f[mask] = hi_full
        
        # 转换回摄氏度
        hi_c = (hi_f - 32) * 5/9
        
        return hi_c
        
    except Exception as e:
        print(f"计算热指数时出错: {e}")
        return temp_c

def get_temperature_variables(temp_type):
    """
    根据温度类型返回需要下载的ERA5变量，并检查可用性
    """
    base_vars = ['mean_sea_level_pressure']  # 基础气压数据
    
    temp_var_mapping = {
        '2mT': {
            'vars': ['2m_temperature'],
            'available': True,
            'description': '2米温度'
        },
        '100mT': {
            'vars': ['2m_temperature'],  # ERA5没有100m温度，使用2m代替
            'available': False,
            'description': '100米温度 (ERA5不可用，将使用2m温度代替)'
        },
        'min': {
            'vars': ['2m_temperature'],  # 使用日最低温度但ERA5可能不直接提供
            'available': True,
            'description': '最低温度 (可能需要处理)'
        },
        'max': {
            'vars': ['2m_temperature'],  # 使用日最高温度但ERA5可能不直接提供
            'available': True,
            'description': '最高温度 (可能需要处理)'
        },
        'dew': {
            'vars': ['2m_dewpoint_temperature'],
            'available': True,
            'description': '露点温度'
        },
        'ground': {
            'vars': ['skin_temperature'],
            'available': True,
            'description': '地表温度'
        },
        'apparent': {
            'vars': ['2m_temperature', '2m_dewpoint_temperature', '10m_u_component_of_wind', '10m_v_component_of_wind'],
            'available': True,
            'description': '体感温度 (需要温度、露点、风速)'
        },
        'wetbulb': {
            'vars': ['2m_temperature', '2m_dewpoint_temperature'],
            'available': True,
            'description': '湿球温度 (需要温度和露点)'
        },
        'heatindex': {
            'vars': ['2m_temperature', '2m_dewpoint_temperature'],
            'available': True,
            'description': '热指数 (需要温度和露点计算相对湿度)'
        },
        'anomaly': {
            'vars': ['2m_temperature'],
            'available': True,
            'description': '温度距平 (需要气候态数据)'
        }
    }
    
    if temp_type not in temp_var_mapping:
        print(f"警告: 未知温度类型 {temp_type}，使用2m温度")
        return base_vars + ['2m_temperature'], True, '2米温度 (默认)'
    
    mapping = temp_var_mapping[temp_type]
    print(f"温度类型: {mapping['description']}")
    print(f"可用性: {'可用' if mapping['available'] else '不完全可用'}")
    
    return base_vars + mapping['vars'], mapping['available'], mapping['description']

def process_temperature_data(ds, temp_type, climatology_data=None, target_date=None):
    """
    根据温度类型处理温度数据，包含所有温度计算函数
    """
    if temp_type == '2mT':
        temp_data = ds['t2m'].values.squeeze() - 273.15
        
    elif temp_type == '100mT':
        print("注意: ERA5没有100m温度数据，使用2m温度代替")
        temp_data = ds['t2m'].values.squeeze() - 273.15
        
    elif temp_type == 'min':
        # ERA5小时数据中的2m温度就是瞬时值，不是日最低温度
        print("注意: 使用当前时刻2m温度，不是日最低温度")
        temp_data = ds['t2m'].values.squeeze() - 273.15
            
    elif temp_type == 'max':
        # ERA5小时数据中的2m温度就是瞬时值，不是日最高温度
        print("注意: 使用当前时刻2m温度，不是日最高温度")
        temp_data = ds['t2m'].values.squeeze() - 273.15
            
    elif temp_type == 'dew':
        temp_data = ds['d2m'].values.squeeze() - 273.15
        
    elif temp_type == 'ground':
        temp_data = ds['skt'].values.squeeze() - 273.15
        
    elif temp_type == 'apparent':
        temp_c = ds['t2m'].values.squeeze() - 273.15
        dewpoint_c = ds['d2m'].values.squeeze() - 273.15
        u10 = ds['u10'].values.squeeze()
        v10 = ds['v10'].values.squeeze()
        wind_speed = np.sqrt(u10**2 + v10**2)
        temp_data = calculate_apparent_temperature(temp_c, dewpoint_c, wind_speed)
        
    elif temp_type == 'wetbulb':
        temp_c = ds['t2m'].values.squeeze() - 273.15
        dewpoint_c = ds['d2m'].values.squeeze() - 273.15
        temp_data = calculate_wet_bulb_temperature(temp_c, dewpoint_c)
        
    elif temp_type == 'heatindex':
        temp_c = ds['t2m'].values.squeeze() - 273.15
        dewpoint_c = ds['d2m'].values.squeeze() - 273.15
        
        # 计算相对湿度
        def vapor_pressure(temp):
            return 6.112 * np.exp((17.67 * temp) / (temp + 243.5))
        
        es = vapor_pressure(temp_c)  # 饱和水汽压
        e = vapor_pressure(dewpoint_c)  # 实际水汽压
        rh = (e / es) * 100  # 相对湿度 (%)
        rh = np.clip(rh, 0, 100)
        
        temp_data = calculate_heat_index(temp_c, rh)
        
    elif temp_type == 'anomaly':
        current_temp = ds['t2m'].values.squeeze() - 273.15
        
        if climatology_data is None or target_date is None:
            print("错误: 计算温度距平需要气候态数据和目标日期")
            return current_temp
        
        temp_data = calculate_temperature_anomaly(current_temp, climatology_data, target_date)
        
        if temp_data is None:
            print("温度距平计算失败，返回绝对温度")
            temp_data = current_temp
        
    else:
        print(f"未知温度类型: {temp_type}，使用2m温度")
        temp_data = ds['t2m'].values.squeeze() - 273.15
    
    return temp_data

def get_temperature_type_label(temp_type):
    """
    返回温度类型的显示标签
    """
    labels = {
        '2mT': '2m Temperature',
        '100mT': '100m Temperature',
        'min': 'Minimum Temperature',
        'max': 'Maximum Temperature',
        'dew': 'Dewpoint Temperature',
        'ground': 'Ground Temperature',
        'apparent': 'Apparent Temperature',
        'wetbulb': 'Wet Bulb Temperature',
        'heatindex': 'Heat Index',
        'anomaly': 'Temperature Anomaly'
    }
    return labels.get(temp_type, '2m Temperature')

def draw_mslp_and_temperature_with_numbers(date_str='2021021700', file_path=None, output_image_path='Output/MeteoMap/surface_temperature_numbers_map.png', 
                                          hour=0, lon_min=95, lon_max=150, lat_min=5, lat_max=35, 
                                          data_source='ERA5', smooth_sigma=2, download_data=True,
                                          use_china_boundaries=True, temp_type='2mT',
                                          temp_number_interval=3, temp_contour_interval=2,
                                          show_pressure_contours=True, pressure_contour_interval=6):
    """
    绘制海平面气压场和温度场，支持真实的温度距平计算
    """
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    # 检查温度类型可用性
    variables, is_available, description = get_temperature_variables(temp_type)
    if not is_available:
        print(f"警告: {description}")

    # 数据获取
    if download_data and file_path is None:
        print(f"正在下载 {date_str} 的ERA5地面数据 (温度类型: {temp_type})...")
        print(f"下载变量: {variables}")
        
        # 下载当前时刻地面数据
        ds = download_era5_surface_data(
            date=date_str,
            variables=variables,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if ds is None:
            print("数据下载失败，退出...")
            return
        
        # 如果是距平类型，需要下载气候态数据
        climatology_data = None
        if temp_type == 'anomaly':
            print("正在下载气候态数据...")
            climatology_data = download_era5_climatology_surface_data(
                variables=['2m_temperature'],
                lon_min=lon_min,
                lon_max=lon_max,
                lat_min=lat_min,
                lat_max=lat_max
            )
            
            if climatology_data is None:
                print("气候态数据下载失败，将使用绝对温度")
        
        # 提取基础数据
        mslp = ds['msl'].values.squeeze() / 100  # 转换为hPa
        
        # 处理温度数据
        temp_data = process_temperature_data(ds, temp_type, climatology_data, date_str)
        
        # 获取坐标
        lon = ds.coords['longitude'].values
        lat = ds.coords['latitude'].values
        
    elif file_path is not None:
        # 从文件加载数据
        try:
            if file_path.endswith('.npy'):
                # 处理numpy格式
                data = np.load(file_path)
                mslp = data[0] / 100  # 转换为hPa
                temp_data = data[3] - 273.15 if len(data) > 3 else np.zeros_like(mslp)
                
                # 创建坐标网格
                lon = np.linspace(0, 360, mslp.shape[1])
                lat = np.linspace(90, -90, mslp.shape[0])
                
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
                
                    # 获取变量（尝试各种可能的名称）
                    var_mappings = {
                        'mslp': ['msl', 'slp', 'pressure_msl'],
                        'temp2m': ['t2m', '2t', '2m_temperature', 'temp_2m']
                    }
                    
                    data_vars = {}
                    for var_name, possible_names in var_mappings.items():
                        for name in possible_names:
                            if name in ds:
                                data_vars[var_name] = ds[name].values
                                break
                        else:
                            if var_name == 'temp2m':
                                print("警告: 找不到2米温度变量，使用默认值")
                                data_vars['temp2m'] = np.zeros_like(data_vars['mslp'])
                            else:
                                print(f"错误: 找不到 {var_name} 变量")
                                print("可用变量:", list(ds.variables))
                                return
                    
                    mslp = data_vars['mslp']
                    if np.max(mslp) > 10000:  # 检查单位是否为Pa
                        mslp = mslp / 100  # 转换为hPa
                        
                    temp_data = data_vars['temp2m']
                    
                    # 检查温度单位并转换为摄氏度
                    if np.mean(temp_data) > 100:  # 可能是开尔文
                        temp_data = temp_data - 273.15
                    
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
    
    # 如果使用原始文件，提取感兴趣的区域
    if not download_data:
        # 获取指定范围的索引
        lon_indices = np.where((lon >= lon_min) & (lon <= lon_max))[0]
        lat_indices = np.where((lat >= lat_min) & (lat <= lat_max))[0]
        
        # 提取区域数据
        region_mslp = mslp[np.ix_(lat_indices, lon_indices)]
        region_temp_data = temp_data[np.ix_(lat_indices, lon_indices)]
        region_lon = lon[lon_indices]
        region_lat = lat[lat_indices]
    else:
        # 已经下载了指定区域的数据
        region_mslp = mslp
        region_temp_data = temp_data
        region_lon, region_lat = lon, lat
    
    # 平滑气压数据
    region_mslp_smooth = gaussian_filter(region_mslp, sigma=smooth_sigma)
    
    # 创建网格
    region_lon_grid, region_lat_grid = np.meshgrid(region_lon, region_lat)
    
    # 计算指标
    min_temp = np.min(region_temp_data)
    max_temp = np.max(region_temp_data)
    min_pressure = np.min(region_mslp_smooth)
    max_pressure = np.max(region_mslp_smooth)
    
    temp_label = get_temperature_type_label(temp_type)
    temp_unit = "°C" if temp_type != 'anomaly' else "°C anomaly"
    
    print(f"温度范围: {min_temp:.1f} - {max_temp:.1f} {temp_unit} ({temp_label})")
    print(f"气压范围: {min_pressure:.1f} - {max_pressure:.1f} hPa")
    
    # 设置字体
    try:
        import matplotlib.font_manager as font_manager
        font_manager.fontManager.addfont(r'MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']
    except:
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图形
    fig = plt.figure(figsize=(15, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([region_lon.min(), region_lon.max(), 
                   region_lat.min(), region_lat.max()], 
                  crs=ccrs.PlateCarree())
    
    # 根据温度类型获取配色方案
    temp_colors, temp_points, _, min_temp_display, max_temp_display = get_temperature_color_scheme_by_type(temp_type)

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
    temp_levels_plot = np.linspace(min_temp_display, max_temp_display, 100)
    
    from matplotlib.colors import Normalize
    norm = Normalize(vmin=min_temp_display, vmax=max_temp_display)
    
    contourf = ax.contourf(
        region_lon_grid, region_lat_grid, region_temp_data,
        levels=temp_levels_plot, 
        cmap=cmap, 
        norm=norm,
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='both'
    )
    
    # 添加气压等值线
    if show_pressure_contours:
        pressure_min_round = int(min_pressure // pressure_contour_interval) * pressure_contour_interval
        pressure_max_round = int(max_pressure // pressure_contour_interval + 1) * pressure_contour_interval
        pressure_levels = np.arange(pressure_min_round, pressure_max_round + pressure_contour_interval, pressure_contour_interval)
        
        pressure_contour = ax.contour(
            region_lon_grid, region_lat_grid, region_mslp_smooth, 
            levels=pressure_levels, 
            colors='black', 
            linewidths=1.5,
            alpha=1.0
        )
        ax.clabel(pressure_contour, inline=True, fontsize=9, fmt='%d')
    
    # 添加温度等值线
    temp_contour_min = int(min_temp // temp_contour_interval) * temp_contour_interval
    temp_contour_max = int(max_temp // temp_contour_interval + 1) * temp_contour_interval
    temp_contour_levels = np.arange(temp_contour_min, temp_contour_max + temp_contour_interval, temp_contour_interval)
    
    temp_contour = ax.contour(
        region_lon_grid, region_lat_grid, region_temp_data,
        levels=temp_contour_levels,
        colors='gray',
        linewidths=1.0,
        alpha=0.7,
        linestyles='-'
    )
    ax.clabel(temp_contour, inline=True, fontsize=8, fmt='%d', colors='gray')
    
    # 添加温度数字标注
    skip_factor = max(1, min(region_temp_data.shape) // temp_number_interval)
    
    for i in range(0, region_temp_data.shape[0], skip_factor):
        for j in range(0, region_temp_data.shape[1], skip_factor):
            if i < region_temp_data.shape[0] and j < region_temp_data.shape[1]:
                temp_value = region_temp_data[i, j]
                lon_pos = region_lon_grid[i, j]
                lat_pos = region_lat_grid[i, j]
                
                # 距平显示一位小数，其他显示整数
                if temp_type == 'anomaly':
                    text = f'{temp_value:.1f}'
                else:
                    text = f'{int(round(temp_value))}'
                
                ax.text(lon_pos, lat_pos, text, 
                       fontsize=6, ha='center', va='center', 
                       color='black', weight='bold',
                       transform=ccrs.PlateCarree())
    
    # 添加地图要素（保持原有代码）
    try:
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        
        if use_china_boundaries:
            china_boundaries_added = add_china_boundaries(
                ax, 
                lon_min=region_lon.min(), 
                lon_max=region_lon.max(),
                lat_min=region_lat.min(), 
                lat_max=region_lat.max()
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
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(region_lon.min()), 
                                           np.ceil(region_lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(region_lat.min()), 
                                           np.ceil(region_lat.max()) + 1, 5))

    # 创建色彩条
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    # 设置色彩条刻度
    if temp_type == 'anomaly':
        tick_interval = 2
        tick_start = int(min_temp_display // tick_interval) * tick_interval
        tick_end = int(max_temp_display // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
        # 确保0包含在距平刻度中
        if 0 not in colorbar_ticks:
            colorbar_ticks.append(0)
            colorbar_ticks.sort()
    else:
        tick_interval = 5
        tick_start = int(min_temp_display // tick_interval) * tick_interval
        tick_end = int(max_temp_display // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
        # 确保0度包含在刻度中
        if 0 not in colorbar_ticks and min_temp_display <= 0 <= max_temp_display:
            colorbar_ticks.append(0)
            colorbar_ticks.sort()
    
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label=f'{temp_label} ({temp_unit})')
    
    # 格式化标题
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 左侧标题
    main_title = f'{data_source} MSLP(hPa) and {temp_label}({temp_unit})'
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧标题
    pressure_range_line = f'Pressure: {min_pressure:.1f}-{max_pressure:.1f}hPa'
    temp_range_line = f'{temp_label}: {min_temp:.1f}-{max_temp:.1f}{temp_unit}'
    
    ax.text(0.99, 1.015, pressure_range_line+'\n'+temp_range_line, transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=14, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"图像已保存: {output_image_path}")
    
    pressure_info = f"Pressure interval: {pressure_contour_interval}hPa" if show_pressure_contours else "Pressure contours: OFF"
    print(f"配置 - {pressure_info}, {temp_label} 范围: {min_temp:.1f}-{max_temp:.1f}{temp_unit}")
    print(f"温度类型: {description}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2022120100'
    
    # 支持的温度类型及其可用性检查
    available_temp_types = {
        '2mT': '2米温度 - 完全可用',
        '100mT': '100米温度 - ERA5不可用，使用2m代替',
        'min': '最低温度 - 瞬时值，非日最低',
        'max': '最高温度 - 瞬时值，非日最高', 
        'dew': '露点温度 - 完全可用',
        'ground': '地表温度 - 完全可用',
        'apparent': '体感温度 - 完全可用(需计算)',
        'wetbulb': '湿球温度 - 完全可用(需计算)',
        'heatindex': '热指数 - 完全可用(需计算)',
        'anomaly': '温度距平 - 完全可用(需气候态数据)'
    }
    
    print("可用的温度类型:")
    for temp_type, description in available_temp_types.items():
        # 测试配色方案
        colors, temp_points, _, min_temp, max_temp = get_temperature_color_scheme_by_type(temp_type)
        print(f"  {temp_type}: {description}")
        print(f"    配色范围: {min_temp}°C 到 {max_temp}°C")
    
    print("\n" + "="*50)
    
    # 选择要生成的温度类型
    selected_temp_type = '2mT'  # 修改这里：'2mT', 'dew', 'apparent', 'wetbulb', 'heatindex', 'anomaly', 'ground'
    
    print(f"选择的温度类型: {selected_temp_type}")
    print(f"描述: {available_temp_types.get(selected_temp_type, '未知类型')}")
    
    # 根据温度类型调整等值线间隔
    if selected_temp_type == 'anomaly':
        temp_contour_interval = 1  # 距平使用1度间隔
    elif selected_temp_type in ['wetbulb', 'heatindex']:
        temp_contour_interval = 2  # 湿球温度和热指数使用2度间隔
    else:
        temp_contour_interval = 3  # 其他类型使用3度间隔
    
    print(f"\n正在生成 {selected_temp_type} 温度图...")
    
    try:
        draw_mslp_and_temperature_with_numbers(
            date_str=date_str, 
            output_image_path=f'Output/MeteoMap/ERA5_Surface_{selected_temp_type}_temp_MSLP_{date_str}.png', 
            hour=0,
            lon_min=60, 
            lon_max=180, 
            lat_min=0, 
            lat_max=50,
            download_data=True,
            use_china_boundaries=True,
            temp_type=selected_temp_type,
            temp_number_interval=30,
            temp_contour_interval=temp_contour_interval,
            show_pressure_contours=True,
            pressure_contour_interval=6
        )
        print(f"✅ {selected_temp_type} 图像生成完成")

    except Exception as e:
        print(f"❌ {selected_temp_type} 图像生成失败: {e}")
        import traceback
        traceback.print_exc()