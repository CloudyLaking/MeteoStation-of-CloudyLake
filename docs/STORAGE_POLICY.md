# 生产存储策略

生产根盘约 50 GB，目标长期使用率低于 70%–75%，保留下载峰值和回滚空间。

## 分层

- `data/raw/`：实测原始报文、来源元数据和必要 ECMWF 输入；不由通用清理脚本删除。
- `data/products/`：轻量归一化结果、统计、轨迹和聚类。完整全球成员场不得长期写入这里。
- `data/cache/`、`data/tmp/`：可再生查询结果和临时文件，超过 7 天自动清理。
- `.part`：不在 `data/raw/` 下且超过 2 天的中断临时文件可清理。

`scripts/storage_maintenance.py` 默认 dry-run；systemd timer 仅调用 `--apply`，且只选取上述明确的可再生目录/临时文件，不选取原始观测、WIS2 BUFR、ECMWF 归档或 `.env`。每次上线前仍应执行 dry-run 并保存输出。

## 集合产品

AIFS ENS、WeatherNext 2 与 WeatherNext Cyclones 的即时处理只接收任务所需的派生字段，任务成功、失败或超时都清理临时文件；长期保存起报时间、成员计数、分位数、概率、轨迹、身份映射、聚类和检验结果，不保存完整全球三维成员场。WNC 1000 条轨迹可保存，成员格点场只能临时处理。

系统日志限制为 512 MB、最长 14 天，并至少给根盘保留 5 GB。IFS/AIFS 仍各保留当前与上一完整周期，避免以牺牲线上回退能力换取短期空间；这部分约占 15 GB。若根盘逼近阈值，先清理日志、过期临时文件和已过宽限期的退役周期，再考虑减少完整周期。

服务安装：

```bash
sudo cp deploy/meteostation-storage.service deploy/meteostation-storage.timer /etc/systemd/system/
sudo install -D -m 0644 deploy/meteostation-journald.conf /etc/systemd/journald.conf.d/meteostation-storage.conf
sudo systemctl restart systemd-journald
sudo systemctl daemon-reload
sudo systemctl enable --now meteostation-storage.timer
sudo -u meteostation .venv/bin/python scripts/storage_maintenance.py --dry-run
```
