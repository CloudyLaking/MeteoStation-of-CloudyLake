import numpy as np
from scipy.ndimage import gaussian_filter
import cartopy.crs as ccrs

def get_height_contour_interval(pressure_level):
    """根据气压层返回相应的等高线间距"""
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

def add_height_contour(ax, lon_grid, lat_grid, geopotential_data, 
                       pressure_level, smooth_sigma=1, interval=None):
    """
    叠加位势高度等值线层
    """
    # 转换为位势高度 (z / g)
    height_gpm = geopotential_data / 9.80665
    
    if smooth_sigma > 0:
        height_gpm = gaussian_filter(height_gpm, sigma=smooth_sigma)
        
    if interval is None:
        interval = get_height_contour_interval(pressure_level)
    
    # 确定等高线的范围
    min_val = int(np.floor(np.nanmin(height_gpm)/10)*10)
    max_val = int(np.ceil(np.nanmax(height_gpm)/10)*10)
    levels = np.arange(min_val, max_val + interval, interval)
    
    # 绘制等值线
    contour = ax.contour(lon_grid, lat_grid, height_gpm, levels=levels, 
                         colors='black', linewidths=1.5, transform=ccrs.PlateCarree())
    
    # 添加标签
    ax.clabel(contour, inline=True, fmt='%d', fontsize=10, colors='black')

def add_slp_contour(ax, lon_grid, lat_grid, slp_data, smooth_sigma=1, interval=2.5):
    """
    叠加海平面气压 (SLP) 等值线层 (间隔通常为 2.5 或 5 hPa)
    """
    # 将气压转换为 hPa (1 hPa = 100 Pa)
    slp_hpa = slp_data / 100.0
    
    if smooth_sigma > 0:
        slp_hpa = gaussian_filter(slp_hpa, sigma=smooth_sigma)
        
    min_val = int(np.floor(np.nanmin(slp_hpa) / interval) * interval)
    max_val = int(np.ceil(np.nanmax(slp_hpa) / interval) * interval)
    levels = np.arange(min_val, max_val + interval, interval)
    
    contour = ax.contour(lon_grid, lat_grid, slp_hpa, levels=levels, 
                         colors='black', linewidths=1.5, transform=ccrs.PlateCarree())
    
    ax.clabel(contour, inline=True, fmt='%d', fontsize=10, colors='black')

def add_contour_generic(ax, lon_grid, lat_grid, data, var_name, smooth_sigma=1):
    """
    通用自适应等值线绘制方法，用于未做专门化适配的其他ERA5参数
    """
    if smooth_sigma > 0:
        data = gaussian_filter(data, sigma=smooth_sigma)
        
    min_val, max_val = np.nanmin(data), np.nanmax(data)
    
    # 根据自适应范围划分大约 12 到 15 层等值线
    # ticker.MaxNLocator 会自动找出比较工整的间隔
    import matplotlib.ticker as ticker
    locator = ticker.MaxNLocator(nbins=12)
    levels = locator.tick_values(min_val, max_val)
    
    contour = ax.contour(lon_grid, lat_grid, data, levels=levels, 
                         colors='black', linewidths=1.2, alpha=0.8, transform=ccrs.PlateCarree())
    
    # 如果数值过大过小，采用自适应格式，否则采用1位小数
    if max_val - min_val > 100 or np.abs(np.mean(data)) > 100:
        fmt = '%d'
    elif max_val - min_val < 0.1:
        fmt = '%.3f'
    else:
        fmt = '%.1f'

    ax.clabel(contour, inline=True, fmt=fmt, fontsize=9, colors='black')