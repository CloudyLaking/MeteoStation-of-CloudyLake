# 导入库
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from matplotlib import font_manager
import matplotlib.gridspec as gridspec
import numpy as np

import pyecharts

#得到站点信息
def get_all_station_info():
    # 从文本文件中提取站点信息
    with open(r'C:\Users\lyz13\OneDrive\CloudyLake Programming\MeteoStation of CloudyLake\MeteoStation-of-CloudyLake\station info.txt', 'r', encoding='utf-8') as file:
        station_info = file.read()
    # 分割列
    station_info = station_info.split('\n')
    #分割每一行
    station_info = [info.split(' ') for info in station_info]
    #返回
    return station_info




#主函数
def main():
    station_info = get_all_station_info()
    stations = [(station[2] ,float(station[3])/100, float(station[4])/100) for station in station_info[1:]]
    from pyecharts.charts import Geo
    from pyecharts.globals import ChartType
    from pyecharts.options import TitleOpts, VisualMapOpts

    geo=Geo()
    
    # 添加站点到地图，使用EffectScatter（带有涟漪特效散点）
    for station in stations:
        name, _lng, _lat = station
        # 假设每个站点的value为1，这个值可以根据实际情况进行调整
        geo.add_coordinate(name, _lng, _lat)

    # 设置地图的全局配置项
    geo.set_global_opts(
        title_opts=TitleOpts(title="站点地"),
        visualmap_opts=VisualMapOpts(is_show=False)  # 不显示视觉映射配置项
    )
        
    # 渲染地图到HTML文件
    geo.render("station_map.html")

if __name__ == '__main__':
    main()