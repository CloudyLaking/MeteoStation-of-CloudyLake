# 画出1979-2024年平均的1月和7月500hPa和200hPa的位势高度场和风场
# MeteoMap-ERA5average/draw-level-wind-and-geopotential-height-average.py

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
    if pressure_level == 500:
        # 500hPa风速配色
        wind_speed_colors = [
            '#FFFFFF', '#E6F7FF', '#BAE7FF', '#91D5FF', '#69C0FF', 
            '#40A9FF', '#1890FF', '#096DD9', '#0050B3', '#003A8C',
            '#002766', '#FF7F00', '#FF4500', '#FF0000', '#B22222'
        ]
        wind_speed_levels = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
        max_wind_display = 70
    else:
        # 其他层级默认配色
        wind_speed_colors = [
            '#FFFFFF', '#E6F7FF', '#BAE7FF', '#91D5FF', '#69C0FF', 
            '#40A9FF', '#1890FF', '#096DD9', '#0050B3', '#003A8C'
        ]
        wind_speed_levels = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
        max_wind_display = 90
    
    return wind_speed_colors, wind_speed_levels, max_wind_display

def get_height_contour_interval(pressure_level):
    """
    根据气压层返回位势高度等高线间距
    """
    if pressure_level == 500:
        return 60  # 500hPa使用60gpm间距
    elif pressure_level == 200:
        return 120  # 200hPa使用120gpm间距
    else:
        return 60  # 默认间距

def draw_monthly_climatology(january_data, july_data, pressure_level, output_path, 
                            years_range=(1979, 2024), smooth_sigma=1.5):
    """
    绘制1月和7月气候态位势高度场和风场
    
    参数:
    january_data, july_data : dict - 包含高度和风场数据的字典
    pressure_level : int - 气压层
    output_path : str - 输出图像路径
    years_range : tuple - 年份范围
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
    
    # 创建图形 - 两个子图
    fig = plt.figure(figsize=(16, 6))
    
    # 获取配色方案
    wind_speed_colors, wind_speed_levels, max_wind_display = get_wind_color_scheme(pressure_level)
    height_interval = get_height_contour_interval(pressure_level)
    
    # 创建风速颜色映射
    n_colors = min(len(wind_speed_colors), len(wind_speed_levels))
    colors_normalized = wind_speed_colors[:n_colors]
    color_positions = np.linspace(0, 1, n_colors)
    cmap = LinearSegmentedColormap.from_list(
        'wind_speed_cmap', 
        list(zip(color_positions, colors_normalized))
    )
    
    # 处理两个月份的数据
    months = [
        ('January', january_data),
        ('July', july_data)
    ]
    
    max_winds = []  # 存储最大风速用于统一色标
    
    # 预计算所有数据以确定统一范围
    all_wind_speeds = []
    all_heights = []
    
    for month_name, month_data in months:
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
    
    # 1月和7月
    for i, (month_name, month_data) in enumerate(months):
        # 创建子图
        ax = plt.subplot(1, 2, i+1, projection=ccrs.PlateCarree())
        
        # 获取数据
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
            linewidths=0.5,
            alpha=0.3
        )
        
        # 添加等高线标签
        ax.clabel(contour, inline=True, fontsize=9, fmt='%d')
        
        # 绘制风标 
        skip_factor = max(0, 50)
        barb_slice = (slice(None, None, skip_factor), slice(None, None, skip_factor))
        ax.barbs(
            lon_grid[barb_slice], lat_grid[barb_slice],
            u_wind[barb_slice], v_wind[barb_slice],
            length=5, pivot='middle', color='black', linewidth=0.8
        )
        
        # 添加海岸线
        ax.coastlines(resolution='50m', alpha=0.7, linewidth=0.8)
        
        # 添加网格线
        gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5)
        gl.top_labels = False
        gl.right_labels = False
        if i == 1:  # 只在右侧子图显示右侧标签
            gl.left_labels = False
        
        # 计算当前月份的统计信息
        month_max_wind = np.max(wind_speed)
        month_min_height = np.min(height_smooth)
        month_max_height = np.max(height_smooth)
        
        # 设置子图标题
        ax.set_title(f'{month_name} {pressure_level}hPa\n'
                    f'Height: {month_min_height:.0f}-{month_max_height:.0f}gpm, '
                    f'Max Wind: {month_max_wind:.1f}m/s', 
                    fontsize=14, fontweight='bold', pad=20)
    
    # 添加总标题
    fig.suptitle(f'ERA5 {pressure_level}hPa Geopotential Height and Wind Climatology ({years_range[0]}-{years_range[1]})', 
                fontsize=16, fontweight='bold', y=0.95)
    
    # 添加统一的色彩条
    # 为色彩条留出空间
    fig.subplots_adjust(bottom=0.15, top=0.85, wspace=0.05)
    
    # 创建色彩条轴
    cbar_ax = fig.add_axes([0.15, 0.08, 0.7, 0.03])
    
    # 设置色彩条刻度
    colorbar_ticks = [level for i, level in enumerate(wind_speed_levels[:n_colors]) if i % 2 == 0]
    
    cbar = plt.colorbar(contourf, cax=cbar_ax, orientation='horizontal', 
                       ticks=colorbar_ticks, label='Wind Speed (m/s)')
    
    # 添加说明文字
    fig.text(0.02, 0.02, f'Contour interval: {height_interval}gpm | Max wind display: {actual_max_wind:.0f}m/s', 
             fontsize=10, ha='left')
    
    # 保存图像
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, bbox_inches='tight', dpi=300)
    print(f"图像已保存到: {output_path}")
    print(f"配置 - {pressure_level}hPa 等高线间距: {height_interval}gpm, 最大风速显示: {actual_max_wind:.0f}m/s")
    plt.close()

def main():
    """
    主函数：下载数据并绘制指定气压层的月份气候态
    """
    
    # ========== 统一设置参数 ==========
    pressure_level = 200  # 气压层 (hPa)
    variables = ['geopotential', 'u_component_of_wind', 'v_component_of_wind']  # 下载变量
    years_range = (1991, 2020)  # 年份范围
    smooth_sigma = 1.5  # 高斯平滑参数
    # ================================
    
    print(f"\n处理 {pressure_level}hPa 数据...")
    
    # 下载数据
    file_path = download_era5_monthly_climatology(
        pressure_level=pressure_level,
        variables=variables,
        years_range=years_range
    )
    
    if file_path is None:
        print(f"跳过 {pressure_level}hPa：数据下载失败")
        return
    
    # 计算月份气候态
    january_data, july_data = calculate_monthly_climatology(file_path, pressure_level)
    
    if january_data is None or july_data is None:
        print(f"跳过 {pressure_level}hPa：气候态计算失败")
        return
    
    # 绘制图像
    output_path = f'Output/MeteoMap-Average/images/ERA5_{pressure_level}hPa_monthly_climatology_{years_range[0]}_{years_range[1]}.png'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    draw_monthly_climatology(
        january_data=january_data,
        july_data=july_data,
        pressure_level=pressure_level,
        output_path=output_path,
        years_range=years_range,
        smooth_sigma=smooth_sigma
    )
    
    print(f"{pressure_level}hPa 处理完成\n")

if __name__ == "__main__":
    main()