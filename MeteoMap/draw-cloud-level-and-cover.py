import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter
import xarray as xr
import os
import datetime as dt
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
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

def classify_cloud_level(low_cloud, medium_cloud, high_cloud):
    """
    根据低云、中云、高云覆盖度分类云层类型
    
    参数:
    low_cloud, medium_cloud, high_cloud: 低云、中云、高云覆盖度 (0-1)
    
    返回:
    cloud_level: 云层类型分类 (0-5)
    0: 晴空 (总云量 < 10%)
    1: 低云为主 (低云 > 中云 且 低云 > 高云)
    2: 中云为主 (中云 > 低云 且 中云 > 高云)
    3: 高云为主 (高云 > 低云 且 高云 > 中云)
    4: 混合云层 (两种或以上云层覆盖度接近)
    5: 深厚云系 (总云量 > 80%)
    """
    # 计算总云量
    total_cloud = low_cloud + medium_cloud + high_cloud
    # 限制总云量在0-1之间（避免重复计算）
    total_cloud = np.minimum(total_cloud, 1.0)
    
    cloud_level = np.zeros_like(total_cloud)
    
    # 分类逻辑
    # 1. 晴空：总云量 < 10%
    clear_sky = total_cloud < 0.1
    cloud_level[clear_sky] = 0
    
    # 2. 深厚云系：总云量 > 80%
    thick_cloud = total_cloud > 0.8
    cloud_level[thick_cloud] = 5
    
    # 3. 对于中等云量区域，按主导云层分类
    moderate_cloud = (total_cloud >= 0.1) & (total_cloud <= 0.8)
    
    # 在中等云量区域内进一步分类
    low_dominant = moderate_cloud & (low_cloud > medium_cloud) & (low_cloud > high_cloud)
    medium_dominant = moderate_cloud & (medium_cloud > low_cloud) & (medium_cloud > high_cloud)
    high_dominant = moderate_cloud & (high_cloud > low_cloud) & (high_cloud > medium_cloud)
    
    cloud_level[low_dominant] = 1
    cloud_level[medium_dominant] = 2
    cloud_level[high_dominant] = 3
    
    # 4. 混合云层：没有明显主导云层的情况
    mixed_cloud = moderate_cloud & ~(low_dominant | medium_dominant | high_dominant)
    cloud_level[mixed_cloud] = 4
    
    return cloud_level.astype(int)

def get_cloud_level_color_scheme():
    """
    返回云层类型配色方案
    """
    colors = [
        "#87CEEB",   # 0: 晴空 - 天蓝色
        "#90EE90",   # 1: 低云为主 - 浅绿色
        "#FFD700",   # 2: 中云为主 - 金黄色
        "#FFA500",   # 3: 高云为主 - 橙色
        "#FF6347",   # 4: 混合云层 - 番茄红
        "#8B0000"    # 5: 深厚云系 - 暗红色
    ]
    
    labels = [
        "Clear Sky (<10%)",
        "Low Cloud Dominant", 
        "Medium Cloud Dominant",
        "High Cloud Dominant",
        "Mixed Cloud Layers",
        "Thick Cloud System (>80%)"
    ]
    
    return colors, labels

def draw_cloud_analysis(date_str='2024072400', 
                       output_image_path='Output/MeteoMap/cloud_analysis.png',
                       hour=0, lon_min=80, lon_max=140, lat_min=20, lat_max=55,
                       data_source='ERA5', smooth_sigma=1, download_data=True,
                       use_china_boundaries=True,
                       # 总云量网格设置
                       show_total_cloud_grid=True,
                       grid_interval=5,  # 网格间隔（经纬度度数）- 调整为5度以增加密度
                       grid_fontsize=8):
    """
    绘制云层分析图：云层类型填充 + 总云量数据网格显示
    
    参数:
    date_str : str - 日期时间字符串 (YYYYMMDDHH)
    show_total_cloud_grid : bool - 是否显示总云量网格数据
    grid_interval : int - 网格间隔（经纬度度数）
    grid_fontsize : int - 网格文字大小
    """
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    if download_data:
        print(f"正在下载 {date_str} 的ERA5云量数据...")
        
        # 下载地面云量数据
        surface_ds = download_era5_surface_data(
            date=date_str,
            variables=[
                'low_cloud_cover',
                'medium_cloud_cover', 
                'high_cloud_cover',
                'total_cloud_cover'
            ],
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max
        )
        
        if surface_ds is None:
            print("云量数据下载失败，退出...")
            return
        
        # 提取坐标
        lon = surface_ds.coords['longitude'].values
        lat = surface_ds.coords['latitude'].values
        
        # 提取云量数据
        low_cloud = surface_ds['lcc'].values.squeeze()
        medium_cloud = surface_ds['mcc'].values.squeeze()
        high_cloud = surface_ds['hcc'].values.squeeze()
        total_cloud = surface_ds['tcc'].values.squeeze()
        
        print("云量数据下载完成")
        
    else:
        print("错误: 暂不支持从文件加载云量数据")
        return

    # 创建网格
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    
    # 应用平滑
    if smooth_sigma > 0:
        low_cloud_smooth = gaussian_filter(low_cloud, sigma=smooth_sigma)
        medium_cloud_smooth = gaussian_filter(medium_cloud, sigma=smooth_sigma)
        high_cloud_smooth = gaussian_filter(high_cloud, sigma=smooth_sigma)
        total_cloud_smooth = gaussian_filter(total_cloud, sigma=smooth_sigma)
    else:
        low_cloud_smooth = low_cloud
        medium_cloud_smooth = medium_cloud
        high_cloud_smooth = high_cloud
        total_cloud_smooth = total_cloud
    
    # 分类云层类型
    print("正在分类云层类型...")
    cloud_level = classify_cloud_level(low_cloud_smooth, medium_cloud_smooth, high_cloud_smooth)
    
    # 计算统计信息
    total_cloud_percent = total_cloud_smooth * 100  # 转换为百分比
    min_total_cloud = np.min(total_cloud_percent)
    max_total_cloud = np.max(total_cloud_percent)
    mean_total_cloud = np.mean(total_cloud_percent)
    
    # 统计各云层类型的面积占比
    unique_levels, counts = np.unique(cloud_level, return_counts=True)
    total_points = cloud_level.size
    level_percentages = {level: count/total_points*100 for level, count in zip(unique_levels, counts)}
    
    print(f"总云量统计: {min_total_cloud:.1f}%-{max_total_cloud:.1f}% (平均: {mean_total_cloud:.1f}%)")
    print("云层类型分布:")
    colors, labels = get_cloud_level_color_scheme()
    for level in range(6):
        if level in level_percentages:
            print(f"  {labels[level]}: {level_percentages[level]:.1f}%")
    
    # 设置字体
    try:
        import matplotlib.font_manager as font_manager
        font_manager.fontManager.addfont(r'MeteoStation\MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']
    except:
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图形
    fig = plt.figure(figsize=(16, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], crs=ccrs.PlateCarree())
    
    # 绘制云层类型填充（底层）
    print("正在绘制云层类型填充...")
    colors, labels = get_cloud_level_color_scheme()
    
    # 创建离散色彩映射
    cmap = ListedColormap(colors)
    
    # 绘制云层类型
    cloud_contourf = ax.contourf(
        lon_grid, lat_grid, cloud_level,
        levels=np.arange(-0.5, 6.5, 1),  # 离散级别
        cmap=cmap,
        transform=ccrs.PlateCarree(),
        alpha=0.8
    )
    
    # 显示总云量网格数据（顶层）
    if show_total_cloud_grid:
        print("正在添加总云量网格数据...")
        
        # 创建网格点
        grid_lons = np.arange(lon.min(), lon.max() + grid_interval, grid_interval)
        grid_lats = np.arange(lat.min(), lat.max() + grid_interval, grid_interval)
        
        # 在每个网格点显示总云量百分比
        for grid_lon in grid_lons:
            for grid_lat in grid_lats:
                # 确保网格点在数据范围内
                if (lon.min() <= grid_lon <= lon.max() and 
                    lat.min() <= grid_lat <= lat.max()):
                    
                    # 找到最近的数据点
                    lon_idx = np.argmin(np.abs(lon - grid_lon))
                    lat_idx = np.argmin(np.abs(lat - grid_lat))
                    
                    # 获取该点的总云量百分比
                    cloud_percent = total_cloud_percent[lat_idx, lon_idx]
                    
                    # 显示数值 - 去掉白色背景
                    ax.text(grid_lon, grid_lat, f'{cloud_percent:.0f}',
                           transform=ccrs.PlateCarree(),
                           ha='center', va='center',
                           fontsize=grid_fontsize,
                           color='black',
                           weight='bold')
    
    # 添加海岸线和边界
    try:
        ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
        
        if use_china_boundaries:
            china_boundaries_added = add_china_boundaries(
                ax, 
                lon_min=lon.min(), 
                lon_max=lon.max(),
                lat_min=lat.min(), 
                lat_max=lat.max()
            )
            
            if not china_boundaries_added:
                ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.8)
        else:
            ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.8)
        
    except Exception as e:
        print(f"添加边界时出错: {e}")
        ax.coastlines(resolution='50m')
        ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.8)
    
    # 添加网格线
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(lon.min()), 
                                           np.ceil(lon.max()) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(lat.min()), 
                                           np.ceil(lat.max()) + 1, 5))

    # 创建云层类型图例
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    # 创建色彩条
    cbar = plt.colorbar(cloud_contourf, cax=cax, orientation='vertical',
                       ticks=range(6), label='Cloud Level Classification')
    cbar.ax.set_yticklabels(labels)
    
    # 格式化日期以显示
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        date_display = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        date_display = date_str
    
    # 构建标题
    main_title = f'{data_source} Cloud Level Classification and Total Cloud Cover'
    
    if hour > 0:
        time_title = f'{date_display} +{hour}h'
    else:
        time_title = date_display
    
    # 左侧标题
    ax.text(0.01, 1.025, main_title+'\n'+time_title, transform=ax.transAxes, 
            ha='left', va='bottom', 
            fontsize=14, fontweight='bold', color='black')
    
    # 右侧统计信息
    stats_text = f'Total Cloud Cover: {min_total_cloud:.1f}%-{max_total_cloud:.1f}%\n'
    stats_text += f'Average: {mean_total_cloud:.1f}%'
    if show_total_cloud_grid:
        stats_text += f'\nGrid shows total cloud %'
    
    ax.text(0.99, 1.025, stats_text, transform=ax.transAxes, 
            ha='right', va='bottom', 
            fontsize=10, color='black')
    
    # 保存图像
    plt.savefig(output_image_path, bbox_inches='tight', dpi=300)
    print(f"云层分析图已保存: {output_image_path}")
    plt.close()

if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs('Output/MeteoMap', exist_ok=True)
    
    date_str = '2024072400'
    
    draw_cloud_analysis(
        date_str=date_str, 
        output_image_path=f'Output/MeteoMap/ERA5_CloudLevel_TotalCover_{date_str}.png', 
        hour=0,
        lon_min=80, 
        lon_max=140, 
        lat_min=20, 
        lat_max=55,
        download_data=True,
        use_china_boundaries=True,
        show_total_cloud_grid=True,
        grid_interval=1, 
        grid_fontsize=8
    )