from flask import Flask
import History_Station_info  # 假设这是你的脚本名

app = Flask(__name__)

@app.route('/run-visualization')
def run_visualization():
    # 这里调用你的可视化函数
    # 假设你的可视化代码封装在一个函数中，比如 visualize()
    History_Station_info.main()
    return '可视化完成'

if __name__ == '__main__':
    app.run(debug=True)