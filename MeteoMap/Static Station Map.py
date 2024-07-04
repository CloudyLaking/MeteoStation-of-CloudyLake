#使用cartopy绘制静态站点地图

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import cartopy as cart
import cartopy.feature as cfeature
import cartopy.crs as ccrs
import requests
from bs4 import BeautifulSoup

import pathlib
folder = pathlib.Path(__file__).parent.resolve()

# 得到站点位置数据
def get_all_station_info():
    # 从文本文件中提取站点信息
    with open(f'{folder}/station info.txt', 'r', encoding='utf-8') as file:
        station_info = file.read()
    # 分割列
    station_info = station_info.split('\n')
    #分割每一行
    station_info = [info.split(' ') for info in station_info]
    #返回
    return station_info

# 得到一个站点气象数据
def get_data(url):

    response = requests.get(url)
    
    if response.status_code == 200:
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找标题并提取文本
        title = soup.find('h1').text.strip()
        
        table = soup.find('table', class_='border')
        table_data = []
        for row in table.find_all('tr'):
            row_data = []
            for cell in row.find_all(['th', 'td']):
                row_data.append(cell.text.strip())
            table_data.append(row_data)
        
        #处理掉data里的'-'，并将其转换为0
        for row in table_data[1:]:
            for i in range(len(row)):
                if row[i] == '-':
                    row[i] = '0'
        # 返回标题和表格数据
        
        return table_data
    else:
        return []

# 处理得到所有站点的一种气象数据
def get_all_data(station_info, data_type, time):
    data = []
    i = 0
    for station in station_info[1:]:
        name, number = station[2], station[1]
        lat=float(station[3])/100
        lon=float(station[4])/100
        url = 'https://q-weather.info/weather/{}/today/'.format(number)
            # 获取站点数据
        while True:
            try:    
                # 获取数据
                got_data = get_data(url)
                break
            except Exception as e:
                print("发生错误：", e)
        
        data.append([lat,lon,got_data])

        i+=1
        print(f'{station[2]}{number}获取完成({i}/2167)' )
    return data

# 绘制信息地图
def draw_datamap(station_info, data, data_type):
    return None
    # 创建地图
    fig = plt.figure(figsize=(10, 10))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    
    # 添加海岸线
    ax.add_feature(cfeature.COASTLINE)
    # 添加国家边界
    ax.add_feature(cfeature.BORDERS, linestyle=':')
    # 添加州边界
    ax.add_feature(cfeature.STATES)
    
    # 绘制站点
    for station in station_info[1:]:
        name, lat, lon = station[2], float(station[3])/100, float(station[4])/100
        ax.plot(lon, lat, 'ro', markersize=5, transform=ccrs.PlateCarree())
        ax.text(lon, lat, name, transform=ccrs.PlateCarree())
    
    # 显示图像
    plt.show()

# 绘制普通地图
def draw_map(station_info):
    # 创建地图
    fig = plt.figure(figsize=(12, 10))
    gs = gridspec.GridSpec(1, 1 )  
    ax = fig.add_subplot(gs[0], projection=ccrs.PlateCarree())
    plt.subplots_adjust(left=0.12, right=0.98, top=0.98, bottom=0.05)


    #设置字体
    plt.rcParams['font.sans-serif'] = ['SimHei'] 
    plt.rcParams['axes.unicode_minus'] = False

    # 添加海岸线
    ax.add_feature(cfeature.COASTLINE)
    # 添加国家边界
    ax.add_feature(cfeature.BORDERS, linestyle=':')

    #设置范围
    ax.set_extent([73, 135, 18, 54])
    # 画省界
    ax.add_feature(cfeature.STATES, linestyle='-', edgecolor='black')
    
    # 绘制站点
    for station in station_info[1:-3]:
        lat, lon =  float(station[3])/100, float(station[4])/100
        ax.plot(lon, lat, 'o',color = 'black', markersize=2, transform=ccrs.PlateCarree())
    
    # 显示图像
    plt.savefig('map.jpg')
    plt.close()

# 主函数
def main():
    # 选择要绘制的数据类型
    choices= {'1':'气温', '2':'1小时降水量', '3':'2分钟平均风速与风向', '4':'湿度', '5':'海平面气压', '6':'能见度'}
    choice = input('请选择要绘制的数据类型：\n1.气温\n2.降水量\n3.风速\n4.湿度\n5.气压\n6.能见度\n')
    choice = choices[choice]

    # 选择时间
    time = input('请输入时间：(格式:11)')

    # 得到所有站点信息
    station_info = get_all_station_info()

    # 绘制地图
    demand = 'no'
    if demand == 'yes':
        # 得到所有气象站该时次的该种数据信息
        data = get_all_data(station_info, choice, time)
        draw_datamap(station_info, data, time)
    else:
        draw_map(station_info)

if __name__ == '__main__':
    main()