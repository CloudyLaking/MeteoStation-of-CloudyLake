# 导入库
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

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
        
        #处理掉data里的'-'，并将其转换为0
        for row in table_data[1:]:
            for i in range(len(row)):
                if row[i] == '-':
                    row[i] = '0'
        # 返回标题和表格数据
        return title, table_data
    else:
        return None, []

# 绘制数据
def drawdata(weather_data,title):

    # 设置图形大小
    fig, ax1 = plt.subplots(figsize=(15, 8))
    ax2 = ax1.twinx()

    # 设置中文显示
    font_manager.fontManager.addfont(r'C:\Users\lyz13\OneDrive\CloudyLake Programming\MeteoStation of CloudyLake\MeteoStation-of-CloudyLake\MiSans VF.ttf')
    plt.rcParams['font.sans-serif'] = ['MiSans VF']  # 使用misans字体
    plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号

    #标题
    plt.title(title, fontsize=25, fontweight='bold', fontname='Microsoft YaHei',pad=20)

    # 提取时间列
    time_column = [row[0][11:16] for row in reversed(weather_data[1:])]
    print("Time Column:", time_column)

    # 提取温度列
    temperature_column = [float(row[1]) for row in reversed(weather_data[1:])]
    print("Temperature Column:", temperature_column)
    # 提取湿度列
    humidity_column = [float(row[3]) for row in reversed(weather_data[1:])]
    print("Humidity Column:", humidity_column)

    # Magnus公式计算露点温度
    dewpoint_column = []
    for temperature, humidity in zip(temperature_column, humidity_column):
        a = 17.625
        b = 243.04
        gamma = (a * temperature) / (b + temperature) + np.log(humidity / 100.0)
        dewpoint = (b * gamma) / (a - gamma)
        dewpoint_rounded = round(dewpoint, 2)
        dewpoint_column.append(dewpoint_rounded)
    print("Dewpoint Column:", dewpoint_column)


    # 绘制温度关系图
    ax1.plot(time_column, temperature_column, color='red', marker='o', label='Temperature')
    ax1.set_xlabel('Time')
    ax1.set_ylabel('Temperature (°C)', color='red')
    ax1.tick_params(axis='y', labelcolor='red')

    
    '''
    ######体感温度
    '''
    def calculate_heat_index(temperature_colomn, humidity_column):
        """
        根据摄氏度和相对湿度计算体感温度（热指数）。
        
        参数:
        - temperature_celsius: 摄氏度温度
        - humidity: 相对湿度（百分比）
        
        返回:
        - 热指数（体感温度）的摄氏度值
        """
        # 将摄氏度转换为华氏度，因为热指数的计算公式基于华氏度
        heat_index_column = []
        for temperature_celsius, humidity in zip(temperature_column, humidity_column):

            temperature_fahrenheit = temperature_celsius * 9 / 5 + 32
        
            # 使用NOAA的热指数公式
            heat_index_fahrenheit = (
                -42.379 + 2.04901523 * temperature_fahrenheit + 10.14333127 * humidity
                - 0.22475541 * temperature_fahrenheit * humidity
                - 6.83783e-3 * temperature_fahrenheit**2
                - 5.481717e-2 * humidity**2
                + 1.22874e-3 * temperature_fahrenheit**2 * humidity
                + 8.5282e-4 * temperature_fahrenheit * humidity**2
                - 1.99e-6 * temperature_fahrenheit**2 * humidity**2
            )
        
            # 将热指数从华氏度转换回摄氏度
            heat_index_celsius = (heat_index_fahrenheit - 32) * 5 / 9
            heat_index_column.append(round(heat_index_celsius, 2))

        return heat_index_column
    heat_index_column = calculate_heat_index(temperature_column, humidity_column)
    ax1.plot(heat_index_column, color='orange', marker='o', label='Heat Index')

    #调整好数据标签
    from adjustText import adjust_text
    # 绘制温度和露点温度、体感温度、湿度数据标签
    for i in range(len(time_column)):
        texts=[]
        
        temperature_text = ax1.annotate(str(temperature_column[i]), (time_column[i], temperature_column[i]), ha='center', va='bottom', xytext=(0, 5), textcoords='offset points')
        dewpoint_text = ax1.annotate(str(dewpoint_column[i]), (time_column[i], temperature_column[i]), ha='center', va='bottom', xytext=(0, -20), textcoords='offset points')
        heat_index_text = ax1.annotate(str(heat_index_column[i]), (time_column[i], max(heat_index_column)), ha='center', va='bottom', xytext=(0, -15), textcoords='offset points')
        humidity_text = ax1.annotate(str(humidity_column[i]), (time_column[i], max(heat_index_column)), ha='center', va='bottom', xytext=(0, 0), textcoords='offset points')
    # 添加图例
    legend_labels = ['温度', '体感温度']
    legend_colors = ['red', 'orange']
    legend_patches = [plt.Rectangle((0, 0), 1, 1, color=color) for color in legend_colors]
    ax1.legend(legend_patches, legend_labels, loc='center left', bbox_to_anchor=(1.05, 0.75))
        

    # 设置y1温度轴的上下端点值
    ax1.set_ylim([min(heat_index_column)-10, max(heat_index_column)])

    '''
    #####降水
    '''
    # 提取降水量列
    precipitation_column = [float(row[7]) for row in reversed(weather_data[1:])]
    print("Precipitation Column:", precipitation_column)

    
    # 初始化累计降水量列表
    cumulative_precipitation_12h = []

    # 遍历precipitation_column来计算每个小时的12小时累计降水量
    for i in range(len(precipitation_column)):
        # 对于前11小时，累计降水量为0
        if i < 12:
            cumulative_precipitation_12h.append(0)
        else:
            # 计算当前小时及之前11小时的累计降水量
            cumulative_precipitation_12h.append(sum(precipitation_column[i-11:i+1]))

    # 根据新的降水量级别为每个12小时累计降水量分配颜色
    def get_precipitation_color(precipitation):
        if precipitation <= 4.9:
            return '#ACEBBF'  # 小雨
        elif precipitation <= 14.9:
            return '#57D875'  # 中雨
        elif precipitation <= 29.9:
            return '#1A9E2D'  # 大雨
        elif precipitation <= 69.9:
            return '#097000'  # 暴雨
        elif precipitation <= 139.9:
            return '#740086'  # 大暴雨
        else:
            return '#E700E0'  # 特大暴雨
    colors_12h = [get_precipitation_color(p) for p in cumulative_precipitation_12h]

    # 加上颜色的图例
    legend_labels = ['小雨', '中雨', '大雨', '暴雨', '大暴雨', '特大暴雨']
    legend_colors = ['#ACEBBF', '#57D875', '#1A9E2D', '#097000', '#740086', '#E700E0']
    legend_patches = [plt.Rectangle((0, 0), 1, 1, color=color) for color in legend_colors]
    ax2.legend(legend_patches, legend_labels, loc='center left', bbox_to_anchor=(1.05, 0.5))
    # 调整子图布局参数
    plt.subplots_adjust(right=0.85) 

    # 绘制12小时累计降水量柱状图
    ax2.bar(time_column, precipitation_column, color=colors_12h, label='降水量')
    
    # 绘制12小时累计降水量柱状图
    ax2.bar(time_column, precipitation_column, color=colors_12h, label='降水量')
    ax2.set_ylabel('降水量(mm)', color='green')
    ax2.tick_params(axis='y', labelcolor='green')
    
    #绘制降水量数据标签
    for i in range(len(time_column)):
        plt.text(time_column[i], precipitation_column[i], str(precipitation_column[i]), ha='center', va='bottom')
    
    #设置y2降水量轴的上下端点值
    ax2.set_ylim([0, max(precipitation_column)*1.8])

    # 添加竖线
    for time in time_column:
        plt.axvline(x=time, color='lightblue', linestyle=':', linewidth=1)

    # 显示图形
    fig.tight_layout()
    plt.savefig('weather.png', dpi=300)
    plt.show()
    plt.close()

# 调用函数并打印结果

def main():
        # 生成地址
        number = input("请输入站号：（如：58362）：")
        url = 'https://q-weather.info/weather/{}/today/'.format(number)
        if number == '':
            url = 'https://q-weather.info/weather/58362/today/'
        # 获取数据
        title, weather_data = getdata(url)


        # 输出
        if weather_data:
            for row in weather_data:
                print(row)
            drawdata(weather_data, title)

if __name__ == "__main__":
    main()