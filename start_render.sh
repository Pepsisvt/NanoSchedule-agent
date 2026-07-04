#!/bin/bash
set -e
echo "[render] NanoSchedule starting..."

# 从环境变量生成 nanobot 配置
mkdir -p /root/.nanobot

if [ -n "$DEEPSEEK_API_KEY" ]; then
  cat > /root/.nanobot/config.json << EOF
{
  "agents": {"defaults": {"workspace": "/app/workspace", "model": "deepseek-chat", "provider": "deepseek", "timezone": "Asia/Shanghai"}},
  "providers": {"deepseek": {"apiKey": "$DEEPSEEK_API_KEY", "apiBase": "https://api.deepseek.com"}},
  "channels": {"websocket": {"enabled": true, "host": "0.0.0.0", "token": "schedule123"}, "feishu": {"enabled": false}},
  "gateway": {"host": "0.0.0.0", "port": 18790},
  "tools": {"web": {"enable": true}, "exec": {"enable": false}, "file": {"enable": true}}
}
EOF
  echo "[render] Config generated from DEEPSEEK_API_KEY"
else
  echo "[render] WARNING: DEEPSEEK_API_KEY not set!"
fi

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
