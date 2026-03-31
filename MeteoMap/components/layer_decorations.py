import numpy as np
import requests
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from shapely.geometry import shape

def download_china_boundaries():
    try:
        china_url = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
        response = requests.get(china_url, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error downloading China boundaries: {e}")
    return None

def add_boundaries_and_grid(ax, lon_min, lon_max, lat_min, lat_max, use_china_boundaries=True):
    # 添加海岸线和边界
    try:
        ax.coastlines(resolution='50m', alpha=0.5, linewidth=0.5)
        if use_china_boundaries:
            china_geojson = download_china_boundaries()
            china_boundaries_added = False
            if china_geojson and 'features' in china_geojson:
                for feature in china_geojson['features']:
                    if feature['geometry']['type'] in ['Polygon', 'MultiPolygon']:
                        geom = shape(feature['geometry'])
                        # Clip geometry to given bbox
                        from shapely.geometry import box
                        bbox = box(lon_min, lat_min, lon_max, lat_max)
                        try:
                            geom = geom.intersection(bbox)
                            if geom.is_empty:
                                continue
                        except:
                            pass
                            
                        # Plot polygons
                        if geom.geom_type == 'Polygon':
                            x, y = geom.exterior.xy
                            ax.plot(x, y, color='black', linewidth=0.8, alpha=0.8, transform=ccrs.PlateCarree())
                            for interior in geom.interiors:
                                x, y = interior.xy
                                ax.plot(x, y, color='black', linewidth=0.6, alpha=0.8, transform=ccrs.PlateCarree())
                        elif geom.geom_type == 'MultiPolygon':
                            for polygon in geom.geoms:
                                if polygon.geom_type == 'Polygon':
                                    x, y = polygon.exterior.xy
                                    ax.plot(x, y, color='black', linewidth=0.8, alpha=0.8, transform=ccrs.PlateCarree())
                                    for interior in polygon.interiors:
                                        x, y = interior.xy
                                        ax.plot(x, y, color='black', linewidth=0.6, alpha=0.8, transform=ccrs.PlateCarree())
                china_boundaries_added = True
                
            if not china_boundaries_added:
                ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
        else:
            ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
    except Exception as e:
        print(f"添加边界时出错: {e}")
        ax.coastlines(resolution='50m')
        ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.5)
        
    # 添加网格线 - 恢复原版设置
    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.7)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlocator = plt.FixedLocator(np.arange(np.floor(lon_min), np.ceil(lon_max) + 1, 5))
    gl.ylocator = plt.FixedLocator(np.arange(np.floor(lat_min), np.ceil(lat_max) + 1, 5))

def add_titles(ax, main_title, time_title, stats_lines):
    """
    恢复原版的左标题、右标题(最值)摆放方法。
    直接在图框边缘使用 ax.text 进行标注。
    """
    left_str = f"{main_title}\n{time_title}"
    ax.text(0.01, 1.015, left_str, transform=ax.transAxes, ha='left', va='bottom', 
            fontsize=17, fontweight='bold', color='black')
    
    if stats_lines:
        right_str = '\n'.join(stats_lines)
        ax.text(0.99, 1.015, right_str, transform=ax.transAxes, ha='right', va='bottom', 
                fontsize=12, color='black')
