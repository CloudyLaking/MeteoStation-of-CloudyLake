import os
import matplotlib.pyplot as plt
import numpy as np
import datetime as dt

# 内部模块
from data_fetcher import fetch_era5_pressure_data, fetch_era5_surface_data
from components.base_map import create_base_map
from components.layer_shaded import calculate_k_index, add_shaded_kindex, add_shaded_cape, add_shaded_temp, add_shaded_wind_speed, add_shaded_generic
from components.layer_contour import add_height_contour, add_slp_contour, add_contour_generic
from components.layer_wind import add_wind_barbs
from components.layer_decorations import add_boundaries_and_grid, add_titles

def run_composite_map(config):
    """
    通用绘图配置执行入口。可根据字典灵活组合填色图、等值线和风场。
    """
    date_str = config.get("date_str", "2024072400")
    lon_min, lon_max = config.get("lon_min", 80), config.get("lon_max", 140)
    lat_min, lat_max = config.get("lat_min", 20), config.get("lat_max", 55)
    
    # 初始化绘图完全还原原版样式
    fig, ax = create_base_map(lon_min, lon_max, lat_min, lat_max)
    lon_grid, lat_grid = None, None

    # ============== 数据聚合结构 ==============
    shaded_type = config.get("shaded_type")
    shaded_level = config.get("shaded_level")
    
    stats_lines = []
    title_parts = []

    # ============== 1. 填色层逻辑 (Shaded) ==============
    if shaded_type == "KIndex":
        data_k = fetch_era5_pressure_data(
            date=date_str, pressure_level=[500, 700, 850], variables=['temperature', 'relative_humidity'],
            lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max
        )
        if data_k:
            lon_grid, lat_grid = np.meshgrid(data_k.longitude.values, data_k.latitude.values)
            
            # Xarray中气压层的坐标名是 'pressure_level'，不再是旧版的 'level'
            t500 = data_k.t.sel(pressure_level=500).values.squeeze()
            t700 = data_k.t.sel(pressure_level=700).values.squeeze()
            t850 = data_k.t.sel(pressure_level=850).values.squeeze()
            r500 = data_k.r.sel(pressure_level=500).values.squeeze()
            r700 = data_k.r.sel(pressure_level=700).values.squeeze()
            r850 = data_k.r.sel(pressure_level=850).values.squeeze()
            
            k_index_data = calculate_k_index(t500, t700, t850, r500, r700, r850)
            vmin, vmax, vmean, vname, unit = add_shaded_kindex(ax, fig, lon_grid, lat_grid, k_index_data, smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"{vname}: {vmin:.1f}-{vmax:.1f}{unit} (avg: {vmean:.1f}{unit})")
            title_parts.append('K-index')

    elif shaded_type == "CAPE":
        data_cape = fetch_era5_surface_data(
            date=date_str, variables=['convective_available_potential_energy'],
            lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max
        )
        if data_cape:
            lon_grid, lat_grid = np.meshgrid(data_cape.longitude.values, data_cape.latitude.values)
            cape_data = data_cape.cape.values.squeeze()
            vmin, vmax, vmean, vname, unit = add_shaded_cape(ax, fig, lon_grid, lat_grid, cape_data, smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"{vname}: {vmin:.1f}-{vmax:.1f} {unit} (avg: {vmean:.1f} {unit})")
            title_parts.append('CAPE')

    elif shaded_type == "Temperature":
        if str(shaded_level) == "2m":
            data_t = fetch_era5_surface_data(date=date_str, variables=['2m_temperature'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            t_var = 't2m'
        else:
            data_t = fetch_era5_pressure_data(date=date_str, pressure_level=shaded_level, variables=['temperature'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            t_var = 't'
            
        if data_t:
            lon_grid, lat_grid = np.meshgrid(data_t.longitude.values, data_t.latitude.values)
            temp_data = data_t[t_var].values.squeeze()
            vmin, vmax, vmean, vname, unit = add_shaded_temp(ax, fig, lon_grid, lat_grid, temp_data, level_tag=str(shaded_level), smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"{vname}: {vmin:.1f}-{vmax:.1f} {unit}")
            title_parts.append(f'Temp ({shaded_level})')

    elif shaded_type == "WindSpeed":
        if str(shaded_level) in ["10m", "100m"]:
            data_ws = fetch_era5_surface_data(date=date_str, variables=[f'{str(shaded_level)}_u_component_of_wind', f'{str(shaded_level)}_v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            u_var, v_var = f'u{str(shaded_level)[:-1]}', f'v{str(shaded_level)[:-1]}'
        else:
            data_ws = fetch_era5_pressure_data(date=date_str, pressure_level=shaded_level, variables=['u_component_of_wind', 'v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            u_var, v_var = 'u', 'v'
            
        if data_ws:
            lon_grid, lat_grid = np.meshgrid(data_ws.longitude.values, data_ws.latitude.values)
            u_data = data_ws[u_var].values.squeeze()
            v_data = data_ws[v_var].values.squeeze()
            vmin, vmax, vmean, vname, unit = add_shaded_wind_speed(ax, fig, lon_grid, lat_grid, u_data, v_data, level_tag=str(shaded_level), smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"{vname}: max {vmax:.1f} {unit}")
            title_parts.append(f'WindSpd ({shaded_level})')

    elif shaded_type is not None:
        # ----- 通用填色参数 Fallback (自适应配色及范围) -----
        # 常见的高空变量名，用于防呆，防止用户查询高空变量却忘了指定高度导致报错
        KNOWN_PRESSURE_VARS = ['vorticity', 'divergence', 'vertical_velocity', 'relative_humidity', 'specific_humidity', 'temperature', 'geopotential']
        
        # 判断是高空还是地面 (根据是否指定了整数气压层)
        is_surface = (shaded_level is None) or (isinstance(shaded_level, str) and shaded_level.endswith('m'))
        if is_surface and shaded_type in KNOWN_PRESSURE_VARS:
            print(f"⚠️ 警告: '{shaded_type}' 是高空变量，但未指定高度层。自动默认使用 500 hPa。")
            is_surface = False
            shaded_level = 500
            
        if is_surface:
            data_gen = fetch_era5_surface_data(date=date_str, variables=[shaded_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_gen = fetch_era5_pressure_data(date=date_str, pressure_level=shaded_level, variables=[shaded_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            
        if data_gen:
            lon_grid, lat_grid = np.meshgrid(data_gen.longitude.values, data_gen.latitude.values)
            # 获取数据实体变量 (剔除经纬度等坐标维度)
            valid_vars = [v for v in data_gen.data_vars.keys()]
            if valid_vars:
                gen_var = valid_vars[0]  
                # 处理如果数据里仍然有 pressure_level 坐标未被 squeeze 的情况
                if 'pressure_level' in data_gen[gen_var].coords:
                    val_data = data_gen[gen_var].sel(pressure_level=int(shaded_level)).values.squeeze()
                else:
                    val_data = data_gen[gen_var].values.squeeze()
                
                vmin, vmax, vmean, vname, unit = add_shaded_generic(ax, fig, lon_grid, lat_grid, val_data, var_name=shaded_type, smooth_sigma=config.get("smooth_sigma", 1))
                
                # 因为数值范围未知，采用科学计数或浮点适配
                stats_lines.append(f"{vname}: {vmin:.2e} ~ {vmax:.2e}")
                title_parts.append(f'{vname}')

    # ============== 2. 等值线层 (Contour) ==============
    contour_type = config.get("contour_type")
    contour_level = config.get("contour_level")
    
    if contour_type == "Geopotential":
        data_z = fetch_era5_pressure_data(date=date_str, pressure_level=contour_level, variables=['geopotential'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        if data_z:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_z.longitude.values, data_z.latitude.values)
            z_data = data_z.z.values.squeeze() / 9.80665
            add_height_contour(ax, lon_grid, lat_grid, data_z.z.values.squeeze(), contour_level, smooth_sigma=config.get("smooth_sigma", 1))
            
            z_min, z_max = np.min(z_data), np.max(z_data)
            stats_lines.append(f"{contour_level}hPa Height: {z_min:.0f}-{z_max:.0f}gpm")
            title_parts.append(f'{contour_level}hPa GPH')
            
    elif contour_type == "SLP":
        data_slp = fetch_era5_surface_data(date=date_str, variables=['mean_sea_level_pressure'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        if data_slp:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_slp.longitude.values, data_slp.latitude.values)
            slp_data = data_slp.msl.values.squeeze() / 100.0
            add_slp_contour(ax, lon_grid, lat_grid, data_slp.msl.values.squeeze(), smooth_sigma=config.get("smooth_sigma", 1))
            
            slp_min, slp_max = np.min(slp_data), np.max(slp_data)
            stats_lines.append(f"SLP: {slp_min:.0f}-{slp_max:.0f} hPa")
            title_parts.append(f'SLP')
            
    elif contour_type is not None:
        # ----- 通用等值线参数 Fallback (自适应等高线间隔) -----
        # 常见的高空变量名，用于防呆
        KNOWN_PRESSURE_VARS = ['vorticity', 'divergence', 'vertical_velocity', 'relative_humidity', 'specific_humidity', 'temperature', 'geopotential']
        
        # 判断是高空还是地面 (根据是否指定了整数气压层)
        is_surface = (contour_level is None) or (isinstance(contour_level, str) and contour_level.endswith('m'))
        if is_surface and contour_type in KNOWN_PRESSURE_VARS:
            print(f"⚠️ 警告: '{contour_type}' 是高空变量，但未指定高度层。自动默认使用 500 hPa。")
            is_surface = False
            contour_level = 500
            
        if is_surface:
            data_gen_c = fetch_era5_surface_data(date=date_str, variables=[contour_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_gen_c = fetch_era5_pressure_data(date=date_str, pressure_level=contour_level, variables=[contour_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            
        if data_gen_c:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_gen_c.longitude.values, data_gen_c.latitude.values)
            valid_vars = [v for v in data_gen_c.data_vars.keys()]
            if valid_vars:
                gen_var = valid_vars[0]  
                if 'pressure_level' in data_gen_c[gen_var].coords:
                    val_data = data_gen_c[gen_var].sel(pressure_level=int(contour_level)).values.squeeze()
                else:
                    val_data = data_gen_c[gen_var].values.squeeze()
                
                add_contour_generic(ax, lon_grid, lat_grid, val_data, var_name=contour_type, smooth_sigma=config.get("smooth_sigma", 1))
                
                cmin, cmax = np.nanmin(val_data), np.nanmax(val_data)
                vname = str(contour_type).replace('_', ' ').title()
                stats_lines.append(f"{vname}: {cmin:.2e} ~ {cmax:.2e}")
                title_parts.append(f'{vname}')

    # ============== 3. 风场矢量打点层 (Wind) ==============
    if config.get("show_wind"):
        wind_level = config.get("wind_level", 850)
        if str(wind_level) in ["10m", "100m"]:
            data_wind = fetch_era5_surface_data(date=date_str, variables=[f'{str(wind_level)}_u_component_of_wind', f'{str(wind_level)}_v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            u_var, v_var = f'u{str(wind_level)[:-1]}', f'v{str(wind_level)[:-1]}'
        else:
            data_wind = fetch_era5_pressure_data(date=date_str, pressure_level=wind_level, variables=['u_component_of_wind', 'v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            u_var, v_var = 'u', 'v'

        if data_wind:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_wind.longitude.values, data_wind.latitude.values)
            u_wd = data_wind[u_var].values.squeeze()
            v_wd = data_wind[v_var].values.squeeze()
            add_wind_barbs(ax, lon_grid, lat_grid, u_wd, v_wd, wind_density=config.get("wind_density", 20))
            
            w_speed_max = np.max(np.sqrt(u_wd**2 + v_wd**2))
            stats_lines.append(f"{wind_level}hPa Wind: max {w_speed_max:.1f}m/s")
            title_parts.append(f'{wind_level}hPa Wind')

    # ============== 4. 添加原版边界网络与组合标题标题 ==============
    add_boundaries_and_grid(ax, lon_min, lon_max, lat_min, lat_max, use_china_boundaries=config.get("use_china_boundaries", True))

    data_source = config.get("data_source", "ERA5")
    main_title = f"{data_source} " + " + ".join(title_parts)
    
    try:
        date_obj = dt.datetime.strptime(date_str, '%Y%m%d%H')
        time_title = date_obj.strftime('%Y-%m-%d %H:00 UTC')
    except:
        time_title = date_str

    if not config.get("show_stats", True):
        stats_lines = []

    add_titles(ax, main_title, time_title, stats_lines)

    # ============== 5. 保存输出 ==============
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../Output/MeteoMap'))
    os.makedirs(output_dir, exist_ok=True)
    
    # 按照 ERA5_500HeightAnomaly_850Wind_2022112500.png 风格自动拼装文件命名
    save_parts = [data_source]
    if shaded_type:
        lvl_str = str(shaded_level) if shaded_level is not None else ""
        save_parts.append(f"{lvl_str}{shaded_type}")
    if contour_type:
        clvl_str = str(contour_level) if contour_level is not None else ""
        save_parts.append(f"{clvl_str}{contour_type}")
    if config.get("show_wind"):
        save_parts.append(f"{config.get('wind_level')}Wind")
    save_parts.append(date_str)
    
    filename = "_".join(save_parts) + ".png"
    out_file = os.path.join(output_dir, filename)
    
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Success: Plot saved to {out_file}")

if __name__ == "__main__":
    # ==========================================
    # 主程序统一测试入口: 风速填色 + SLP等值线 + 10m风场
    # 这里附带了所有可选选项的详细说明
    # ==========================================
    config_example = {
        # --- 基础设置 ---
        "date_str": "2025070700",       # 时间字符串 (YYYYMMDDHH)
        "data_source": "ERA5",          # 数据源名称，用于标题和保存文件名
        "lon_min": 80, "lon_max": 140,  # 经度范围 (默认 80~140)
        "lat_min": 20, "lat_max": 55,   # 纬度范围 (默认 20~55)
        
        # --- 填色数据层 (Shaded) --- 
        # "shaded_type" 可选值: 
        #   [特设优化配色的参数]: "KIndex", "CAPE", "Temperature", "WindSpeed"
        #   
        #   [通用 ERA5 数据参数 (高空/等压面 pressure_level)]:
        #       - "relative_humidity" (相对湿度) 
        #       - "specific_humidity" (比湿)
        #       - "vorticity" (相对涡度) 
        #       - "divergence" (散度) 
        #       - "vertical_velocity" (垂直运动/欧米伽)
        #       - "temperature" (高空温度)
        #       - "geopotential" (位势)
        #   
        #   [通用 ERA5 数据参数 (地表 single_levels, 需设 level="10m" 或 "2m" 或 None)]:
        #       - "2m_temperature", "2m_dewpoint_temperature" (2米温度/露点)
        #       - "10m_u_component_of_wind", "10m_v_component_of_wind" (10米风分量)
        #       - "surface_pressure", "mean_sea_level_pressure" (地表气压/海平面气压)
        #       - "total_precipitation", "convective_precipitation" (总降水/对流降水)
        #       - "surface_latent_heat_flux", "surface_sensible_heat_flux" (潜热/显热通量)
        #       - "total_cloud_cover" (总云量)
        #       - "cape", "k_index" (如果手动从单层调取)
        #
        #   注意：CDS对于高空(压力层)和地表(单层)的变量名严格区分，比如地表没有 vorticity(涡度)！
        #   [不填色]: None
        "shaded_type": "total_precipitation",   
        # "shaded_level": 对应数据的气压层(如 850, 500)。对于单层地表可传 "2m", "10m" 或 None。
        "shaded_level": "2m",           
        
        # --- 等值线数据层 (Contour) ---
        # "contour_type" 可选值: 
        #   [特设参数]: "Geopotential" (位势高度), "SLP" (海平面气压)
        #   [通用参数]: (参考上方的可用列表。高空用高空参数，单层用单层参数)
        #   [不等值线]: None
        "contour_type": "Geopotential",          
        # "contour_level": 气压层高度。仅在 "Geopotential" 时必须指定(如 500)，SLP不需要传None即可。
        "contour_level": 500,          
        
        # --- 风场矢量点层 (Wind) ---
        "show_wind": True,              # 是否绘制风羽
        "wind_level": "10m",            # 风场高度层，如 850 或边界层 "10m", "100m"
        "wind_density": 22,             # 风矢量抽稀密度 (数值越大风标越稀疏)
        
        # --- 装饰选项 ---
        "smooth_sigma": 1,              # 统一的图面高斯平滑数值，设为 0 关闭平滑 (默认 1)
        "use_china_boundaries": True,   # 是否叠加高精度的官方DataV国界/省界线
        "show_stats": True              # 是否在右上角显示所填图层的极值/均值统计板
    }
    
    print("Testing Example: 10m WindSpeed / SLP / 10m Wind...")
    run_composite_map(config_example)
