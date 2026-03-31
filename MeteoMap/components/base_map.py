import os
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import matplotlib.font_manager as font_manager

def create_base_map(lon_min, lon_max, lat_min, lat_max, figsize=(15, 12)):
    """
    创建地图画布及底图，严格继承原版字体设置
    """
    # 恢复原版字体设置
    try:
        # 获取 MiSans VF.ttf 的绝对路径 (根据原有相对路径推算)
        font_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../MiSans VF.ttf'))
        if os.path.exists(font_path):
            font_manager.fontManager.addfont(font_path)
            plt.rcParams['font.sans-serif'] = ['MiSans VF']
        else:
            plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
    except Exception as e:
        print(f"设置字体时出错: {e}")
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
        
    plt.rcParams['axes.unicode_minus'] = False
    
    fig = plt.figure(figsize=figsize)
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    # 设置地图范围
    ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())
    
    return fig, ax
