# 导入库
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 请求数据
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

# 绘制数据
def drawdata(weather_data,title):

    # 设置图形大小
    fig, ax1 = plt.subplots(figsize=(14, 8))
    ax2 = ax1.twinx()

    # 设置中文显示
    font_manager.fontManager.addfont(r'C:\Users\lyz13\OneDrive\CloudyLake Programming\MeteoStation of CloudyLake\MeteoStation-of-CloudyLake\MiSans VF.ttf')
    plt.rcParams['font.sans-serif'] = ['MiSans VF']  # 使用misans字体
    plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号

    #标题
    plt.title(title, fontsize=25, fontweight='bold', fontname='Microsoft YaHei')

    # 提取时间列
    time_column = [row[0][11:16] for row in reversed(weather_data[1:])]
    print("Time Column:", time_column)

    # 提取温度列
    temperature_column = [float(row[1]) for row in reversed(weather_data[1:])]
    print("Temperature Column:", temperature_column)
    
    # 绘制温度关系图
    ax1.plot(time_column, temperature_column, color='red', marker='o', label='Temperature')
    ax1.set_xlabel('Time')
    ax1.set_ylabel('Temperature (°C)', color='red')
    ax1.tick_params(axis='y', labelcolor='red')
    
    # 设置y1温度轴的上下端点值
    ax1.set_ylim([min(temperature_column)-5, max(temperature_column)])
    
    # 提取降水量列
    precipitation_column = [float(row[7]) for row in reversed(weather_data[1:])]
    print("Precipitation Column:", precipitation_column)
    # 绘制降水量数据柱状图
    ax2.bar(time_column, precipitation_column, color='lightgreen', label='降水量')
    ax2.set_ylabel('降水量(mm)', color='green')
    ax2.tick_params(axis='y', labelcolor='green')
    
    for i in range(len(time_column)):
        plt.text(time_column[i], precipitation_column[i], str(precipitation_column[i]), ha='center', va='bottom')
    
    # 添加竖线
    for time in time_column:
        plt.axvline(x=time, color='lightblue', linestyle=':', linewidth=1)

    # 提取湿度列，并进行归一化处理（假设湿度范围为0-100）
    humidity_column = [float(row[3])/5 for row in reversed(weather_data[1:])]
    print("Humidity Column:", humidity_column)

    # 显示图形
    plt.savefig('weather.png', dpi=300)
    plt.show()
    plt.close()

# 调用函数并打印结果

def main():
    #生成地址
    number=input("请输入站号：（如：58362）")
    url = 'https://q-weather.info/weather/{}/today/'.format(number)
    if number=='':
        url='https://q-weather.info/weather/58362/today/'
    #获取数据
    title,weather_data = getdata(url)

    #输出
    if weather_data:
        for row in weather_data:
            print(row)
        drawdata(weather_data,title)

main()