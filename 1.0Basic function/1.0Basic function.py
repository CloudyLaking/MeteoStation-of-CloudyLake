# 导入库
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt


# 导入requests库
def getdata(url):
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
        
        # 返回标题和表格数据
        return title, table_data
    else:
        return None, []


def drawdata(weather_data,title):
    plt.figure(figsize=(14, 8))  # 设置图形大小
    # 设置中文显示
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']  # 使用微软雅黑
    plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号

    #标题
    plt.title(title, fontsize=25, fontweight='bold')

    # 提取时间列
    time_column = [row[0][11:16] for row in reversed(weather_data[1:])]
    print("Time Column:", time_column)

    # 提取温度列
    temperature_column = [float(row[1]) for row in reversed(weather_data[1:])]
    print("Temperature Column:", temperature_column)

    # 绘制温度关系图
    plt.plot(time_column, temperature_column, color='red', marker='o')
    for i in range(len(time_column)):
        plt.text(time_column[i], temperature_column[i], temperature_column[i], ha='center', va='bottom')
    # 提取湿度列
    humidity_column = [float(row[3])/5 for row in reversed(weather_data[1:])]
    print("Humidity Column:", humidity_column)
    # 绘制湿度柱形图
    plt.bar(time_column, humidity_column, color='lightblue', align='center', width=0.3)
        # 绘制湿度数据标签
    for i in range(len(time_column)):
        plt.text(time_column[i], humidity_column[i], humidity_column[i]*5, ha='center', va='bottom')
    
    # 提取降水量列
    precipitation_column = [float(row[7]) for row in reversed(weather_data[1:])]
    print("Precipitation Column:", precipitation_column)
    # 绘制降水量数据标签
    for i in range(len(time_column)):
        plt.text(time_column[i], precipitation_column[i], precipitation_column[i], ha='center', va='bottom')

    # 绘制降水量柱形图
    plt.bar(time_column, precipitation_column, color='lightgreen', align='center')

    # 添加竖线
    for time in time_column:
        plt.axvline(x=time, color='lightblue', linestyle=':', linewidth=1)

    # 显示图形
    plt.savefig('weather.png', dpi=300)
    plt.show()
    plt.close()

# 调用函数并打印结果
url = 'https://q-weather.info/weather/{}/today/'.format(input("请输入站号：（如：58362）"))
title,weather_data = getdata(url)
if weather_data:
    for row in weather_data:
        print(row)
    drawdata(weather_data,title)