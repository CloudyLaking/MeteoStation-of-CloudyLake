# MeteoStation-of-CloudyLake
# 旨在依据能够查询的api搭建一个绘图，然后搭建一个网站，用于查询更加充分展示的实况与预报

### version 1.x 
搭建绘图
# 1.0.1 
当前可以根据输入的站号，从网站上下载数据，输出实况图，包括降水量，湿度，温度
# 1.0.2
计算露点温度和体感温度
露点温度根据Magnus公式
        a = 17.625
        b = 243.04
        gamma = (a * temperature) / (b + temperature) + np.log(humidity / 100.0)
        dewpoint = (b * gamma) / (a - gamma)
        dewpoint_rounded = round(dewpoint, 2)
        dewpoint_column.append(dewpoint_rounded)
调整坐标轴
根据国家标准调整雨量柱的颜色
调整了很多东西
#1.0.3
计算了体感温度加入
根据NOAA公式
并且把代码分区
同时还根据湿度决定体感温度颜色
#1.0.4
转化了站点的pdf放在其中
于是可以计算站点海压
公式：sealevel_pressure = pressure * (1 + (station_height / 44330))**5.255
加入到图中
然后还有修复了很多bug
加上了其他信息
#1.0.5
加水印
绘制风速在下



