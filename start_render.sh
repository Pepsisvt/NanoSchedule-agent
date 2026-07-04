#!/bin/bash
set -e

echo "=== NanoSchedule Render Start ==="
echo "HOME=$HOME PORT=$PORT"

# 从环境变量生成配置
mkdir -p /root/.nanobot

if [ -n "$DEEPSEEK_API_KEY" ]; then
  cat > /root/.nanobot/config.json << ENDCONFIG
{
  "agents": {"defaults": {"workspace": "/app/workspace", "model": "deepseek-chat", "provider": "deepseek", "timezone": "Asia/Shanghai", "maxTokens": 2048}},
  "providers": {"deepseek": {"apiKey": "$DEEPSEEK_API_KEY", "apiBase": "https://api.deepseek.com"}},
  "channels": {"websocket": {"enabled": true, "host": "0.0.0.0", "token": "schedule123"}, "feishu": {"enabled": false}},
  "gateway": {"host": "0.0.0.0", "port": 18790},
  "tools": {"web": {"enable": true}, "exec": {"enable": false}, "file": {"enable": true}}
}
ENDCONFIG
  echo "[OK] Config created"
else
  echo "[WARN] DEEPSEEK_API_KEY not set — Agent will not work!"
fi

# 将 Render 分配的端口注入 nginx 配置
sed -i "s/__PORT__/${PORT:-10000}/g" /etc/nginx/conf.d/default.conf
echo "[OK] nginx port set to ${PORT:-10000}"

# 启动 nginx
nginx -t && nginx
echo "[OK] nginx started"

# 初始化数据库
python -c "from nanobot_calendar import db; db.init_db()"
echo "[OK] DB ready"

# 启动 gateway（后台输出到日志）
export HOME=/root
nohup nanobot gateway > /tmp/gateway.log 2>&1 &
echo "[OK] Gateway starting..."
sleep 6

# 检查 gateway 是否存活
if netstat -tlnp 2>/dev/null | grep -q 18790; then
    echo "[OK] Gateway listening on 18790"
else
    echo "[WARN] Gateway may not be running!"
    cat /tmp/gateway.log | tail -20
fi

# 启动 PWA（前台）
exec python serve_pwa.py
