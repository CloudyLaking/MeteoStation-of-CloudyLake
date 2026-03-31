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

def get_gust_color_scheme():
    """
    返回阵风配色方案 - 专门针对阵风的颜色设置
    """
    colors = [
        '#FFFFFF', '#E0E0E0', '#87CEEB', '#00BFFF', '#00FF00', 
        '#FFFF00', '#FFA500', '#FF4500', '#FF0000', '#DC143C', 
        '#8B0000', '#4B0082', '#9400D3', '#FF00FF'
    ]
    levels = [i * 5 for i in range(14)]  # 0-65 m/s，阵风通常比平均风速高
    max_display = 70
    
    return colors, levels, max_display

def draw_mslp_and_gust(date_str='2021021700', file_path=None, output_image_path='Output/MeteoMap/surface_gust_map.png', 
                      hour=0, lon_min=95, lon_max=150, lat_min=5, lat_max=35, 
                      data_source='ERA5', smooth_sigma=2, download_data=True,
                      use_china_boundaries=True):
    """
    绘制海平面气压场和阵风场
    
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
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    # 数据获取
    if download_data and file_path is None:
        print(f"正在下载 {date_str} 的ERA5地面数据...")
        
        # 下载地面数据（包括阵风数据）
        ds = download_era5_surface_data(
            date=date_str,
            variables=['mean_sea_level_pressure', '10m_u_component_of_wind', '10m_v_component_of_wind', 'instantaneous_10m_wind_gust'],
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if ds is None:
            print("数据下载失败，退出...")
            return
        
        # 提取数据
        mslp = ds['msl'].values.squeeze() / 100  # 转换为hPa
        u10 = ds['u10'].values.squeeze()  # 10米U风分量 (m/s)
        v10 = ds['v10'].values.squeeze()  # 10米V风分量 (m/s)
        gust = ds['i10fg'].values.squeeze()  # 瞬时10米阵风 (m/s)
        
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
                gust = data[3] if len(data) > 3 else np.sqrt(u10**2 + v10**2) * 1.3  # 如果没有阵风数据，估算
                
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
                        'u10': ['u10', '10u', 'u_10m'],
                        'v10': ['v10', '10v', 'v_10m'],
                        'gust': ['i10fg', 'gust', 'wind_gust', '10m_wind_gust']
                    }
                    
                    data_vars = {}
                    for var_name, possible_names in var_mappings.items():
                        for name in possible_names:
                            if name in ds:
                                data_vars[var_name] = ds[name].values
                                break
                        else:
                            if var_name == 'gust':
                                # 如果没有阵风数据，根据风速估算
                                print("警告: 找不到阵风变量，将根据风速估算")
                                u10_temp = data_vars.get('u10', np.zeros_like(data_vars['mslp']))
                                v10_temp = data_vars.get('v10', np.zeros_like(data_vars['mslp']))
                                data_vars['gust'] = np.sqrt(u10_temp**2 + v10_temp**2) * 1.3
                            else:
                                print(f"错误: 找不到 {var_name} 变量")
                                print("可用变量:", list(ds.variables))
                                return
                    
                    mslp = data_vars['mslp']
                    if np.max(mslp) > 10000:  # 检查单位是否为Pa
                        mslp = mslp / 100  # 转换为hPa
                        
                    u10 = data_vars['u10']
                    v10 = data_vars['v10']
                    gust = data_vars['gust']
                    
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
        region_gust = gust[np.ix_(lat_indices, lon_indices)]
        region_lon = lon[lon_indices]
        region_lat = lat[lat_indices]
    else:
        # 已经下载了指定区域的数据
        region_mslp = mslp
        region_u10 = u10
        region_v10 = v10
        region_gust = gust
        region_lon, region_lat = lon, lat
    
    # 平滑气压数据
    region_mslp_smooth = gaussian_filter(region_mslp, sigma=smooth_sigma)
    
    # 为风标降采样
    skip_factor = max(1, min(region_mslp.shape) // 20)
    region_lon_grid, region_lat_grid = np.meshgrid(region_lon, region_lat)
    
    # 计算指标
    max_gust = np.max(region_gust)
    min_pressure = np.min(region_mslp_smooth)
    max_pressure = np.max(region_mslp_smooth)
    print(f"最大阵风: {max_gust:.2f} m/s")
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
    
    # 设定阵风的等级和对应的颜色
    gust_colors, gust_levels, max_gust_display = get_gust_color_scheme()

    # 根据实际数据调整最大显示值
    actual_max_gust = min(max_gust_display, max(max_gust_display * 0.7, np.ceil(max_gust / 5) * 5))
    
    # 创建具有适当归一化的颜色映射
    # 确保颜色和级别数量相同
    n_colors = min(len(gust_colors), len(gust_levels))
    colors_normalized = gust_colors[:n_colors]
    
    # 创建从0到1的归一化位置
    color_positions = np.linspace(0, 1, n_colors)
    
    cmap = LinearSegmentedColormap.from_list(
        'gust_cmap', 
        list(zip(color_positions, colors_normalized))
    )
    
    # 绘制阵风填充等高线
    contourf = ax.contourf(
        region_lon_grid, region_lat_grid, region_gust, 
        levels=np.linspace(0, actual_max_gust, 100), 
        cmap=cmap, 
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='max'
    )
    
    # 添加气压等值线 - 改为2hPa间距
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
    
    # 绘制风标（使用平均风而非阵风）
    barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    ax.barbs(
        region_lon_grid[barb_slice], region_lat_grid[barb_slice],
        region_u10[barb_slice], region_v10[barb_slice],
        length=5, pivot='middle', color='black'
    )
    
    # 添加海岸线和边界
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
    
    # 添加网格线
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
    
    # 根据阵风级别设置色彩条刻度
    colorbar_ticks = [level for i, level in enumerate(gust_levels[:n_colors]) if i % 2 == 0]
    
    cbar = plt.colorbar(contourf, cax=cax, orientation='vertical', 
                       ticks=colorbar_ticks, label='Wind Gust (m/s)')
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 左侧标题 - 两行固定间距
    main_title = f'{data_source} MSLP(hPa) and Wind Gust(m/s)'
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    # 设置左侧标题（主标题和时间）
    ax.text(0.01, 1.015, main_title+'\n'+time_title, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧标题 - 两行固定间距
    pressure_range_line = f'Pressure: {min_pressure:.1f}-{max_pressure:.1f}hPa'
    max_gust_line = f'Max Gust: {max_gust:.1f}m/s'
    
    ax.text(0.99, 1.015, pressure_range_line+'\n'+max_gust_line, transform=ax.transAxes, ha='right', va='bottom', 
            fontsize=14, color='black')
    
    # 添加边界使用说明到图片信息
    boundary_info = "China Official Boundaries" if use_china_boundaries else "Cartopy Default Boundaries"
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"Image saved to: {output_image_path}")
    print(f"Configuration - Pressure interval: 2hPa, Gust max: {actual_max_gust:.0f}m/s")
    print(f"Boundaries: {boundary_info}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024072400'
    
    draw_mslp_and_gust(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_Surface_MSLP_Gust_Wind_{date_str}.png', 
        hour=0,
        lon_min=100, 
        lon_max=140, 
        lat_min=15, 
        lat_max=35,
        download_data=True,
        use_china_boundaries=True
    )