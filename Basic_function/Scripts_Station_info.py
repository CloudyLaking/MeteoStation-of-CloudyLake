# 导入库
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from matplotlib import font_manager
import matplotlib.gridspec as gridspec
import numpy as np
import datetime
import pathlib
import time
import os

version = '1.2.2'

# 请求气象数据
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
        return table_data
    else:
        return []

# 得到站点信息
def get_station_infos():
    # 从文本文件中提取站点信息
    folder = pathlib.Path(__file__).parent.resolve()
    with open(f'{folder}/station info.txt', 'r', encoding='utf-8') as file:
        station_infos = file.read()
    # 分割列
    station_infos = station_infos.split('\n')
    #分割每一行
    station_infos = [info.split(' ') for info in station_infos]
    return station_infos

# 寻找站点信息
def find_station_info(number, station_info):
    #寻找
    for station in station_info[1:]:
        if number.isdigit() and len(number) == 5:
            if number in station[1]:
                return station, number
        else :
            if number in station[2] and number !='':
                return station, station[1]
            else:
                pass
    return ['上海', '58362', '宝山', '3139', '12145', '4.5', '3.3'], '58362'

# 绘制数据
def drawdata(weather_data,station_info):
    '''
    #####图像初始化
    '''
    def init_chart():
        # 设置图形大小
        global fig, ax1, ax2 ,ax3 ,ax4 ,ax5
        fig= plt.figure(figsize=(15, 9))
        # 定义GridSpec：2行1列
        gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1])
        ax1 = fig.add_subplot(gs[0])
        # 创建ax4,ax5

        ax4 = fig.add_subplot(gs[1])
        ax5 = ax4.twinx()
        #确保与ax1的x轴对齐
        
        # 将ax4的x轴刻度和标签移动到上方并且隐藏数据
        ax4.xaxis.tick_top()
        ax4.xaxis.set_label_position('top')
        ax4.set_xticklabels([])
        # 调整子图布局参数
        plt.subplots_adjust(left=0.12)
        #ax4和ax1之间距离
        plt.subplots_adjust(hspace=0.08)
        ax3 = ax1.twinx()
        ax2 = ax1.twinx()
        # 隐藏第三个y轴的刻度和标签
        ax3.get_yaxis().set_visible(False)
        # 隐藏第三个y轴的轴线
        ax3.spines['right'].set_visible(False)
        # 设置中文显示
        import pathlib
        folder = pathlib.Path(__file__).parent.resolve()
        font_manager.fontManager.addfont(f'{folder}/MiSans VF.ttf')
        plt.rcParams['font.sans-serif'] = ['MiSans VF']

        # 标题
        plt.title(f'{station_info[0]}{station_info[2]}站(#{station_info[1]})24h实况序列', fontsize=25, fontweight='bold', pad=22)   
        # 绘制经纬度与查询时次
        plt.text(-0.15, 1.11, f'''{station_info[3][:2]}°{station_info[3][2:4]}'N   {station_info[4][:-2]}°{station_info[4][-2:]}\'E\n查询时次: {weather_data[1][0]}''', transform=ax1.transAxes, fontsize=12, ha='left', va='top')
        # 上水印
        plt.text( 1.15, 1.1,f'''By @CloudyLake\nVersion:{version}''', transform=ax1.transAxes, fontsize=12, ha='right', va='top')
    init_chart()
    print('图像初始化完成')
    '''
    #####提取数据
    '''
    def init_data():
        global time_column, temperature_column, humidity_column, dewpoint_column, heat_index_column, precipitation_column,pressure_column,sealevel_pressure_column,wind_speed_column,wind_direction_column,max_wind_speed_column,visibility_column
        #统一提取源数据
        for i1 in range(len(weather_data[0])):
            for key in ['时次','瞬时温度', '相对湿度', '地面气压', '瞬时风向','2分钟平均风向', '瞬时风速','2分钟平均风速', '1小时降水', '10分钟平均能见度', '1小时极大风速']:
                # 提取时间列
                if weather_data[0][i1] == key and key == '时次':
                    time_column = [row[i1][11:16] for row in reversed(weather_data[1:])]
                # 提取温度列
                if weather_data[0][i1] == key and key == '瞬时温度':
                    temperature_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                # 提取湿度列
                if weather_data[0][i1] == key and key == '相对湿度':
                    humidity_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                # 提取降水量列
                if weather_data[0][i1] == key and key == '1小时降水':
                    precipitation_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                # 提取气压列
                if weather_data[0][i1] == key and key == '地面气压':
                    pressure_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                # 提取风向列
                if weather_data[0][i1] == key and( key == '瞬时风向' or key == '2分钟平均风向'):
                    wind_direction_column = [row[i1] if row[i1] != '-' and row[i1] != '' else '0' for row in reversed(weather_data[1:])]
                # 提取风速列
                if weather_data[0][i1] == key and (key == '瞬时风速' or key == '2分钟平均风速'):
                    if weather_data[1][i1][0].isdigit():
                        wind_speed_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                    else:
                        wind_speed_column = [float(row[i1][1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                #提取最大风速列
                if weather_data[0][i1] == key and key == '1小时极大风速':
                    max_wind_speed_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
                # 提取能见度列
                if weather_data[0][i1] == key and key == '10分钟平均能见度':
                    visibility_column = [float(row[i1]) if row[i1] != '-' and row[i1] != '' else 0 for row in reversed(weather_data[1:])]
        #处理湿度
        if humidity_column[-1] == 0:
            humidity_column[-1] = humidity_column[-2]
        # Magnus公式计算露点温度
        def calculate_dewpoint(temperature_column, humidity_column):
            """
            根据温度和湿度计算露点温度。

            参数:
            - temperature_column: 温度列表（摄氏度）
            - humidity_column: 湿度列表（百分比）

            返回:
            - 露点温度列表（摄氏度）
            """
            dewpoint_column = []
            for temperature, humidity in zip(temperature_column, humidity_column):
                a = 17.625
                b = 243.04
                gamma = (a * temperature) / (b + temperature) + np.log(humidity / 100.0)
                dewpoint = (b * gamma) / (a - gamma)
                dewpoint_rounded = round(dewpoint, 2)
                dewpoint_column.append(dewpoint_rounded)
            return dewpoint_column
        dewpoint_column = calculate_dewpoint(temperature_column, humidity_column)
        # 计算体感温度
        def calculate_heat_index(temperature_column, humidity_column):
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
                humidity = humidity / 100.0
                temperature_fahrenheit = temperature_celsius * 9 / 5 + 32
            
                # 简化公式计算热指数
                simple_hi_fahrenheit = 0.5 * (temperature_fahrenheit + 61.0 + ((temperature_fahrenheit - 68.0) * 1.2) + (humidity * 100 * 0.094))
            
                # 如果简化公式计算的热指数大于等于80°F，使用完整的回归方程
                if simple_hi_fahrenheit >= 80:
                    heat_index_fahrenheit = (
                        -42.379 + 2.04901523 * temperature_fahrenheit + 10.14333127 * humidity * 100
                        - 0.22475541 * temperature_fahrenheit * humidity * 100
                        - 6.83783e-3 * temperature_fahrenheit**2
                        - 5.481717e-2 * (humidity * 100)**2
                        + 1.22874e-3 * temperature_fahrenheit**2 * humidity * 100
                        + 8.5282e-4 * temperature_fahrenheit * (humidity * 100)**2
                        - 1.99e-6 * temperature_fahrenheit**2 *(humidity * 100)**2
                    )
            
                    # 应用特定条件下的调整
                    if humidity < 0.13 and 80 <= temperature_fahrenheit <= 112:
                        adjustment = ((13 - humidity * 100) / 4) * ((17 - abs(temperature_fahrenheit - 95)) / 17)**0.5
                        heat_index_fahrenheit -= adjustment
                    elif humidity > 0.85 and 80 <= temperature_fahrenheit <= 87:
                        adjustment = ((humidity * 100 - 85) / 10) * ((87 - temperature_fahrenheit) / 5)
                        heat_index_fahrenheit += adjustment
                else:
                    heat_index_fahrenheit = simple_hi_fahrenheit
            
                # 将热指数从华氏度转换回摄氏度
                heat_index_celsius = (heat_index_fahrenheit - 32) * 5 / 9
                heat_index_column.append(round(heat_index_celsius, 2))

            return heat_index_column
        heat_index_column = calculate_heat_index(temperature_column, humidity_column)
        #处理气压
        if pressure_column[-1] == 0 :
            pressure_column[-1] = pressure_column[-2]
        for pressure in pressure_column:
            if pressure == '-':
                pressure = 500.0
        #计算海平面气压
        station_height=float(station_info[5])
        def calculate_sealevel_pressure(pressure_column, station_height=0):
            """
            根据气压和站点高度计算海平面气压。
            参数:
            - pressure_column: 气压列表（hPa）
            - station_height: 站点高度（m）

            返回:
            - 海平面气压列表（hPa）
            """
            sealevel_pressure_column = []
            for pressure in pressure_column:
                sealevel_pressure = pressure * (1 + (station_height / 44330))**5.255
                sealevel_pressure_column.append(round(sealevel_pressure, 2))
                #保留一位小数
                sealevel_pressure_column = [round(p, 1) for p in sealevel_pressure_column]
            return sealevel_pressure_column
        sealevel_pressure_column = calculate_sealevel_pressure(pressure_column, station_height)
        #处理无持续风向与分隔风向
        for i in range(len(wind_direction_column)):
            if wind_direction_column[i] == '-':
                wind_direction_column[i] = ['0','0']
            #以'/'为分隔分开为一个列表
            wind_direction_column[i] = wind_direction_column[i].split('/') if '/' in wind_direction_column[i] else wind_direction_column[i]
    init_data()
    print('该站点数据列提取完成')

    '''
    #####气压
    '''
    def draw_pressure():
        # 绘制气压粗柱状图
        width = 1  # 可以根据需要调整柱状图的宽度
        ax3.bar(time_column, pressure_column, width, color='#DBDBFF', label='气压',zorder=1)
        ax3.set_ylabel('气压(hPa)', color='blue')
        ax3.tick_params(axis='y', labelcolor='blue')
        # 绘制气压与海平面数据标签
        diff = max(pressure_column) - min(pressure_column)
        for i, value in enumerate(pressure_column):
            # 仅在第一个数据点旁添加说明
            if i == -1:
                ax3.annotate('气压(hPa):                        ', (time_column[i], value), ha='right', va='bottom', xytext=(10, 0), textcoords='offset points', fontsize=9)
                ax3.annotate(str(value), (time_column[i], value), ha='right', va='bottom', xytext=(10, 0), textcoords='offset points', fontsize=9)
                ax3.annotate('海平面气压(hPa):                        ', (time_column[i], sealevel_pressure_column[i]), ha='right', va='bottom', xytext=(10, 0), textcoords='offset points', fontsize=9)
            else:
                ax3.annotate(str(value),                       (time_column[i], value),                       ha='center', va='bottom', xytext=(0, 0), textcoords='offset pixels', fontsize=9)
                ax3.annotate(str(sealevel_pressure_column[i]), (time_column[i], value), ha='center', va='bottom', xytext=(0, -60), textcoords='offset pixels', fontsize=9)
        # 设置y轴的上下端点值
        diff = max(pressure_column) - min(pressure_column)
        ax3.set_ylim([min(pressure_column)-diff*3, max(pressure_column) + diff * 4.5]) 
    draw_pressure()
    print('气压数据绘制完成')
    '''
    ######温度，露点温度与体感温度，湿度
    '''
    # 绘制温度图
    def draw_temperature_dewpoint_heatindex_humidity():
        global temperature_column
        try:
            w=temperature_column[0]
        except:
            temperature_column = [0]*24
        #绘制体感温度关系图
        ax1.plot(time_column, heat_index_column, color='orange', marker='o', label='Heat Index', zorder=2)

        from matplotlib.colors import LinearSegmentedColormap
    
        # 定义橙色到蓝色的颜色映射
        colors = ["#FF5900", "#3EE8D2"]  # 从橙色渐变到蓝色
        cmap_name = "humidity_cmap"
        n_bins = 100  # 颜色条中的颜色数量
        cmap = LinearSegmentedColormap.from_list(cmap_name, colors, N=n_bins)
    
        # 归一化湿度数据
        normalized_humidity_column = [h/100 for h in humidity_column]
    
        # 使用获取的颜色绘制体感温度点
        ax1.scatter(time_column, heat_index_column, c=[cmap(h) for h in normalized_humidity_column], s=150, label='Humidity', zorder=2)

        # 绘制温度关系图覆盖在上
        ax1.plot(time_column, temperature_column, color='red', marker='o', label='Temperature', zorder=3)
        ax1.set_ylabel('实况温度(°C)',)
        ax1.tick_params(axis='y')

        # 设置y1温度轴的上下端点值
        diff=max(temperature_column+heat_index_column)-min(temperature_column+heat_index_column)
        ax1.set_ylim([min(heat_index_column)-diff*1.8, max(heat_index_column)+diff*0.5])

        # 绘制温度和露点温度、体感温度、湿度数据标签
        for i in range(len(time_column)):
            texts=[]

            # 仅在第一个数据点旁添加说明
            if i == 0:
                ax1.annotate('温度(°C) \n\n' + str(temperature_column[i]), (time_column[i], temperature_column[i]), ha='center', va='bottom', xytext=(0, 5), textcoords='offset points')
                ax1.annotate( str(dewpoint_column[i])+'\n\n露点温度(°C) ', (time_column[i], temperature_column[i]), ha='center', va='top', xytext=(0, -10), textcoords='offset points')
                ax1.annotate('湿度(%):                  ' + str(humidity_column[i]), (time_column[i], max(heat_index_column)+diff*0.5), ha='right', va='bottom', xytext=(10, 0), textcoords='offset points')
                ax1.annotate('体感温度(°C):                  ' + str(heat_index_column[i]), (time_column[i],max(heat_index_column)+diff*0.5), ha='right', va='bottom', xytext=(10, -15), textcoords='offset points')
            else:
                ax1.annotate(str(temperature_column[i]), (time_column[i], temperature_column[i]), ha='center', va='bottom', xytext=(0, 5), textcoords='offset points')
                ax1.annotate(str(dewpoint_column[i]), (time_column[i], temperature_column[i]), ha='center', va='bottom', xytext=(0, -20), textcoords='offset points')
                ax1.annotate(str(heat_index_column[i]), (time_column[i], max(heat_index_column)+diff*0.5), ha='center', va='bottom', xytext=(0, -15), textcoords='offset points')
                ax1.annotate(str(humidity_column[i]), (time_column[i], max(heat_index_column)+diff*0.5), ha='center', va='bottom', xytext=(0, 0), textcoords='offset points')

        # 添加图例
        # 左侧湿度颜色映射
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=100))
        sm.set_array([])
        cbar_ax = fig.add_axes([0.02, 0.15, 0.02, 0.73])  # 这里的数字分别代表[左, 下, 宽, 高]
        cbar = fig.colorbar(sm, cax=cbar_ax)
        cbar.set_label('湿度映射(%)')
        # 右侧温度和体感温度图例/降雨等级
        from matplotlib.lines import Line2D
        legend_labels = ['温度', '体感温度']
        legend_colors = ['red', 'orange']
        legend_lines = [Line2D([0], [0], color=color, lw=2) for color in legend_colors]
        ax1.legend(legend_lines, legend_labels, loc='center left', bbox_to_anchor=(1.05, 0.75))
    draw_temperature_dewpoint_heatindex_humidity()
    print('温度，露点温度，体感温度，湿度数据绘制完成')
    '''
    #####降水
    '''
    #做累计降水量
    def get_precipitation_color():
        # 初始化累计降水量列表
        cumulative_precipitation_12h = []

        # 遍历precipitation_column来计算每个小时的12小时累计降水量
        for i in range(len(precipitation_column)):
            cumulative_precipitation_12h.append(sum(precipitation_column[:i+1]))

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
        return colors_12h
    # 绘制降水量柱状图
    def draw_precipitation_bar():
        # 背景画上浅蓝浅黄交替竖线定位竖列
        for i in range(len(time_column)):
            ax2.axvline(x=time_column[i], color='lightblue', linestyle=':', linewidth=2)


        ax2.bar(time_column, precipitation_column, color=colors_12h, label='降水量')
    
        ax2.set_ylabel('降水量(mm)', color='green')
        ax2.tick_params(axis='y', labelcolor='green')
        
        # 绘制温度和露点温度、体感温度、湿度数据标签
        for i in range(len(time_column)):
            # 仅在第一个数据点旁添加说明
            if i == 0: 
                ax2.annotate(str(precipitation_column[i]), (time_column[i],precipitation_column[i]), ha='right', va='bottom', xytext=(10, 0), textcoords='offset points')
            else:
                ax2.annotate(str(precipitation_column[i]), (time_column[i], precipitation_column[i]), ha='center', va='bottom', xytext=(0, 0), textcoords='offset points')
        ax2.text(-0.02, -0.02, '降水量(mm):\n时次:', transform=ax2.transAxes, fontsize=10, ha='right')
        #设置y2降水量轴的上下端点值
        ax2.set_ylim([0, max(precipitation_column)*4]) if max(precipitation_column)>0 else ax2.set_ylim([0, 1])

        # 添加竖线
        for time in time_column:
            plt.axvline(x=time, color='lightblue', linestyle=':', linewidth=1)
    #右上角添加累计降水量数据
    def write_precipitation_data():
        # 计算最近6h累计降水量
        precipitation_6h = sum([float(p) for p in precipitation_column[-6:]])
        #计算最近12h累计降水量
        precipitation_12h = sum([float(p) for p in precipitation_column[-12:]])
        # 计算最近24h累计降水量
        precipitation_24h = sum([float(p) for p in precipitation_column[:]])
        # 添加累计降水量数据
        plt.text(1.00, 1.04, \
             '近6h累计降水量: {} mm\n近12h累计降水量: {} mm\n近24h累计降水量: {} mm'.\
             format(precipitation_6h,precipitation_12h,precipitation_24h),\
             transform=ax2.transAxes, fontsize=8, ha='right')
    try:
        w = precipitation_column[0]
        colors_12h=get_precipitation_color()
        draw_precipitation_bar()
        write_precipitation_data()
    except:
        pass
    
    
    print('降水数据绘制完成')
    '''
    #####风向风速
    '''
    def draw_wind_with_arrows():
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        from matplotlib.transforms import Affine2D
        from PIL import Image
        
        global wind_speed_column
        #如果风速列查询出现错误，用极大风代替
        try:
            w = wind_speed_column[0]
        except:
            wind_speed_column = max_wind_speed_column

        #背景竖线
        for i in range(len(time_column)):
            ax4.axvline(x=time_column[i], color='lightblue', linestyle=':', linewidth=2)

        # 读取风向标图像
        
        folder = pathlib.Path(__file__).parent.resolve()
        img = Image.open(f"{folder}/画板 1.png")
        img.format

        # 更新ax4的x轴范围以匹配ax1
        ax4.set_xlim(ax1.get_xlim())
        ax4.plot(time_column, wind_speed_column, color='lightblue', marker='o', label='风速', zorder=1)
        ax4.set_ylabel('风速(m/s)', color='black')
        ax4.tick_params(axis='y', labelcolor='black')
        diff=max(wind_speed_column)-min(wind_speed_column)
        ax4.set_ylim([min(wind_speed_column)-diff*2, max(wind_speed_column)+diff*1])

        #画箭头
        for i in range(len(time_column)):
            if wind_direction_column[i] != '0':
                # 旋转箭头图像
                img_rotated = img.rotate(-float(wind_direction_column[i][0])+180)
                # 创建图像注释
                imagebox = OffsetImage(img_rotated, zoom=0.045)
                ab = AnnotationBbox(imagebox, (time_column[i], wind_speed_column[i]), frameon=False)
                ax4.add_artist(ab)
        
        #添加风速标签
        for i in range(len(time_column)):
            if wind_direction_column[i] != '0':
                ax4.annotate(str(wind_speed_column[i]), (time_column[i], wind_speed_column[i]), ha='center', va='bottom', xytext=(0, 10), textcoords='offset points')

        #画一条0风速线
        ax4.axhline(0, color='black',linestyle = '--', linewidth=1)
    draw_wind_with_arrows()
    print('风向风速数据绘制完成')
    '''
    #####能见度
    '''
    def draw_visibility():
        try:
            w = visibility_column[0]
        except:
            return None
        ax5.bar(time_column, visibility_column, color='#B8B8B8AA', label='能见度')
        ax5.set_ylabel('能见度(km)', color='black')
        ax5.tick_params(axis='y', labelcolor='grey')
        diff=max(visibility_column)-min(visibility_column)
        ax5.set_ylim([0, max(visibility_column)+diff*5.5])
        for i in range(len(time_column)):
            ax5.annotate(str(visibility_column[i]), (time_column[i], visibility_column[i]), ha='center', va='bottom', xytext=(0, 10), textcoords='offset points', fontsize=9)
    draw_visibility()
    print('能见度数据绘制完成')
    '''
    #####保存图片
    '''

    # 获取当前脚本文件的绝对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 生成图片的完整路径
    image_path = os.path.join(script_dir, f'{station_info[1]}.png')

    # 保存图片到指定路径
    plt.savefig(image_path, dpi=300)
    print(f'图片已保存至 {image_path}')
    plt.close()

# 主函数
def main(index):
    global error_log, station_infos

    # 站点
    for station_info in station_infos[index:index]:
        print('第',index,'/2169个站点')
        index += 1
        number = station_info[1]
        # 生成url
        url = f'https://q-weather.info/weather/{number}/today/'
        print('该站点信息提取完成:\n',station_info,'\n开始获取站点数据...')


        # 获取站点数据
        for i in range(100):
            try:    
                weather_data = getdata(url)
                print(f'站点数据获取完成\n第一组:{weather_data[0]}\n最近一组:{weather_data[1]}\n开始绘制数据...')
                break
            except Exception as e:
                print("发生错误：", e)
                print("正在再次尝试。")


        # 当前时间
        current_time = datetime.datetime.now()
        print("获取时间：", current_time)

        if weather_data:
            try:
                drawdata(weather_data,station_info)  
            except Exception as e:
                print("绘制数据时发生错误：", e)
                error_log.append(station_info[1]+station_info[2])
            

if __name__ == "__main__":
    index0 = int(input('请输入开始序号:'))
    # 错误日志
    error_log = []
    # 站点信息
    station_infos = get_station_infos()
    
    index = index0
    for i in range(10000000000):
        for index in range(index0,2169):
            main(index)