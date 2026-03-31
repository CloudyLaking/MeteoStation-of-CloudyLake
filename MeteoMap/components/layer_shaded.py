import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter
import cartopy.crs as ccrs

# ================= 通用辅助: 建立完全还原的ColorMap =================
def _build_exact_colormap(colors, points, min_val, max_val, name='custom_cmap'):
    color_positions = []
    valid_colors = []
    for i, pt in enumerate(points):
        if i < len(colors):
            pos = (pt - min_val) / (max_val - min_val)
            pos = max(0, min(1, pos))
            color_positions.append(pos)
            valid_colors.append(colors[i])
            
    sorted_pairs = sorted(zip(color_positions, valid_colors))
    color_positions, valid_colors = zip(*sorted_pairs)
    color_positions, valid_colors = list(color_positions), list(valid_colors)
    
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
            
    return LinearSegmentedColormap.from_list(name, list(zip(unique_positions, unique_colors)), N=256)

def _add_right_colorbar(ax, contourf, tick_interval, min_val, max_val, label, ticks_list=None):
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='5%', pad=0.1, axes_class=plt.Axes)
    
    if ticks_list is not None:
        colorbar_ticks = ticks_list
    else:
        tick_start = int(min_val // tick_interval) * tick_interval
        tick_end = int(max_val // tick_interval) * tick_interval
        colorbar_ticks = list(range(tick_start, tick_end + 1, tick_interval))
    
    plt.colorbar(contourf, cax=cax, orientation='vertical', 
                 ticks=colorbar_ticks, label=label)

# ================= K-Index ================= 
def calculate_k_index(t500, t700, t850, rh500, rh700, rh850):
    def magnus_formula(temp_k, rh_percent):
        temp_c = temp_k - 273.15
        a, b = 17.27, 237.7
        es = 6.112 * np.exp((a * temp_c) / (b + temp_c))
        e = es * rh_percent / 100.0
        ln_ratio = np.log(e / 6.112)
        return (b * ln_ratio) / (a - ln_ratio)
    
    td850 = magnus_formula(t850, rh850)
    td700 = magnus_formula(t700, rh700)
    t850_c, t700_c, t500_c = t850 - 273.15, t700 - 273.15, t500 - 273.15
    return (t850_c - t500_c) + td850 - (t700_c - td700)

def add_shaded_kindex(ax, fig, lon_grid, lat_grid, k_index_data, smooth_sigma=1):
    if smooth_sigma > 0:
        k_index_data = gaussian_filter(k_index_data, sigma=smooth_sigma)
        
    colors = ["#FFFFFF", "#FFF2FF", "#E0BEFF", "#FFEA00"]
    points = [0, 15, 30, 55]
    min_val, max_val = 0, 55
    
    cmap = _build_exact_colormap(colors, points, min_val, max_val, 'kindex_cmap')
    norm = Normalize(vmin=min_val, vmax=max_val)
    levels = np.linspace(min_val, max_val, 100)
    
    cf = ax.contourf(lon_grid, lat_grid, k_index_data, levels=levels, 
                     cmap=cmap, norm=norm, transform=ccrs.PlateCarree(), 
                     alpha=0.8, extend='max')
                     
    _add_right_colorbar(ax, cf, tick_interval=5, min_val=min_val, max_val=max_val, label='K-index (°C)')
    
    return np.min(k_index_data), np.max(k_index_data), np.mean(k_index_data), "K-index", "°C"

# ================= CAPE ================= 
def add_shaded_cape(ax, fig, lon_grid, lat_grid, cape_data, smooth_sigma=1):
    if smooth_sigma > 0:
        cape_data = gaussian_filter(cape_data, sigma=smooth_sigma)
        
    colors = ["#FFFFFF", "#FFFFFF", "#FFB0B0", "#FF6666", "#FF0000", "#FF9900", "#FFEA00"]
    points = [0, 500, 1000, 2000, 3000, 4000, 5000]
    min_val, max_val = 0, 5000
    
    cmap = _build_exact_colormap(colors, points, min_val, max_val, 'cape_cmap')
    norm = Normalize(vmin=min_val, vmax=max_val)
    levels = np.linspace(min_val, max_val, 100)
    
    cf = ax.contourf(lon_grid, lat_grid, cape_data, levels=levels, 
                     cmap=cmap, norm=norm, transform=ccrs.PlateCarree(), 
                     alpha=0.8, extend='max')
                     
    _add_right_colorbar(ax, cf, tick_interval=500, min_val=min_val, max_val=max_val, label='CAPE (J/kg)')
    
    return np.min(cape_data), np.max(cape_data), np.mean(cape_data), "CAPE", "J/kg"


# ================= Temperature ================= 
def add_shaded_temp(ax, fig, lon_grid, lat_grid, temp_data, level_tag='2m', smooth_sigma=1):
    temp_c = temp_data - 273.15 if np.nanmax(temp_data) > 100 else temp_data
    if smooth_sigma > 0:
        temp_c = gaussian_filter(temp_c, sigma=smooth_sigma)

    colors = [
        "#B3B0B0",  # -60
        "#7EE1E1",  # -50
        "#8EB2EB",  # -40
        "#C881E6",  # -30
        "#87A3FC",  # -20
        '#87CEEB',  # -10
        '#FFFFFF',  # 0
        "#52FF52",  # 10
        '#FFFF00',  # 20
        '#FF0000',  # 30
        '#C71585',  # 35
        '#8A2BE2',  # 40
        '#E6E6FA',  # 45
        '#FFFFFF'   # 50
    ]
    points = [-60, -50, -40, -30, -20, -10, 0, 10, 20, 30, 35, 40, 45, 50]
    min_val, max_val = -60, 50
    
    cmap = _build_exact_colormap(colors, points, min_val, max_val, 'temp_cmap')
    norm = Normalize(vmin=min_val, vmax=max_val)
    levels = np.linspace(min_val, max_val, 100)
    
    cf = ax.contourf(lon_grid, lat_grid, temp_c, levels=levels, cmap=cmap, norm=norm, 
                     alpha=0.8, extend='both', transform=ccrs.PlateCarree())
    
    _add_right_colorbar(ax, cf, tick_interval=10, min_val=min_val, max_val=max_val, label=f'Temperature ({level_tag}) (°C)', ticks_list=points)
    
    return np.min(temp_c), np.max(temp_c), np.mean(temp_c), f"Temp ({level_tag})", "°C"


# ================= Wind Speed ================= 
def add_shaded_wind_speed(ax, fig, lon_grid, lat_grid, u_data, v_data, level_tag='10m', smooth_sigma=1):
    speed = np.sqrt(u_data**2 + v_data**2)
    if smooth_sigma > 0:
        speed = gaussian_filter(speed, sigma=smooth_sigma)
        
    is_surface = isinstance(level_tag, str) and level_tag.endswith('m')
    
    if is_surface:
        # 地面风速 (如 10m)
        colors = [
            '#FFFFFF', '#E0E0E0', '#87CEEB', '#00BFFF', '#00FF00', 
            '#FFFF00', '#FFA500', '#FF4500', '#FF0000', '#DC143C', 
            '#8B0000', '#4B0082', '#9400D3', '#FF00FF'
        ]
        points = [i * 5 for i in range(14)] # 0, 5, ..., 65
        max_val = 70
    else:
        # 高空风速 (如 850, 500)
        try:
            pressure = int(level_tag)
        except ValueError:
            pressure = 850
            
        colors = [
            '#FFFFFF', '#D1D1D1', '#188FD8', '#34D259', '#F1B04D', 
            '#FF6200', '#FF0000', '#9C2EBA', '#FF00FF', '#EA00FF'
        ]
        if pressure >= 750:
            points = [i * 5 for i in range(10)]
            max_val = 56
        elif pressure >= 400:
            points = [i * 6 for i in range(10)]
            max_val = 68
        elif pressure >= 200:
            points = [i * 8 for i in range(10)]
            max_val = 84
        else:
            points = [i * 10 for i in range(10)]
            max_val = 104

    min_val = 0
    
    # 根据实际最大值自适应显示范围，但遵循原有上限规则
    actual_max_wind = np.max(speed)
    display_max = int(min(max_val, max(max_val * 0.7, np.ceil(actual_max_wind / 5) * 5)))
    
    # 动态构建结束于 display_max 的 cmap，并用 set_over 确保顶部延伸色的平滑
    cmap = _build_exact_colormap(colors, points, min_val, display_max, 'wind_speed_cmap')
    cmap.set_over(cmap(1.0))
    norm = Normalize(vmin=min_val, vmax=display_max)
    
    levels = np.linspace(min_val, display_max, 100)
    
    cf = ax.contourf(lon_grid, lat_grid, speed, levels=levels, cmap=cmap, norm=norm, 
                     alpha=0.8, extend='max', transform=ccrs.PlateCarree())
    
    valid_ticks = [p for p in points if p <= display_max]
    _add_right_colorbar(ax, cf, tick_interval=5, min_val=min_val, max_val=display_max, label=f'Wind Speed ({level_tag}) (m/s)', ticks_list=valid_ticks)
    
    return np.min(speed), np.max(speed), np.mean(speed), f"Wind Speed ({level_tag})", "m/s"

# ================= Generic (通用自适应填色) =================
def add_shaded_generic(ax, fig, lon_grid, lat_grid, data, var_name, smooth_sigma=1):
    """
    通用自适应填色方法，用于未做专门化适配的其他ERA5参数（如相对湿度、散度、涡度等）
    """
    if smooth_sigma > 0:
        data = gaussian_filter(data, sigma=smooth_sigma)
        
    cmap = plt.get_cmap('Spectral_r') 
    min_val, max_val = np.nanmin(data), np.nanmax(data)
    
    # 强制让过于轻微的波动有更好的视觉展示，避免全图纯色
    if max_val == min_val:
        min_val -= 1
        max_val += 1
        
    levels = np.linspace(min_val, max_val, 100)
    norm = Normalize(vmin=min_val, vmax=max_val)
    
    cf = ax.contourf(lon_grid, lat_grid, data, levels=levels, cmap=cmap, norm=norm, 
                     alpha=0.8, extend='both', transform=ccrs.PlateCarree())
    
    # 自适应Colorbar间隔
    range_span = max_val - min_val
    if range_span > 100:
        tick_interval = 20
    elif range_span > 20:
        tick_interval = 5
    elif range_span > 5:
        tick_interval = 1
    else:
        tick_interval = range_span / 5.0
        
    label_text = str(var_name).replace('_', ' ').title()
    import matplotlib.ticker as ticker
    locator = ticker.MaxNLocator(nbins=6)
    ticks_list = locator.tick_values(min_val, max_val)

    _add_right_colorbar(ax, cf, tick_interval=tick_interval, min_val=min_val, max_val=max_val, label=label_text, ticks_list=ticks_list)
    
    return np.min(data), np.max(data), np.mean(data), label_text, ""
