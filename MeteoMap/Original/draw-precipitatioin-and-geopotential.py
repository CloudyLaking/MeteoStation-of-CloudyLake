import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter
import xarray as xr
import os
import datetime as dt
from matplotlib.colors import LinearSegmentedColormap, BoundaryNorm
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

def download_era5_precipitation_data(date, precip_type, time_period, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5降水数据
    
    参数:
    date : str - 日期时间字符串 (YYYYMMDDHH)
    precip_type : str - 降水类型 ('total', 'snow', 'phase')
    time_period : str - 时间段 ('1h', '3h', '6h', '12h', '24h')
    """
    try:
        import cdsapi
        import tempfile
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None
        
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    c = cdsapi.Client()
    
    # 根据降水类型和时间段选择变量
    variables = ['total_precipitation']  # 基础变量
    
    if precip_type == 'snow':
        variables.append('snowfall')
    elif precip_type == 'phase':
        variables.extend(['snowfall', '2m_temperature'])
    
    # 根据时间段确定需要下载的时次
    current_hour = int(hour)
    time_hours = []
    
    if time_period == '1h':
        time_hours = [f'{current_hour:02d}:00']
    elif time_period == '3h':
        time_hours = [f'{(current_hour - i):02d}:00' for i in range(3)]
    elif time_period == '6h':
        time_hours = [f'{(current_hour - i):02d}:00' for i in range(6)]
    elif time_period == '12h':
        time_hours = [f'{(current_hour - i):02d}:00' for i in range(12)]
    elif time_period == '24h':
        time_hours = [f'{(current_hour - i):02d}:00' for i in range(24)]
    
    # 处理跨日期的情况
    time_hours = [t for t in time_hours if int(t.split(':')[0]) >= 0]
    
    try:
        temp_dir = tempfile.gettempdir()
        temp_filename = f"era5_precip_temp_{os.getpid()}_{date}_{precip_type}_{time_period}.nc"
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
                'time': time_hours,
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
        print(f"下载ERA5降水数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def download_era5_height_data(date, pressure_level, lon_min, lon_max, lat_min, lat_max):
    """
    下载ERA5位势高度数据
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
        temp_filename = f"era5_height_temp_{os.getpid()}_{date}_{pressure_level}.nc"
        output_file = os.path.join(temp_dir, temp_filename)
        
        if os.path.exists(output_file):
            os.remove(output_file)
            
        c.retrieve(
            'reanalysis-era5-pressure-levels',
            {
                'product_type': 'reanalysis',
                'format': 'netcdf',
                'variable': ['geopotential'],
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
        print(f"下载ERA5位势高度数据时出错: {e}")
        if 'output_file' in locals() and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except:
                pass
        return None

def process_precipitation_data(ds, precip_type, time_period):
    """
    处理降水数据，包括累积和相态计算
    """
    # 转换为mm/h
    total_precip = ds['tp'].values * 1000  # m -> mm
    
    if len(total_precip.shape) > 2:  # 有时间维度
        # 累积降水
        total_precip = np.sum(total_precip, axis=0)
    
    if precip_type == 'total':
        return total_precip
    
    elif precip_type == 'snow':
        snow_precip = ds['sf'].values * 1000  # m -> mm
        if len(snow_precip.shape) > 2:
            snow_precip = np.sum(snow_precip, axis=0)
        return snow_precip
    
    elif precip_type == 'phase':
        # 计算降水相态
        if 'sf' in ds and 't2m' in ds:
            snow_precip = ds['sf'].values * 1000
            temp_2m = ds['t2m'].values - 273.15  # K -> °C
            
            if len(snow_precip.shape) > 2:
                snow_precip = np.sum(snow_precip, axis=0)
                temp_2m = np.mean(temp_2m, axis=0)  # 平均温度
            
            # 计算降水相态 (雨雪混合指数)
            # 0 = 纯雨, 0.5 = 雨雪混合, 1 = 纯雪
            snow_ratio = snow_precip / (total_precip + 1e-6)  # 避免除零
            snow_ratio = np.clip(snow_ratio, 0, 1)
            
            # 温度修正
            temp_factor = np.where(temp_2m <= -2, 1.0,
                                 np.where(temp_2m >= 2, 0.0,
                                        (2 - temp_2m) / 4))  # -2到2度线性过渡
            
            phase_index = snow_ratio * temp_factor
            return phase_index
        else:
            print("缺少雪和温度数据，返回总降水")
            return total_precip
    
    return total_precip

def get_precipitation_color_scheme(precip_type, time_period):
    """
    根据降水类型和时间段返回配色方案，遵循中国气象局标准
    """
    if precip_type == 'total':
        # 统一的降水配色方案（按照您提供的24h色阶）
        base_colors = [
            "#FFFFFF",  # 白色 - 无雨
            "#C0FFC0",  # 浅绿 - 微量
            "#80FF80",  # 绿色 - 小雨-中雨
            "#40C0FF",  # 浅蓝 - 大雨
            "#0080FF",  # 蓝色 - 暴雨
            "#FF00FF",  # 紫色 - 大暴雨
            "#FF0000",  # 红色 - 特大暴雨
        ]
        
        if time_period in ['24h']:
            colors = base_colors
            levels = [0, 0.1, 10, 25, 50, 100, 250]
            
        elif time_period in ['12h']:
            colors = base_colors
            levels = [0, 0.1, 5, 15, 30, 70, 140]
            
        elif time_period in ['3h', '6h']:
            colors = base_colors
            levels = [0, 0.1, 2, 5, 10, 20, 50]
            
        elif time_period == '1h':
            colors = base_colors
            levels = [0, 0.1, 1, 2.5, 5, 20, 40]
            
    elif precip_type == 'snow':
        # 降雪使用蓝色系渐进
        if time_period in ['24h']:
            colors = [
                "#FFFFFF",  # 白色 (0mm) - 无雪
                "#F0F8FF",  # 爱丽丝蓝 (0.1mm) - 微量
                "#E0F6FF",  # 极浅蓝 (2.5mm) - 小雪
                "#B3D9FF",  # 浅蓝 (5mm) - 中雪
                "#87CEEB",  # 天蓝 (10mm) - 大雪/暴雪
                "#4169E1",  # 皇家蓝 (20mm) - 大暴雪
                "#0000FF",  # 蓝色 (30mm) - 特大暴雪
            ]
            levels = [0, 0.1, 2.5, 5, 10, 20, 30]
            
        elif time_period in ['12h']:
            colors = [
                "#FFFFFF",  # 白色 (0mm) - 无雪
                "#F0F8FF",  # 爱丽丝蓝 (0.1mm) - 微量
                "#E0F6FF",  # 极浅蓝 (1.5mm) - 小雪
                "#B3D9FF",  # 浅蓝 (3mm) - 中雪
                "#87CEEB",  # 天蓝 (6mm) - 大雪/暴雪
                "#4169E1",  # 皇家蓝 (10mm) - 大暴雪
                "#0000FF",  # 蓝色 (15mm) - 特大暴雪
            ]
            levels = [0, 0.1, 1.5, 3, 6, 10, 15]
            
        elif time_period in ['3h', '6h']:
            colors = [
                "#FFFFFF",  # 白色 (0mm) - 无雪
                "#F0F8FF",  # 爱丽丝蓝 (0.1mm) - 微量
                "#E0F6FF",  # 极浅蓝 (0.5mm) - 小雪
                "#B3D9FF",  # 浅蓝 (1mm) - 中雪
                "#87CEEB",  # 天蓝 (2mm) - 大雪
                "#4169E1",  # 皇家蓝 (5mm) - 强雪
                "#0000FF",  # 蓝色 (8mm) - 短时暴雪
            ]
            levels = [0, 0.1, 0.5, 1, 2, 5, 8]
            
        elif time_period == '1h':
            colors = [
                "#FFFFFF",  # 白色 (0mm) - 无雪
                "#F0F8FF",  # 爱丽丝蓝 (0.1mm) - 微量
                "#E0F6FF",  # 极浅蓝 (0.2mm) - 小雪
                "#B3D9FF",  # 浅蓝 (0.5mm) - 中雪
                "#87CEEB",  # 天蓝 (1mm) - 大雪
                "#4169E1",  # 皇家蓝 (2mm) - 强雪
                "#0000FF",  # 蓝色 (4mm) - 1小时强雪
            ]
            levels = [0, 0.1, 0.2, 0.5, 1, 2, 4]
            
    elif precip_type == 'phase':
        # 降水相态：绿色(雨) -> 黄色(混合) -> 白色(雪)
        colors = [
            "#008000",  # 绿色 (纯雨)
            "#32CD32",  # 酸橙绿
            "#ADFF2F",  # 绿黄
            "#FFFF00",  # 黄色 (雨雪混合)
            "#FFE4B5",  # 鹿皮色
            "#FFC0CB",  # 粉红
            "#FFFFFF",  # 白色 (纯雪)
        ]
        levels = [0, 0.1, 0.25, 0.4, 0.6, 0.75, 1.0]
        
    else:
        # 默认配色
        colors = ["#FFFFFF", "#87CEEB", "#4169E1", "#0000FF", "#8B0000"]
        levels = [0, 1, 5, 10, 20]
    
    return colors, levels

def get_precipitation_label_and_unit(precip_type, time_period):
    """
    返回降水类型的标签和单位
    """
    labels = {
        'total': f'Total Precipitation ({time_period})',
        'snow': f'Snowfall ({time_period})', 
        'phase': f'Precipitation Phase ({time_period})'
    }
    
    units = {
        'total': 'mm',
        'snow': 'mm',
        'phase': 'ratio'
    }
    
    return labels.get(precip_type, f'Precipitation ({time_period})'), units.get(precip_type, 'mm')

def draw_precipitation_with_height(date_str='2024072400', 
                                 output_image_path='Output/MeteoMap/precipitation_with_height.png',
                                 hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                                 data_source='ERA5', smooth_sigma=1, download_data=True,
                                 use_china_boundaries=True,
                                 # 降水设置
                                 precip_type='total',  # 'total', 'snow', 'phase'
                                 time_period='6h',     # '1h', '3h', '6h', '12h', '24h'
                                 show_precip_numbers=True,
                                 precip_number_interval=20,
                                 # 500hPa位势高度设置
                                 show_height_contours=True,
                                 height_contour_interval=60):
    """
    绘制降水图，叠加500hPa位势高度等值线
    
    参数:
    precip_type : str - 降水类型 ('total', 'snow', 'phase')
    time_period : str - 时间累积 ('1h', '3h', '6h', '12h', '24h')
    show_precip_numbers : bool - 是否显示降水数值
    precip_number_interval : int - 降水数值标注间隔
    show_height_contours : bool - 是否显示500hPa等值线
    height_contour_interval : int - 位势高度等值线间隔
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5降水数据 ({precip_type}, {time_period})...")
        
        # 下载降水数据
        precip_ds = download_era5_precipitation_data(
            date=date_str,
            precip_type=precip_type,
            time_period=time_period,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if precip_ds is None:
            print("降水数据下载失败，退出...")
            return
        
        # 下载500hPa位势高度数据
        height_ds = None
        if show_height_contours:
            print("正在下载500hPa位势高度数据...")
            height_ds = download_era5_height_data(
                date=date_str,
                pressure_level=500,
                lon_min=lon_min,
                lon_max=lon_max,
                lat_min=lat_min,
                lat_max=lat_max
            )
            
            if height_ds is None:
                print("500hPa数据下载失败，将不显示等值线")
                show_height_contours = False
        
        # 处理降水数据
        precip_data = process_precipitation_data(precip_ds, precip_type, time_period)
        
        # 处理位势高度数据
        height_data = None
        if show_height_contours and height_ds is not None:
            height_data = height_ds['z'].values.squeeze() / 9.80665  # 转换为gpm
        
        # 获取坐标
        lon = precip_ds.coords['longitude'].values
        lat = precip_ds.coords['latitude'].values
        
    else:
        print("错误: 暂不支持从文件加载降水数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 应用平滑
    if smooth_sigma > 0:
        precip_smooth = gaussian_filter(precip_data, sigma=smooth_sigma)
        if height_data is not None:
            height_smooth = gaussian_filter(height_data, sigma=smooth_sigma)
        else:
            height_smooth = None
    else:
        precip_smooth = precip_data
        height_smooth = height_data
    
    # 计算统计信息
    max_precip = np.max(precip_smooth)
    mean_precip = np.mean(precip_smooth[precip_smooth > 0.1])  # 只统计有效降水
    precip_label, precip_unit = get_precipitation_label_and_unit(precip_type, time_period)
    
    # 添加气象标准信息
    standard_info = ""
    if precip_type == 'total':
        if time_period == '24h':
            if max_precip >= 250:
                standard_info = " (特大暴雨)"
            elif max_precip >= 100:
                standard_info = " (大暴雨)"
            elif max_precip >= 50:
                standard_info = " (暴雨)"
            elif max_precip >= 25:
                standard_info = " (大雨)"
        elif time_period == '12h':
            if max_precip >= 140:
                standard_info = " (特大暴雨)"
            elif max_precip >= 70:
                standard_info = " (大暴雨)"
            elif max_precip >= 30:
                standard_info = " (暴雨)"
            elif max_precip >= 15:
                standard_info = " (大雨)"
        elif time_period == '1h':
            if max_precip >= 60:
                standard_info = " (红色预警)"
            elif max_precip >= 40:
                standard_info = " (橙色预警)"
            elif max_precip >= 20:
                standard_info = " (黄色预警)"
    elif precip_type == 'snow':
        if time_period == '24h':
            if max_precip >= 30:
                standard_info = " (特大暴雪)"
            elif max_precip >= 20:
                standard_info = " (大暴雪)"
            elif max_precip >= 10:
                standard_info = " (暴雪)"
        elif time_period == '12h':
            if max_precip >= 15:
                standard_info = " (特大暴雪)"
            elif max_precip >= 10:
                standard_info = " (大暴雪)"
            elif max_precip >= 6:
                standard_info = " (暴雪)"
    
    print(f"降水统计: 最大 {max_precip:.1f}{precip_unit}{standard_info}, 平均 {mean_precip:.1f}{precip_unit}")
    
    height_stats = ""
    if show_height_contours and height_smooth is not None:
        min_height = np.min(height_smooth)
        max_height = np.max(height_smooth)
        height_stats = f"500hPa Height: {min_height:.0f}-{max_height:.0f}gpm"
        print(f"位势高度统计: {height_stats}")
    
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
    
    # 获取降水配色方案（现在包含时间段）
    colors, levels = get_precipitation_color_scheme(precip_type, time_period)
    
    # 创建分段颜色映射（不使用渐变，使用离散色块）
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(levels, ncolors=len(colors), extend='max')
    
    # 绘制降水填充（底层）
    contourf = ax.contourf(lon_grid, lat_grid, precip_smooth, levels=levels, 
                          cmap=cmap, norm=norm, transform=ccrs.PlateCarree(), 
                          alpha=0.8, extend='max')
    
    # 绘制500hPa位势高度等值线（中层）
    if show_height_contours and height_smooth is not None:
        height_min_round = int(min_height // height_contour_interval) * height_contour_interval
        height_max_round = int(max_height // height_contour_interval + 1) * height_contour_interval
        height_levels = np.arange(height_min_round, height_max_round + height_contour_interval, 
                                height_contour_interval)
        
        contour = ax.contour(lon_grid, lat_grid, height_smooth, levels=height_levels, 
                           colors='black', linewidths=1.5, alpha=1.0, transform=ccrs.PlateCarree())
        ax.clabel(contour, inline=True, fontsize=9, fmt='%d', colors='black')
    
    # 添加降水数值标注（顶层）
    if show_precip_numbers:
        skip_factor = max(1, min(precip_smooth.shape) // precip_number_interval)
        
        for i in range(0, precip_smooth.shape[0], skip_factor):
            for j in range(0, precip_smooth.shape[1], skip_factor):
                if i < precip_smooth.shape[0] and j < precip_smooth.shape[1]:
                    precip_value = precip_smooth[i, j]
                    if precip_value > 0.1:  # 只显示有效降水
                        lon_pos = lon_grid[i, j]
                        lat_pos = lat_grid[i, j]
                        
                        if precip_type == 'phase':
                            # 相态显示两位小数
                            text = f'{precip_value:.2f}'
                        else:
                            # 降水量显示一位小数
                            text = f'{precip_value:.1f}'
                        
                        ax.text(lon_pos, lat_pos, text, 
                               fontsize=6, ha='center', va='center', 
                               color='black', weight='bold',
                               transform=ccrs.PlateCarree())
    
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
    
    # 创建离散化的色彩条
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       label=f'{precip_label} ({precip_unit})',
                       ticks=levels, spacing='proportional')
    
    # 格式化标题
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 构建标题
    title_parts = [precip_label]
    if show_height_contours:
        title_parts.append('500hPa GPH')
    
    main_title = f'{data_source} ' + ' + '.join(title_parts)
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', fontsize=14, fontweight='bold', color='black')
    
    # 右侧统计信息
    precip_stats = f'{precip_label}: max {max_precip:.1f}{precip_unit}{standard_info}'
    if not np.isnan(mean_precip):
        precip_stats += f', avg {mean_precip:.1f}{precip_unit}'
    
    stats_lines = [precip_stats]
    if height_stats:
        stats_lines.append(height_stats)
    
    # 移除标准说明部分
    # if precip_type == 'total' and time_period == '24h':
    #     stats_lines.append("标准: 大雨25+, 暴雨50+, 大暴雨100+, 特大暴雨250+mm")
    # elif precip_type == 'total' and time_period == '12h':
    #     stats_lines.append("标准: 大雨15+, 暴雨30+, 大暴雨70+, 特大暴雨140+mm")
    # elif precip_type == 'snow' and time_period == '24h':
    #     stats_lines.append("标准: 暴雪10+, 大暴雪20+, 特大暴雪30+mm")
    # elif precip_type == 'snow' and time_period == '12h':
    #     stats_lines.append("标准: 暴雪6+, 大暴雪10+, 特大暴雪15+mm")
    # elif precip_type == 'total' and time_period == '1h':
    #     stats_lines.append("预警: 黄色20+, 橙色40+, 红色60+mm")
    
    ax.text(0.99, 1.015, '\n'.join(stats_lines), transform=ax.transAxes, 
            ha='right', va='bottom', fontsize=10, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"降水图已保存: {output_image_path}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '20250815612'
    
    # 支持的降水类型和时间段
    available_precip_types = {
        'total': '总降水量',
        'snow': '降雪量', 
        'phase': '降水相态'
    }
    
    available_time_periods = {
        '1h': '1小时累积',
        '3h': '3小时累积',
        '6h': '6小时累积', 
        '12h': '12小时累积',
        '24h': '24小时累积'
    }
    
    print("可用的降水类型:")
    for precip_type, description in available_precip_types.items():
        print(f"  {precip_type}: {description}")
    
    print("\n可用的时间累积:")
    for time_period, description in available_time_periods.items():
        print(f"  {time_period}: {description}")
    
    print("\n" + "="*50)
    
    # 选择要生成的降水类型和时间段（修改这里）
    selected_precip_type = 'total'  # 修改这里：'total', 'snow', 'phase'
    selected_time_period = '24h'     # 修改这里：'1h', '3h', '6h', '12h', '24h'
    
    print(f"选择的降水类型: {selected_precip_type} ({available_precip_types[selected_precip_type]})")
    print(f"选择的时间累积: {selected_time_period} ({available_time_periods[selected_time_period]})")
    
    print(f"\n正在生成 {selected_precip_type} {selected_time_period} 降水图...")
    
    try:
        draw_precipitation_with_height(
            date_str=date_str, 
            output_image_path=f'Output/MeteoMap/ERA5_{selected_precip_type}_precip_{selected_time_period}_{date_str}.png', 
            hour=0,
            lon_min=50, 
            lon_max=90, 
            lat_min=10, 
            lat_max=33,
            download_data=True,
            use_china_boundaries=True,
            # 降水设置
            precip_type=selected_precip_type,
            time_period=selected_time_period,
            show_precip_numbers=True,
            precip_number_interval=20,
            # 500hPa位势高度设置
            show_height_contours=False,
            height_contour_interval=60
        )
        print(f"✅ {selected_precip_type} {selected_time_period} 降水图生成完成")
        print(f"📁 保存位置: Output/MeteoMap/ERA5_{selected_precip_type}_precip_{selected_time_period}_{date_str}.png")
        
    except Exception as e:
        print(f"❌ 降水图生成失败: {e}")
        import traceback
        traceback.print_exc()