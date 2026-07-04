#!/bin/bash
set -e
echo "[render] NanoSchedule starting..."

# 启动 nginx
nginx
echo "[render] nginx ready"

# 初始化数据库
python -c "from nanobot_calendar import db; db.init_db()"

# 启动 gateway (后台)
nanobot gateway &
sleep 5
echo "[render] gateway ready"

# 启动 PWA (前台)
python serve_pwa.py
