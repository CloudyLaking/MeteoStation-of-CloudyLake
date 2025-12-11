# 画出1951-1980年与1991-2020年平均的1月和7月200hPa的位势高度场和风场进行对比，包含差值图
# MeteoMap-ERA5average/draw-level-wind-and-geopotential-height-average-compare.py

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter
import xarray as xr
import os
import cdsapi
from matplotlib.colors import LinearSegmentedColormap
print("import completed")

def download_era5_monthly_climatology(pressure_level, variables, years_range=(1979, 2024)):
    """
    下载ERA5月平均再分析数据用于气候态计算
    
    参数:
    pressure_level : int - 气压层 (hPa)
    variables : list - 要下载的变量列表
    years_range : tuple - 年份范围 (起始年, 结束年)
    
    返回:
    str - 下载的文件路径
    """
    try:
        # 初始化CDS API客户端
        c = cdsapi.Client()
        
        # 生成年份列表
        years = [str(year) for year in range(years_range[0], years_range[1] + 1)]
        
        # 创建data文件夹
        data_dir = 'Output/MeteoMap-Average/data'
        os.makedirs(data_dir, exist_ok=True)
        
        # 定义输出文件名（保存到data文件夹）
        output_file = os.path.join(data_dir, f'era5_monthly_{pressure_level}hPa_{years_range[0]}_{years_range[1]}.nc')
        
        # 检查文件是否已存在
        if os.path.exists(output_file):
            print(f"文件 {output_file} 已存在，跳过下载")
            return output_file
            
        print(f"正在下载 {pressure_level}hPa {years_range[0]}-{years_range[1]} 月平均数据...")
        
        # 下载ERA5月平均数据
        c.retrieve(
            'reanalysis-era5-pressure-levels-monthly-means',
            {
                'product_type': 'monthly_averaged_reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'pressure_level': str(pressure_level),
                'year': years,
                'month': ['01', '07'],  # 1月和7月
                'time': '00:00',
            },
            output_file
        )
        
        print(f"数据已保存到: {output_file}")
        return output_file
            
    except Exception as e:
        print(f"下载ERA5数据时出错: {e}")
        return None

def calculate_monthly_climatology(file_path, pressure_level):
    """
    计算1月和7月多年平均气候态
    
    参数:
    file_path : str - 数据文件路径
    pressure_level : int - 气压层
    
    返回:
    tuple - (january_data, july_data) 包含位势高度和风场的DataArrays
    """
    try:
        # 使用dask并行读取数据以提高效率
        ds = xr.open_dataset(file_path, chunks={'valid_time': 'auto'})
        
        # 转换坐标系统 (0-360 to -180-180)
        ds = ds.assign_coords(
            longitude=(((ds.longitude + 180) % 360) - 180)
        ).sortby('longitude')
        
        print(f"数据维度: {dict(ds.dims)}")
        print(f"可用变量: {list(ds.data_vars)}")
        
        # 转换位势为位势高度
        ds['z'] = ds['z'] / 9.80665
        
        # 筛选出1月和7月的数据
        ds_filtered = ds.where(ds['valid_time'].dt.month.isin([1, 7]), drop=True)
        
        # 按月份分组并计算多年月平均气候态
        climatology = ds_filtered.groupby('valid_time.month').mean('valid_time')
        
        # 提取1月和7月的数据
        january_ds = climatology.sel(month=1)
        july_ds = climatology.sel(month=7)
        
        # 创建返回数据结构
        january_data = {
            'height': january_ds['z'],
            'u_wind': january_ds['u'],
            'v_wind': january_ds['v']
        }
        
        july_data = {
            'height': july_ds['z'],
            'u_wind': july_ds['u'],
            'v_wind': july_ds['v']
        }
        
        print(f"{pressure_level}hPa 月份气候态计算完成")
        return january_data, july_data
        
    except Exception as e:
        print(f"计算月份气候态时出错: {e}")
        return None, None

def get_wind_color_scheme(pressure_level):
    """
    根据气压层返回风速配色方案
    """
    if pressure_level == 200:
        # 200hPa风速配色
        wind_speed_colors = [
            '#FFFFFF', '#E6F7FF', '#BAE7FF', '#91D5FF', '#69C0FF', 
            '#40A9FF', '#1890FF', '#096DD9', '#0050B3', '#003A8C',
            '#002766', '#FF7F00', '#FF4500', '#FF0000', '#B22222'
        ]
        wind_speed_levels = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140]
        max_wind_display = 140
    else:
        # 其他层级默认配色
        wind_speed_colors = [
            '#FFFFFF', '#E6F7FF', '#BAE7FF', '#91D5FF', '#69C0FF', 
            '#40A9FF', '#1890FF', '#096DD9', '#0050B3', '#003A8C'
        ]
        wind_speed_levels = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
        max_wind_display = 90
    
    return wind_speed_colors, wind_speed_levels, max_wind_display

def get_difference_color_scheme():
    """
    返回差值图的配色方案
    """
    # 使用蓝-白-红配色表示负-零-正差值
    colors = [
        '#0000FF', '#4169E1', '#87CEEB', '#B0E0E6', '#E0F6FF',
        '#FFFFFF',
        '#FFE0E0', '#FFB6C1', '#FFA07A', '#FF6347', '#FF0000'
    ]
    return colors

def draw_period_comparison(period1_data, period2_data, pressure_level, output_path,
                          period1_range, period2_range, smooth_sigma=1.5):
    """
    绘制两个时期的1月和7月气候态位势高度场和风场对比，包含差值图
    
    参数:
    period1_data, period2_data : tuple - 两个时期的(january_data, july_data)
    pressure_level : int - 气压层
    output_path : str - 输出图像路径
    period1_range, period2_range : tuple - 两个时期的年份范围
    smooth_sigma : float - 高斯平滑参数
    """
    
    # 设置字体
    try:
        import matplotlib.font_manager as font_manager
        font_manager.fontManager.addfont(r'MeteoStation\MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']
    except:
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建图形 - 2x3子图（两行三列）
    fig = plt.figure(figsize=(20, 8))
    
    # 获取配色方案
    wind_speed_colors, wind_speed_levels, max_wind_display = get_wind_color_scheme(pressure_level)
    height_interval = 120
    
    # 创建风速颜色映射
    n_colors = min(len(wind_speed_colors), len(wind_speed_levels))
    colors_normalized = wind_speed_colors[:n_colors]
    color_positions = np.linspace(0, 1, n_colors)
    cmap = LinearSegmentedColormap.from_list(
        'wind_speed_cmap', 
        list(zip(color_positions, colors_normalized))
    )
    
    # 创建差值配色方案
    diff_colors = get_difference_color_scheme()
    diff_cmap = LinearSegmentedColormap.from_list('difference_cmap', diff_colors)
    
    # 准备数据结构
    periods = [
        (f'{period1_range[0]}-{period1_range[1]}', period1_data),
        (f'{period2_range[0]}-{period2_range[1]}', period2_data)
    ]
    
    months = ['January', 'July']
    
    # 预计算所有数据以确定统一范围
    all_wind_speeds = []
    all_heights = []
    
    for period_name, (jan_data, jul_data) in periods:
        for month_data in [jan_data, jul_data]:
            height = month_data['height'].values.squeeze()
            u_wind = month_data['u_wind'].values.squeeze()
            v_wind = month_data['v_wind'].values.squeeze()
            wind_speed = np.sqrt(u_wind**2 + v_wind**2)
            
            all_wind_speeds.append(wind_speed)
            all_heights.append(height)
    
    # 计算全局最大值用于统一色标
    global_max_wind = np.max([np.max(ws) for ws in all_wind_speeds])
    global_min_height = np.min([np.min(h) for h in all_heights])
    global_max_height = np.max([np.max(h) for h in all_heights])
    
    # 调整风速显示范围
    actual_max_wind = min(max_wind_display, max(max_wind_display * 0.7, np.ceil(global_max_wind / 10) * 10))
    
    # 计算等高线级别
    height_min_round = int(global_min_height // height_interval) * height_interval
    height_max_round = int(global_max_height // height_interval + 1) * height_interval
    height_levels = np.arange(height_min_round, height_max_round + height_interval, height_interval)
    
    # 计算差值数据
    jan_diff = {}
    jul_diff = {}
    
    # 1月差值
    jan_diff['height'] = period2_data[0]['height'] - period1_data[0]['height']
    jan_diff['u_wind'] = period2_data[0]['u_wind'] - period1_data[0]['u_wind']
    jan_diff['v_wind'] = period2_data[0]['v_wind'] - period1_data[0]['v_wind']
    
    # 7月差值
    jul_diff['height'] = period2_data[1]['height'] - period1_data[1]['height']
    jul_diff['u_wind'] = period2_data[1]['u_wind'] - period1_data[1]['u_wind']
    jul_diff['v_wind'] = period2_data[1]['v_wind'] - period1_data[1]['v_wind']
    
    # 计算差值范围
    jan_height_diff = jan_diff['height'].values.squeeze()
    jul_height_diff = jul_diff['height'].values.squeeze()
    max_height_diff = max(np.abs(jan_height_diff).max(), np.abs(jul_height_diff).max())
    
    # 绘制六个子图 (2行3列)
    plot_index = 0
    
    # 第一行：1月数据
    for period_idx, (period_name, (jan_data, jul_data)) in enumerate(periods):
        plot_index += 1
        
        # 创建子图
        ax = plt.subplot(2, 3, plot_index, projection=ccrs.PlateCarree())
        
        # 使用1月数据
        month_data = jan_data
        height = month_data['height'].values.squeeze()
        u_wind = month_data['u_wind'].values.squeeze()
        v_wind = month_data['v_wind'].values.squeeze()
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        
        # 获取坐标
        lon = month_data['height'].coords['longitude'].values
        lat = month_data['height'].coords['latitude'].values
        lon_grid, lat_grid = np.meshgrid(lon, lat)
        
        # 平滑位势高度数据
        height_smooth = gaussian_filter(height, sigma=smooth_sigma)
        
        # 设置全球范围
        ax.set_global()
        
        # 绘制风速填充等高线
        contourf = ax.contourf(
            lon_grid, lat_grid, wind_speed, 
            levels=np.linspace(0, actual_max_wind, 100), 
            cmap=cmap, 
            transform=ccrs.PlateCarree(), 
            alpha=0.8, 
            extend='max'
        )
        
        # 添加位势高度等高线
        contour = ax.contour(
            lon_grid, lat_grid, height_smooth, 
            levels=height_levels, 
            colors='black', 
            linewidths=0.6,
            alpha=0.4
        )
        
        # 添加等高线标签
        ax.clabel(contour, inline=True, fontsize=8, fmt='%d')
        
        # 绘制风标 - 增加跳跃因子减少密度
        skip_factor = 50
        barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
        ax.barbs(
            lon_grid[barb_slice], lat_grid[barb_slice],
            u_wind[barb_slice], v_wind[barb_slice],
            length=4, pivot='middle', color='black', linewidth=0.7
        )
        
        # 添加海岸线
        ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
        
        # 添加网格线
        gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
        gl.top_labels = False
        gl.right_labels = False
        
        # 只在左边子图显示左侧标签，只在下方子图显示底部标签
        if plot_index not in [1, 4]:  # 不是左边的子图
            gl.left_labels = False
        if plot_index not in [4, 5, 6]:  # 不是底部的子图
            gl.bottom_labels = False
        
        # 计算当前数据的统计信息
        data_max_wind = np.max(wind_speed)
        data_min_height = np.min(height_smooth)
        data_max_height = np.max(height_smooth)
        
        # 设置子图标题
        ax.set_title(f'January {pressure_level}hPa ({period_name})\n'
                    f'Height: {data_min_height:.0f}-{data_max_height:.0f}gpm, '
                    f'Max Wind: {data_max_wind:.1f}m/s', 
                    fontsize=12, fontweight='bold', pad=15)
    
    # 1月差值图
    plot_index += 1
    ax = plt.subplot(2, 3, plot_index, projection=ccrs.PlateCarree())
    
    # 获取差值数据
    height_diff = jan_height_diff
    u_diff = jan_diff['u_wind'].values.squeeze()
    v_diff = jan_diff['v_wind'].values.squeeze()
    
    # 平滑差值数据
    height_diff_smooth = gaussian_filter(height_diff, sigma=smooth_sigma)
    
    # 设置全球范围
    ax.set_global()
    
    # 绘制高度差值填充等高线
    diff_levels = np.linspace(-max_height_diff, max_height_diff, 21)
    contourf_diff = ax.contourf(
        lon_grid, lat_grid, height_diff, 
        levels=diff_levels, 
        cmap=diff_cmap, 
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='both'
    )
    
    # 添加零线
    ax.contour(
        lon_grid, lat_grid, height_diff_smooth,
        levels=[0], 
        colors='black', 
        linewidths=1.5,
        linestyles='-'
    )
    
    # 绘制风场差值的箭头
    skip_factor = 50
    barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    ax.barbs(
        lon_grid[barb_slice], lat_grid[barb_slice],
        u_diff[barb_slice], v_diff[barb_slice],
        length=4, pivot='middle', color='purple', linewidth=0.8
    )
    
    # 添加海岸线
    ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
    
    # 添加网格线
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False
    gl.left_labels = False
    gl.bottom_labels = False
    
    # 设置标题
    ax.set_title(f'January {pressure_level}hPa Difference\n'
                f'({period2_range[0]}-{period2_range[1]}) - ({period1_range[0]}-{period1_range[1]})', 
                fontsize=12, fontweight='bold', pad=15, color='purple')
    
    # 第二行：7月数据（重复上面的逻辑）
    for period_idx, (period_name, (jan_data, jul_data)) in enumerate(periods):
        plot_index += 1
        
        # 创建子图
        ax = plt.subplot(2, 3, plot_index, projection=ccrs.PlateCarree())
        
        # 使用7月数据
        month_data = jul_data
        height = month_data['height'].values.squeeze()
        u_wind = month_data['u_wind'].values.squeeze()
        v_wind = month_data['v_wind'].values.squeeze()
        wind_speed = np.sqrt(u_wind**2 + v_wind**2)
        
        # 获取坐标
        lon = month_data['height'].coords['longitude'].values
        lat = month_data['height'].coords['latitude'].values
        lon_grid, lat_grid = np.meshgrid(lon, lat)
        
        # 平滑位势高度数据
        height_smooth = gaussian_filter(height, sigma=smooth_sigma)
        
        # 设置全球范围
        ax.set_global()
        
        # 绘制风速填充等高线
        contourf = ax.contourf(
            lon_grid, lat_grid, wind_speed, 
            levels=np.linspace(0, actual_max_wind, 100), 
            cmap=cmap, 
            transform=ccrs.PlateCarree(), 
            alpha=0.8, 
            extend='max'
        )
        
        # 添加位势高度等高线
        contour = ax.contour(
            lon_grid, lat_grid, height_smooth, 
            levels=height_levels, 
            colors='black', 
            linewidths=0.6,
            alpha=0.4
        )
        
        # 添加等高线标签
        ax.clabel(contour, inline=True, fontsize=8, fmt='%d')
        
        # 绘制风标
        skip_factor = 50
        barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
        ax.barbs(
            lon_grid[barb_slice], lat_grid[barb_slice],
            u_wind[barb_slice], v_wind[barb_slice],
            length=4, pivot='middle', color='black', linewidth=0.7
        )
        
        # 添加海岸线
        ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
        
        # 添加网格线
        gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
        gl.top_labels = False
        gl.right_labels = False
        
        # 只在左边子图显示左侧标签，只在下方子图显示底部标签
        if plot_index not in [1, 4]:
            gl.left_labels = False
        if plot_index not in [4, 5, 6]:
            gl.bottom_labels = False
        
        # 计算当前数据的统计信息
        data_max_wind = np.max(wind_speed)
        data_min_height = np.min(height_smooth)
        data_max_height = np.max(height_smooth)
        
        # 设置子图标题
        ax.set_title(f'July {pressure_level}hPa ({period_name})\n'
                    f'Height: {data_min_height:.0f}-{data_max_height:.0f}gpm, '
                    f'Max Wind: {data_max_wind:.1f}m/s', 
                    fontsize=12, fontweight='bold', pad=15)
    
    # 7月差值图
    plot_index += 1
    ax = plt.subplot(2, 3, plot_index, projection=ccrs.PlateCarree())
    
    # 获取差值数据
    height_diff = jul_height_diff
    u_diff = jul_diff['u_wind'].values.squeeze()
    v_diff = jul_diff['v_wind'].values.squeeze()
    
    # 平滑差值数据
    height_diff_smooth = gaussian_filter(height_diff, sigma=smooth_sigma)
    
    # 设置全球范围
    ax.set_global()
    
    # 绘制高度差值填充等高线
    contourf_diff = ax.contourf(
        lon_grid, lat_grid, height_diff, 
        levels=diff_levels, 
        cmap=diff_cmap, 
        transform=ccrs.PlateCarree(), 
        alpha=0.8, 
        extend='both'
    )
    
    # 添加零线
    ax.contour(
        lon_grid, lat_grid, height_diff_smooth,
        levels=[0], 
        colors='black', 
        linewidths=1.5,
        linestyles='-'
    )
    
    # 绘制风场差值的箭头
    skip_factor = 50
    barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    ax.barbs(
        lon_grid[barb_slice], lat_grid[barb_slice],
        u_diff[barb_slice], v_diff[barb_slice],
        length=4, pivot='middle', color='purple', linewidth=0.8
    )
    
    # 添加海岸线
    ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
    
    # 添加网格线
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False
    gl.left_labels = False
    gl.bottom_labels = False
    
    # 设置标题
    ax.set_title(f'July {pressure_level}hPa Difference\n'
                f'({period2_range[0]}-{period2_range[1]}) - ({period1_range[0]}-{period1_range[1]})', 
                fontsize=12, fontweight='bold', pad=15, color='purple')
    
    # 添加总标题
    fig.suptitle(f'ERA5 {pressure_level}hPa Geopotential Height and Wind Climatology Comparison\n'
                f'{period1_range[0]}-{period1_range[1]} vs {period2_range[0]}-{period2_range[1]} with Differences', 
                fontsize=16, fontweight='bold', y=1.02)
    
    # 调整子图布局
    fig.subplots_adjust(bottom=0.15, top=0.88, left=0.05, right=0.95, wspace=0.1, hspace=0.3)
    
    # 添加风速色彩条
    cbar_ax1 = fig.add_axes([0.1, 0.08, 0.35, 0.02])
    colorbar_ticks = [level for i, level in enumerate(wind_speed_levels[:n_colors]) if i % 2 == 0]
    cbar1 = plt.colorbar(contourf, cax=cbar_ax1, orientation='horizontal', 
                        ticks=colorbar_ticks, label='Wind Speed (m/s)')
    
    # 添加差值色彩条
    cbar_ax2 = fig.add_axes([0.55, 0.08, 0.35, 0.02])
    diff_ticks = np.linspace(-max_height_diff, max_height_diff, 9)
    cbar2 = plt.colorbar(contourf_diff, cax=cbar_ax2, orientation='horizontal', 
                        ticks=diff_ticks, label='Height Difference (gpm)')
    
    # 保存图像
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, bbox_inches='tight', dpi=300)
    print(f"对比图像已保存到: {output_path}")
    print(f"配置 - {pressure_level}hPa 等高线间距: {height_interval}gpm, 最大风速显示: {actual_max_wind:.0f}m/s, 箭头密度: 1/{skip_factor}")
    plt.close()

def main():
    """
    主函数：下载数据并绘制两个时期的月份气候态对比
    """
    
    # ========== 统一设置参数 ==========
    pressure_level = 500  # 气压层 (hPa)
    variables = ['geopotential', 'u_component_of_wind', 'v_component_of_wind']  # 下载变量
    period1_range = (1951, 1980)  # 第一个时期
    period2_range = (1991, 2020)  # 第二个时期
    smooth_sigma = 1.5  # 高斯平滑参数
    # ================================
    
    print(f"\n处理 {pressure_level}hPa 两个时期对比...")
    
    # 下载第一个时期数据
    print(f"\n下载第一个时期数据 ({period1_range[0]}-{period1_range[1]})...")
    file_path1 = download_era5_monthly_climatology(
        pressure_level=pressure_level,
        variables=variables,
        years_range=period1_range
    )
    
    if file_path1 is None:
        print(f"跳过：第一个时期数据下载失败")
        return
    
    # 下载第二个时期数据
    print(f"\n下载第二个时期数据 ({period2_range[0]}-{period2_range[1]})...")
    file_path2 = download_era5_monthly_climatology(
        pressure_level=pressure_level,
        variables=variables,
        years_range=period2_range
    )
    
    if file_path2 is None:
        print(f"跳过：第二个时期数据下载失败")
        return
    
    # 计算第一个时期月份气候态
    print(f"\n计算第一个时期气候态...")
    period1_jan, period1_jul = calculate_monthly_climatology(file_path1, pressure_level)
    
    if period1_jan is None or period1_jul is None:
        print(f"跳过：第一个时期气候态计算失败")
        return
    
    # 计算第二个时期月份气候态
    print(f"\n计算第二个时期气候态...")
    period2_jan, period2_jul = calculate_monthly_climatology(file_path2, pressure_level)
    
    if period2_jan is None or period2_jul is None:
        print(f"跳过：第二个时期气候态计算失败")
        return
    
    # 绘制对比图像
    output_path = f'Output/MeteoMap-Average/images/ERA5_{pressure_level}hPa_climatology_comparison_with_differences_{period1_range[0]}_{period1_range[1]}_vs_{period2_range[0]}_{period2_range[1]}.png'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    draw_period_comparison(
        period1_data=(period1_jan, period1_jul),
        period2_data=(period2_jan, period2_jul),
        pressure_level=pressure_level,
        output_path=output_path,
        period1_range=period1_range,
        period2_range=period2_range,
        smooth_sigma=smooth_sigma
    )
    
    print(f"{pressure_level}hPa 两个时期对比处理完成\n")

if __name__ == "__main__":
    main()