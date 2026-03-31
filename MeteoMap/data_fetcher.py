import os
import xarray as xr

# Define DATA_DIR relative to the root of the workspace
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../Output/MeteoMap/data'))
os.makedirs(DATA_DIR, exist_ok=True)

def fetch_era5_pressure_data(date, pressure_level, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载或读取本地的ERA5气压层数据。
    """
    try:
        import cdsapi
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None
        
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    
    # 构造固化的本地缓存文件名
    var_str = "-".join(variables) if isinstance(variables, list) else variables
    filename = f"ERA5_{var_str}_{pressure_level}hPa_{date}.nc"
    output_file = os.path.join(DATA_DIR, filename)
    
    # 如果本地已有所需文件，则直接读取（实现持久化重用）
    if os.path.exists(output_file):
        print(f"Loading local cached data: {filename}")
        with xr.open_dataset(output_file) as ds:
            return ds.load()

    # 否则，调用 cdsapi 下载
    print(f"Downloading from ERA5 to {output_file}...")
    c = cdsapi.Client()
    try:
        c.retrieve(
            'reanalysis-era5-pressure-levels',
            {
                'product_type': 'reanalysis',
                'data_format': 'netcdf',
                'download_format': 'unarchived',
                'variable': variables,
                'pressure_level': [str(p) for p in pressure_level] if isinstance(pressure_level, list) else str(pressure_level),
                'year': year,
                'month': month,
                'day': day,
                'time': f'{hour}:00',
                'area': [lat_max, lon_min, lat_min, lon_max],
            },
            output_file)
        
        with xr.open_dataset(output_file) as ds:
            return ds.load()
            
    except Exception as e:
        print(f"下载ERA5气压层数据时出错: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)  # 清理下载失败的残缺文件
        return None

def fetch_era5_monthly_pressure_data(years_range, months, pressure_level, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载或读取 ERA5 月平均气候态（等压层）数据
    """
    try:
        import cdsapi
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None

    # 用排序后的月份确保缓存名唯一
    months_str = "".join(sorted([str(m).zfill(2) for m in months]))
    var_str = "-".join(variables) if isinstance(variables, list) else variables
    p_str = "-".join([str(p) for p in pressure_level]) if isinstance(pressure_level, list) else str(pressure_level)
    
    filename = f"ERA5_Monthly_{var_str}_{p_str}hPa_{years_range[0]}-{years_range[1]}_m{months_str}.nc"
    output_file = os.path.join(DATA_DIR, filename)

    if os.path.exists(output_file):
        print(f"Loading local cached climatology: {filename}")
        with xr.open_dataset(output_file) as ds:
            return ds.load()

    print(f"Downloading ERA5 Climatology (Pressure) to {output_file}...")
    c = cdsapi.Client()
    try:
        years = [str(y) for y in range(years_range[0], years_range[1] + 1)]
        months_str_list = [str(m).zfill(2) for m in months]
        
        c.retrieve(
            'reanalysis-era5-pressure-levels-monthly-means',
            {
                'product_type': 'monthly_averaged_reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'pressure_level': [str(p) for p in pressure_level] if isinstance(pressure_level, list) else str(pressure_level),
                'year': years,
                'month': months_str_list,
                'time': '00:00',
                'area': [lat_max, lon_min, lat_min, lon_max],
            },
            output_file)
        
        with xr.open_dataset(output_file) as ds:
            return ds.load()
    except Exception as e:
        print(f"下载ERA5月平均气压层数据出错: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
        return None


def fetch_era5_surface_data(date, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载或读取本地的ERA5单层（地面）数据。
    """
    try:
        import cdsapi
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None
        
    year, month, day, hour = date[0:4], date[4:6], date[6:8], date[8:10]
    
    var_str = "-".join(variables) if isinstance(variables, list) else variables
    filename = f"ERA5_{var_str}_surface_{date}.nc"
    output_file = os.path.join(DATA_DIR, filename)
    
    if os.path.exists(output_file):
        print(f"Loading local cached data: {filename}")
        with xr.open_dataset(output_file) as ds:
            return ds.load()

    print(f"Downloading from ERA5 to {output_file}...")
    c = cdsapi.Client()
    try:
        c.retrieve(
            'reanalysis-era5-single-levels',
            {
                'product_type': 'reanalysis',
                'data_format': 'netcdf',
                'download_format': 'unarchived',
                'variable': variables,
                'year': year,
                'month': month,
                'day': day,
                'time': f'{hour}:00',
                'area': [lat_max, lon_min, lat_min, lon_max],
            },
            output_file)
        
        with xr.open_dataset(output_file) as ds:
            return ds.load()
            
    except Exception as e:
        print(f"下载ERA5单层数据时出错: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
        return None

def fetch_era5_monthly_surface_data(years_range, months, variables, lon_min, lon_max, lat_min, lat_max):
    """
    下载或读取 ERA5 月平均气候态（单层/表面）数据
    """
    try:
        import cdsapi
    except ImportError:
        print("需要安装: pip install cdsapi")
        return None

    months_str = "".join(sorted([str(m).zfill(2) for m in months]))
    var_str = "-".join(variables) if isinstance(variables, list) else variables
    
    filename = f"ERA5_Monthly_{var_str}_surface_{years_range[0]}-{years_range[1]}_m{months_str}.nc"
    output_file = os.path.join(DATA_DIR, filename)

    if os.path.exists(output_file):
        print(f"Loading local cached climatology: {filename}")
        with xr.open_dataset(output_file) as ds:
            return ds.load()

    print(f"Downloading ERA5 Climatology (Surface) to {output_file}...")
    c = cdsapi.Client()
    try:
        years = [str(y) for y in range(years_range[0], years_range[1] + 1)]
        months_str_list = [str(m).zfill(2) for m in months]
        
        c.retrieve(
            'reanalysis-era5-single-levels-monthly-means',
            {
                'product_type': 'monthly_averaged_reanalysis',
                'format': 'netcdf',
                'variable': variables,
                'year': years,
                'month': months_str_list,
                'time': '00:00',
                'area': [lat_max, lon_min, lat_min, lon_max],
            },
            output_file)
        
        with xr.open_dataset(output_file) as ds:
            return ds.load()
    except Exception as e:
        print(f"下载ERA5月平均单层数据出错: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
        return None

