import os
import matplotlib.pyplot as plt
import numpy as np
import datetime as dt

# 内部模块 (复用主程序的底层绘图组件)
from data_fetcher import fetch_era5_monthly_pressure_data, fetch_era5_monthly_surface_data
from components.base_map import create_base_map
from components.layer_shaded import add_shaded_temp, add_shaded_wind_speed, add_shaded_generic
from components.layer_contour import add_height_contour, add_slp_contour, add_contour_generic
from components.layer_wind import add_wind_barbs
from components.layer_decorations import add_boundaries_and_grid, add_titles

def get_climate_data(data_ds, var_level=None):
    """
    对多时间维度的气候态数据进行求平均处理，将其压扁为2D地理数据
    支持同时处理带有 pressure_level 和 time/valid_time 的数据
    """
    # 确定时间维度名称
    time_dim = 'valid_time' if 'valid_time' in data_ds.dims else 'time'
    
    # 沿时间维度求全体平均 (算出气候平均态)
    ds_mean = data_ds.mean(dim=time_dim)
    
    # 获取主要物理量名称
    valid_vars = [v for v in ds_mean.data_vars.keys()]
    if not valid_vars:
        return None
    var_name = valid_vars[0]
    
    # 如果明确指定了气压层并且数据里有这个维度，则选择该层
    if var_level is not None and str(var_level).isdigit() and 'pressure_level' in ds_mean.coords:
        return ds_mean[var_name].sel(pressure_level=int(var_level)).values.squeeze(), var_name
    else:
        return ds_mean[var_name].values.squeeze(), var_name

def run_climate_map(config):
    """
    通用ERA5气候态(多年平均)绘图配置执行入口。可根据字典灵活组合填色图、等值线和风场。
    """
    years_range = config.get("years_range", (1991, 2020))
    months = config.get("months", [7]) # 默认7月
    
    lon_min, lon_max = config.get("lon_min", 80), config.get("lon_max", 140)
    lat_min, lat_max = config.get("lat_min", 20), config.get("lat_max", 55)
    
    fig, ax = create_base_map(lon_min, lon_max, lat_min, lat_max)
    lon_grid, lat_grid = None, None

    shaded_type = config.get("shaded_type")
    shaded_level = config.get("shaded_level")
    stats_lines = []
    title_parts = []

    KNOWN_PRESSURE_VARS = ['vorticity', 'divergence', 'vertical_velocity', 'relative_humidity', 'specific_humidity', 'temperature', 'geopotential']

    # ============== 1. 填色层逻辑 (Shaded) ==============
    if shaded_type == "Temperature":
        is_surface = (shaded_level is None) or (isinstance(shaded_level, str) and shaded_level.endswith('m'))
        if is_surface:
            data_t = fetch_era5_monthly_surface_data(years_range=years_range, months=months, variables=['2m_temperature'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_t = fetch_era5_monthly_pressure_data(years_range=years_range, months=months, pressure_level=[shaded_level], variables=['temperature'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            
        if data_t:
            lon_grid, lat_grid = np.meshgrid(data_t.longitude.values, data_t.latitude.values)
            temp_data, _ = get_climate_data(data_t, var_level=shaded_level)
            
            vmin, vmax, vmean, vname, unit = add_shaded_temp(ax, fig, lon_grid, lat_grid, temp_data, level_tag=str(shaded_level), smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"Clim {vname}: {vmin:.1f}-{vmax:.1f} {unit}")
            title_parts.append(f'Temp ({shaded_level})')

    elif shaded_type == "WindSpeed":
        is_surface = (shaded_level is None) or (isinstance(shaded_level, str) and shaded_level.endswith('m'))
        if is_surface:
            data_ws = fetch_era5_monthly_surface_data(years_range=years_range, months=months, variables=['10m_u_component_of_wind', '10m_v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_ws = fetch_era5_monthly_pressure_data(years_range=years_range, months=months, pressure_level=[shaded_level], variables=['u_component_of_wind', 'v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            
        if data_ws:
            lon_grid, lat_grid = np.meshgrid(data_ws.longitude.values, data_ws.latitude.values)
            # 对于风速，我们需要分别求平均后再算速度，或者算好再平均（通常用u, v平均后的合成风速代表气候大环境矢量场）
            time_dim = 'valid_time' if 'valid_time' in data_ws.dims else 'time'
            ds_mean = data_ws.mean(dim=time_dim)
            
            # 分别提取U和V
            u_var = 'u' if not is_surface else 'u10'
            v_var = 'v' if not is_surface else 'v10'
            
            u_data = ds_mean[u_var].sel(pressure_level=int(shaded_level)).values.squeeze() if not is_surface and 'pressure_level' in ds_mean.coords else ds_mean[u_var].values.squeeze()
            v_data = ds_mean[v_var].sel(pressure_level=int(shaded_level)).values.squeeze() if not is_surface and 'pressure_level' in ds_mean.coords else ds_mean[v_var].values.squeeze()
            
            vmin, vmax, vmean, vname, unit = add_shaded_wind_speed(ax, fig, lon_grid, lat_grid, u_data, v_data, level_tag=str(shaded_level), smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"Clim {vname}: max {vmax:.1f} {unit}")
            title_parts.append(f'WindSpd ({shaded_level})')

    elif shaded_type is not None:
        is_surface = (shaded_level is None) or (isinstance(shaded_level, str) and shaded_level.endswith('m'))
        if is_surface and shaded_type in KNOWN_PRESSURE_VARS:
            print(f"⚠️ 警告: '{shaded_type}' 是高空变量，但未指定高度层。自动默认使用 500 hPa。")
            is_surface = False
            shaded_level = 500
            
        if is_surface:
            data_gen = fetch_era5_monthly_surface_data(years_range=years_range, months=months, variables=[shaded_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_gen = fetch_era5_monthly_pressure_data(years_range=years_range, months=months, pressure_level=[shaded_level], variables=[shaded_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            
        if data_gen:
            lon_grid, lat_grid = np.meshgrid(data_gen.longitude.values, data_gen.latitude.values)
            val_data, gen_var_name = get_climate_data(data_gen, var_level=shaded_level)
            
            vmin, vmax, vmean, vname, unit = add_shaded_generic(ax, fig, lon_grid, lat_grid, val_data, var_name=shaded_type, smooth_sigma=config.get("smooth_sigma", 1))
            stats_lines.append(f"Clim. {vname}: {vmin:.2e} ~ {vmax:.2e}")
            title_parts.append(f'{vname}')

    # ============== 2. 等值线层 (Contour) ==============
    contour_type = config.get("contour_type")
    contour_level = config.get("contour_level")
    
    if contour_type == "Geopotential":
        data_z = fetch_era5_monthly_pressure_data(years_range=years_range, months=months, pressure_level=[contour_level], variables=['geopotential'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        if data_z:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_z.longitude.values, data_z.latitude.values)
            z_data, _ = get_climate_data(data_z, var_level=contour_level)
            
            z_data = z_data / 9.80665  # 转为位势高度
            add_height_contour(ax, lon_grid, lat_grid, z_data * 9.80665, contour_level, smooth_sigma=config.get("smooth_sigma", 1))
            
            z_min, z_max = np.min(z_data), np.max(z_data)
            stats_lines.append(f"Clim. {contour_level}hPa Height: {z_min:.0f}-{z_max:.0f}gpm")
            title_parts.append(f'{contour_level}hPa GPH')
            
    elif contour_type == "SLP":
        data_slp = fetch_era5_monthly_surface_data(years_range=years_range, months=months, variables=['mean_sea_level_pressure'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        if data_slp:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_slp.longitude.values, data_slp.latitude.values)
            slp_raw, _ = get_climate_data(data_slp)
            
            add_slp_contour(ax, lon_grid, lat_grid, slp_raw, smooth_sigma=config.get("smooth_sigma", 1))
            slp_data = slp_raw / 100.0
            slp_min, slp_max = np.min(slp_data), np.max(slp_data)
            stats_lines.append(f"Clim. SLP: {slp_min:.0f}-{slp_max:.0f} hPa")
            title_parts.append(f'SLP')
            
    elif contour_type is not None:
        is_surface = (contour_level is None) or (isinstance(contour_level, str) and contour_level.endswith('m'))
        if is_surface and contour_type in KNOWN_PRESSURE_VARS:
            print(f"⚠️ 警告: '{contour_type}' 是高空变量，但未指定高度层。自动默认使用 500 hPa。")
            is_surface = False
            contour_level = 500
            
        if is_surface:
            data_gen_c = fetch_era5_monthly_surface_data(years_range=years_range, months=months, variables=[contour_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_gen_c = fetch_era5_monthly_pressure_data(years_range=years_range, months=months, pressure_level=[contour_level], variables=[contour_type], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
            
        if data_gen_c:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_gen_c.longitude.values, data_gen_c.latitude.values)
            val_data, _ = get_climate_data(data_gen_c, var_level=contour_level)
            
            add_contour_generic(ax, lon_grid, lat_grid, val_data, var_name=contour_type, smooth_sigma=config.get("smooth_sigma", 1))
            
            cmin, cmax = np.nanmin(val_data), np.nanmax(val_data)
            vname = str(contour_type).replace('_', ' ').title()
            stats_lines.append(f"Clim. {vname}: {cmin:.2e} ~ {cmax:.2e}")
            title_parts.append(f'{vname}')

    # ============== 3. 风场矢量打点层 (Wind) ==============
    if config.get("show_wind"):
        wind_level = config.get("wind_level", 850)
        is_wind_surface = (isinstance(wind_level, str) and wind_level.endswith('m'))
        
        if is_wind_surface:
            data_wind = fetch_era5_monthly_surface_data(years_range=years_range, months=months, variables=['10m_u_component_of_wind', '10m_v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)
        else:
            data_wind = fetch_era5_monthly_pressure_data(years_range=years_range, months=months, pressure_level=[wind_level], variables=['u_component_of_wind', 'v_component_of_wind'], lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max)

        if data_wind:
            if lon_grid is None: lon_grid, lat_grid = np.meshgrid(data_wind.longitude.values, data_wind.latitude.values)
            time_dim = 'valid_time' if 'valid_time' in data_wind.dims else 'time'
            ds_mean = data_wind.mean(dim=time_dim)
            
            u_var = 'u' if not is_wind_surface else 'u10'
            v_var = 'v' if not is_wind_surface else 'v10'
            
            u_wd = ds_mean[u_var].sel(pressure_level=int(wind_level)).values.squeeze() if not is_wind_surface and 'pressure_level' in ds_mean.coords else ds_mean[u_var].values.squeeze()
            v_wd = ds_mean[v_var].sel(pressure_level=int(wind_level)).values.squeeze() if not is_wind_surface and 'pressure_level' in ds_mean.coords else ds_mean[v_var].values.squeeze()
            
            add_wind_barbs(ax, lon_grid, lat_grid, u_wd, v_wd, wind_density=config.get("wind_density", 20))
            
            w_speed_max = np.max(np.sqrt(u_wd**2 + v_wd**2))
            stats_lines.append(f"Clim. {wind_level}hPa Wind: max {w_speed_max:.1f}m/s")
            title_parts.append(f'{wind_level}hPa Wind')

    # ============== 4. 添加原版边界网络与组合标题标题 ==============
    add_boundaries_and_grid(ax, lon_min, lon_max, lat_min, lat_max, use_china_boundaries=config.get("use_china_boundaries", True))

    data_source = config.get("data_source", "ERA5 Climatology")
    main_title = f"{data_source} " + " + ".join(title_parts)
    
    # 构建时间标题 (例如: 1991-2020 Means (Jul))
    months_str = ",".join(str(m) for m in months)
    time_title = f"{years_range[0]}-{years_range[1]} Means (Month: {months_str})"

    if not config.get("show_stats", True):
        stats_lines = []

    add_titles(ax, main_title, time_title, stats_lines)

    # ============== 5. 保存输出 ==============
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../Output/MeteoMap-Average/images'))
    os.makedirs(output_dir, exist_ok=True)
    
    save_parts = ["ERA5_Climatology"]
    if shaded_type:
        lvl_str = str(shaded_level) if shaded_level is not None else ""
        save_parts.append(f"{lvl_str}{shaded_type}")
    if contour_type:
        clvl_str = str(contour_level) if contour_level is not None else ""
        save_parts.append(f"{clvl_str}{contour_type}")
    if config.get("show_wind"):
        save_parts.append(f"{config.get('wind_level')}Wind")
    
    save_parts.append(f"{years_range[0]}-{years_range[1]}_m{months_str.replace(',','_')}")
    
    filename = "_".join(save_parts) + ".png"
    out_file = os.path.join(output_dir, filename)
    
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Success: Climate Plot saved to {out_file}")

if __name__ == "__main__":
    # ==========================================
    # 气候态绘图主程序示例: 1991-2020年 7月 500hPa平均位势高度与850hPa风场
    # 设置与 main_plot_climate.py 高度一致，唯一区别是利用了多年跨度及月份
    # ==========================================
    config_example = {
        # --- 气候特征设定 ---
        "years_range": (1991, 2020),    # 计算气候态的起止年份
        "months": [7],                  # 计算平均的月份，例如[7]即代表常年7月，[12,1,2]代表常年冬季
        
        "data_source": "ERA5 Climatology",
        "lon_min": 80, "lon_max": 140,
        "lat_min": 20, "lat_max": 55,
        
        # --- 填色数据层 --- 
        "shaded_type": "WindSpeed",   
        "shaded_level": 500,           
        
        # --- 等值线数据层 ---
        "contour_type": "Geopotential",          
        "contour_level": 500,          
        
        # --- 风场打点层 ---
        "show_wind": True,
        "wind_level": 850,
        "wind_density": 22,
        
        # --- 装饰选项 ---
        "smooth_sigma": 1, 
        "use_china_boundaries": True,   
        "show_stats": True              
    }
    
    print("Testing ERA5 Climatology Example...")
    run_climate_map(config_example)
