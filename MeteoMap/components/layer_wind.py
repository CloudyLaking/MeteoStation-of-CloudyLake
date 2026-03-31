import cartopy.crs as ccrs

def add_wind_barbs(ax, lon_grid, lat_grid, u_wind, v_wind, wind_density=20, color='darkblue'):
    """
    叠加不同密度的风矢量图 (风羽版)
    能够自适应经纬度网格的抽稀
    """
    grid_points = max(u_wind.shape)
    
    # 根据用户期望的显示密度计算抽稀系数
    skip_factor = max(1, int(grid_points / wind_density))
    skip = (slice(None, None, skip_factor), slice(None, None, skip_factor))
    
    # 绘制风羽
    ax.barbs(lon_grid[skip], lat_grid[skip], u_wind[skip], v_wind[skip],
             length=6, linewidth=1, pivot='middle', 
             color=color, alpha=0.8, transform=ccrs.PlateCarree())
