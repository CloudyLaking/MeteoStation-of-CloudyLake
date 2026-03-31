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

def get_temperature_variables(temp_type):
    """
    根据温度类型返回需要下载的ERA5变量
    
    参数:
    temp_type : str - 温度类型
    
    返回:
    list - ERA5变量名列表
    """
    base_vars = ['mean_sea_level_pressure', '100m_u_component_of_wind', '100m_v_component_of_wind']
    
    temp_var_mapping = {
        '2mT': ['2m_temperature'],
        '100mT': ['2m_temperature'],  # ERA5没有100m温度，使用2m代替
        'min': ['2m_temperature_min'],
        'max': ['2m_temperature_max'], 
        'dew': ['2m_dewpoint_temperature'],
        'ground': ['skin_temperature'],
        'apparent': ['2m_temperature', '2m_dewpoint_temperature', '100m_u_component_of_wind', '100m_v_component_of_wind'],
        'wetbulb': ['2m_temperature', '2m_dewpoint_temperature'],
        'anomaly': ['2m_temperature']  # 异常需要气候态数据，这里先下载2m温度
    }
    
    temp_vars = temp_var_mapping.get(temp_type, ['2m_temperature'])
    return base_vars + temp_vars

def calculate_apparent_temperature(temp_c, dewpoint_c, wind_speed_ms):
    """
    计算体感温度 (Apparent Temperature)
    使用Australian Bureau of Meteorology公式
    
    参数:
    temp_c : np.array - 气温(摄氏度)
    dewpoint_c : np.array - 露点温度(摄氏度)
    wind_speed_ms : np.array - 风速(m/s)
    
    返回:
    np.array - 体感温度(摄氏度)
    """
    # 计算水汽压(hPa)
    vapor_pressure = 6.112 * np.exp(17.67 * dewpoint_c / (243.5 + dewpoint_c))
    
    # 体感温度公式
    apparent_temp = temp_c + 0.33 * vapor_pressure - 0.7 * wind_speed_ms - 4.0
    
    return apparent_temp

def calculate_wet_bulb_temperature(temp_c, dewpoint_c):
    """
    计算湿球温度 (Wet Bulb Temperature)
    使用Stull (2011)近似公式
    
    参数:
    temp_c : np.array - 气温(摄氏度)
    dewpoint_c : np.array - 露点温度(摄氏度)
    
    返回:
    np.array - 湿球温度(摄氏度)
    """
    # 计算相对湿度
    vapor_pressure_actual = 6.112 * np.exp(17.67 * dewpoint_c / (243.5 + dewpoint_c))
    vapor_pressure_sat = 6.112 * np.exp(17.67 * temp_c / (243.5 + temp_c))
    rh = np.clip(vapor_pressure_actual / vapor_pressure_sat * 100, 0, 100)
    
    # Stull (2011) 湿球温度近似公式
    wet_bulb = temp_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + \
               np.arctan(temp_c + rh) - \
               np.arctan(rh - 1.676331) + \
               0.00391838 * (rh ** 1.5) * np.arctan(0.023101 * rh) - 4.686035
    
    return wet_bulb

def process_temperature_data(ds, temp_type):
    """
    根据温度类型处理温度数据
    
    参数:
    ds : xr.Dataset - ERA5数据集
    temp_type : str - 温度类型
    
    返回:
    np.array - 处理后的温度数据(摄氏度)
    """
    if temp_type == '2mT':
        temp_data = ds['t2m'].values.squeeze() - 273.15
        
    elif temp_type == '100mT':
        # ERA5没有100m温度，使用2m温度代替
        print("注意: ERA5没有100m温度数据，使用2m温度代替")
        temp_data = ds['t2m'].values.squeeze() - 273.15
        
    elif temp_type == 'min':
        if 'mn2t' in ds:
            temp_data = ds['mn2t'].values.squeeze() - 273.15
        else:
            print("警告: 未找到最低温度数据，使用2m温度代替")
            temp_data = ds['t2m'].values.squeeze() - 273.15
            
    elif temp_type == 'max':
        if 'mx2t' in ds:
            temp_data = ds['mx2t'].values.squeeze() - 273.15
        else:
            print("警告: 未找到最高温度数据，使用2m温度代替")
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
        
    elif temp_type == 'anomaly':
        print("警告: 温度异常计算需要气候态数据，当前仅显示绝对温度")
        temp_data = ds['t2m'].values.squeeze() - 273.15
        
    else:
        print(f"未知温度类型: {temp_type}，使用2m温度")
        temp_data = ds['t2m'].values.squeeze() - 273.15
    
    return temp_data

def get_temperature_color_scheme_by_type(temp_type):
    """
    根据温度类型返回相应的配色方案 - 统一使用相同色阶
    """
    # 统一的温度配色方案 - 适用于所有温度类型
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
    
    levels = list(range(int(min_temp), int(max_temp) + 1, 2))
    return colors, temp_points, levels, min_temp, max_temp

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
        'anomaly': 'Temperature Anomaly'
    }
    return labels.get(temp_type, '2m Temperature')

def draw_mslp_and_temperature(date_str='2021021700', file_path=None, output_image_path='Output/MeteoMap/surface_temperature_map.png', 
                             hour=0, lon_min=95, lon_max=150, lat_min=5, lat_max=35, 
                             data_source='ERA5', smooth_sigma=2, download_data=True,
                             use_china_boundaries=True, temp_type='2mT'):
    """
    绘制海平面气压场和温度场
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    file_path : str or None - 数据文件路径，如果为None且download_data=True则下载数据
    output_image_path : str - 输出图片路径
    hour : int - 预报时效(小时)
    lon_min, lon_max, lat_min, lat_max : float - 地理边界
    data_source : str - 数据源标识
    smooth_sigma : float - 气压场平滑参数
    download_data : bool - 是否下载数据
    use_china_boundaries : bool - 是否使用DataV.GeoAtlas的中国官方边界
    temp_type : str - 温度类型 ('2mT', '100mT', 'min', 'max', 'dew', 'ground', 'apparent', 'wetbulb', 'anomaly')
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    # 数据获取
    if download_data and file_path is None:
        print(f"正在下载 {date_str} 的ERA5地面数据 (温度类型: {temp_type})...")
        
        # 获取需要下载的变量
        variables = get_temperature_variables(temp_type)
        print(f"下载变量: {variables}")
        
        # 下载地面数据
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
        
        # 提取基础数据
        mslp = ds['msl'].values.squeeze() / 100  # 转换为hPa
        u10 = ds['u10'].values.squeeze()  # 10米U风分量 (m/s)
        v10 = ds['v10'].values.squeeze()  # 10米V风分量 (m/s)
        
        # 处理温度数据 - 修复变量名
        temp_data = process_temperature_data(ds, temp_type)
        
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
                u10 = data[1]
                v10 = data[2]
                temp_data = data[3] - 273.15 if len(data) > 3 else np.zeros_like(mslp)  # 修复变量名
                
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
                        'u10': ['u10', '10u', 'u_100m'],
                        'v10': ['v10', '10v', 'v_100m'],
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
                        
                    u10 = data_vars['u10']
                    v10 = data_vars['v10']
                    temp_data = data_vars['temp2m']  # 修复变量名
                    
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
        region_u10 = u10[np.ix_(lat_indices, lon_indices)]
        region_v10 = v10[np.ix_(lat_indices, lon_indices)]
        region_temp_data = temp_data[np.ix_(lat_indices, lon_indices)]  # 修复变量名
        region_lon = lon[lon_indices]
        region_lat = lat[lat_indices]
    else:
        # 已经下载了指定区域的数据
        region_mslp = mslp
        region_u10 = u10
        region_v10 = v10
        region_temp_data = temp_data  # 修复变量名
        region_lon, region_lat = lon, lat
    
    # 平滑气压数据
    region_mslp_smooth = gaussian_filter(region_mslp, sigma=smooth_sigma)
    
    # 为风标降采样
    skip_factor = max(1, min(region_mslp.shape) // 20)
    region_lon_grid, region_lat_grid = np.meshgrid(region_lon, region_lat)
    
    # 计算指标
    min_temp = np.min(region_temp_data)  # 修复变量名
    max_temp = np.max(region_temp_data)  # 修复变量名
    min_pressure = np.min(region_mslp_smooth)
    max_pressure = np.max(region_mslp_smooth)
    print(f"温度范围: {min_temp:.1f} - {max_temp:.1f} °C ({get_temperature_type_label(temp_type)})")
    print(f"气压范围: {min_pressure:.1f} - {max_pressure:.1f} hPa")
    
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
    
    # 根据温度类型获取配色方案
    temp_colors, temp_points, _, min_temp_display, max_temp_display = get_temperature_color_scheme_by_type(temp_type)

    # 使用固定的显示范围
    actual_min_temp = min_temp_display
    actual_max_temp = max_temp_display
    
    # 创建温度配色映射
    fixed_min_temp = min_temp_display
    fixed_max_temp = max_temp_display
    
    # 计算每个温度点在固定范围内的归一化位置
    color_positions = []
    valid_colors = []
    
    for i, temp in enumerate(temp_points):
        if i < len(temp_colors):
            pos = (temp - fixed_min_temp) / (fixed_max_temp - fixed_min_temp)
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
    temp_levels_plot = np.linspace(actual_min_temp, actual_max_temp, 100)
    
    from matplotlib.colors import Normalize
    norm = Normalize(vmin=fixed_min_temp, vmax=fixed_max_temp)
    
    contourf = ax.contourf(
        region_lon_grid, region_lat_grid, region_temp_data,  # 修复变量名
        levels=temp_levels_plot, 
        cmap=cmap, 
        norm=norm,
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='both'
    )
    
    # 添加气压等值线 - 2hPa间距
    pressure_min_round = int(min_pressure) - (int(min_pressure) % 2)
    pressure_max_round = int(max_pressure) + (2 - int(max_pressure) % 2)
    pressure_levels = np.arange(pressure_min_round, pressure_max_round + 2, 2)
    
    contour = ax.contour(
        region_lon_grid, region_lat_grid, region_mslp_smooth, 
        levels=pressure_levels, 
        colors='black', 
        linewidths=1.5,
        alpha=1.0
    )
    ax.clabel(contour, inline=True, fontsize=9, fmt='%d')
    
    # 绘制风标
    barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    ax.barbs(
        region_lon_grid[barb_slice], region_lat_grid[barb_slice],
        region_u10[barb_slice], region_v10[barb_slice],
        length=5, pivot='middle', color='black'
    )
    
    # 添加海岸线和边界
    try:
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        
        if use_china_boundaries:
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
            print("使用cartopy默认边界")
            ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
        
    except Exception as e:
        print(f"添加边界时出错: {e}")
        print("使用cartopy默认边界")
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

    # 创建带有适当刻度的色彩条
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    # 设置色彩条刻度
    tick_interval = 5
    tick_start = int(actual_min_temp // tick_interval) * tick_interval
    tick_end   = int(actual_max_temp // tick_interval) * tick_interval
    colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
    
    # 确保0度包含在刻度中
    if 0 not in colorbar_ticks and actual_min_temp <= 0 <= actual_max_temp:
        colorbar_ticks.append(0)
        colorbar_ticks.sort()
    
    temp_label = get_temperature_type_label(temp_type)
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label=f'{temp_label} (°C)')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 左侧标题
    main_title = f'{data_source} MSLP(hPa) and {temp_label}(°C)'
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧标题
    pressure_range_line = f'Pressure: {min_pressure:.1f}-{max_pressure:.1f}hPa'
    temp_range_line = f'{temp_label}: {np.clip(min_temp, min_temp_display, max_temp_display):.1f}-{np.clip(max_temp, min_temp_display, max_temp_display):.1f}°C'
    
    ax.text(0.99, 1.015, pressure_range_line+'\n'+temp_range_line, transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=14, color='black')
    
    # 添加边界使用说明到图片信息
    boundary_info = "China Official Boundaries" if use_china_boundaries else "Cartopy Default Boundaries"
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"Image saved to: {output_image_path}")
    print(f"Configuration - Pressure interval: 2hPa, {temp_label} range: {actual_min_temp:.1f}-{actual_max_temp:.1f}°C")
    print(f"Boundaries: {boundary_info}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024012400'
    
    # 支持的温度类型列表
    available_temp_types = ['2mT', '100mT', 'min', 'max', 'dew', 'ground', 'apparent', 'wetbulb', 'anomaly']
    
    # 示例：绘制不同类型的温度图
    temp_type = 'dew'  # 可选择: '2mT', '100mT', 'min', 'max', 'dew', 'ground', 'apparent', 'wetbulb', 'anomaly'
    
    print(f"可用温度类型: {available_temp_types}")
    print(f"当前选择: {temp_type}")
    
    draw_mslp_and_temperature(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_Surface_MSLP_{temp_type}_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        temp_type=temp_type
    )