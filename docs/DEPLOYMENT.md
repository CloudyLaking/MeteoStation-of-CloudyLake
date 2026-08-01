# 服务器部署

首版生产结构为：Nginx 处理域名与 HTTPS，FastAPI 提供页面和 API，探空实况
采集器与 ECMWF 预报采集器分别作为独立 systemd 服务运行。

以下示例面向 Ubuntu/Debian，假定项目位于 `/opt/meteostation`，运行用户为
`meteostation`。正式操作前先为服务器创建快照或备份。

## 1. 服务器与磁盘

建议至少：

- 4 vCPU、8 GB RAM；
- 系统盘之外预留至少 80 GB 数据空间；
- Python 3.11 或 3.12；
- Nginx、Git、ecCodes 系统库。

前期生产配置让 IFS 0–144 h逐 3 h与 AIFS 0–144 h逐 6 h各保留四个
完整起报时次，约等于一天，按实测索引估算约 10 GiB。还应为临时下载、
索引和未来产品留出余量，并监控 `data/raw/ecmwf_forecast/`。

## 2. 安装

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential libeccodes0 nginx git
sudo useradd --system --create-home --shell /usr/sbin/nologin meteostation
sudo mkdir -p /opt/meteostation
sudo chown meteostation:meteostation /opt/meteostation
```

把仓库同步到 `/opt/meteostation` 后：

```bash
cd /opt/meteostation
sudo -u meteostation python3 -m venv .venv
sudo -u meteostation .venv/bin/python -m pip install --upgrade pip
sudo -u meteostation .venv/bin/python -m pip install -r requirements-web.txt
sudo -u meteostation .venv/bin/python -m pip install -r requirements-weather-map.txt
sudo -u meteostation cp .env.example .env
```

在 `.env` 中填写天地图令牌。不要把真实令牌和 ECMWF 凭据提交到仓库。
当前预报采集器使用 ECMWF Open Data，不依赖无 MARS 权限的
`~/.ecmwfapirc`。

## 3. 先做本机验收

```bash
sudo -u meteostation .venv/bin/python -m uvicorn web.app:app \
  --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/api/v1/health
```

健康检查应返回 `"status": "ok"`。随后停止前台进程，再安装服务。

## 4. systemd 服务

```bash
sudo cp deploy/meteostation-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now meteostation-web
sudo systemctl enable --now meteostation-sounding-collector
sudo systemctl enable --now meteostation-forecast-collector
```

查看状态和最近日志：

```bash
sudo systemctl status meteostation-web
sudo journalctl -u meteostation-web -n 100 --no-pager
sudo journalctl -u meteostation-sounding-collector -n 100 --no-pager
sudo journalctl -u meteostation-forecast-collector -n 100 --no-pager
```

只运行一个预报采集器实例；多个实例会重复下载同一模式资料。

## 5. Nginx、域名与 HTTPS

先把 `meteostation.top` 和 `www.meteostation.top` 的 DNS A/AAAA 记录指向服务器，
再安装配置：

```bash
sudo cp deploy/nginx-meteostation.conf /etc/nginx/sites-available/meteostation
sudo ln -s /etc/nginx/sites-available/meteostation /etc/nginx/sites-enabled/meteostation
sudo nginx -t
sudo systemctl reload nginx
```

确认 HTTP 可访问后，可使用 Certbot 自动取得证书并修改 Nginx 配置：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d meteostation.top -d www.meteostation.top
```

## 6. 更新与回滚

每次更新前备份 `.env`、`data/` 和当前提交号。同步代码后执行：

```bash
cd /opt/meteostation
sudo -u meteostation .venv/bin/python -m pip install -r requirements-web.txt
sudo -u meteostation .venv/bin/python -m pytest -q
sudo systemctl restart meteostation-web
sudo systemctl restart meteostation-sounding-collector
sudo systemctl restart meteostation-forecast-collector
curl --fail http://127.0.0.1:8765/api/v1/health
```

如果验收失败，恢复上一提交及对应依赖，再重启服务。不要删除 `data/raw/`；
其中包含探空归档和已下载的 ECMWF 周期。
