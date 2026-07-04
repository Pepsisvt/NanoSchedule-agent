#!/bin/bash
# NanoSchedule Render 启动脚本

echo "=== NanoSchedule Render Start ==="
echo "HOME=$HOME PORT=$PORT"

# ── 1. 生成 nanobot 配置 ──
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
  echo "[OK] nanobot config created"
else
  echo "[WARN] DEEPSEEK_API_KEY not set — Agent will not work!"
fi

# ── 2. 初始化数据库 ──
if python -c "from nanobot_calendar import db; db.init_db()" 2>&1; then
    echo "[OK] DB ready"
else
    echo "[WARN] DB init failed, continuing anyway"
fi

# ── 3. 启动 nanobot gateway（后台）──
export HOME=/root
nohup nanobot gateway > /tmp/gateway.log 2>&1 &
echo "[OK] Gateway starting (pid $!)..."
sleep 4

if netstat -tlnp 2>/dev/null | grep -q 18790; then
    echo "[OK] Gateway listening on 18790"
else
    echo "[WARN] Gateway may not be running — check /tmp/gateway.log"
fi

# ── 4. 先启动 PWA 后端（后台），等它就绪后再启 nginx ──
#     这样 nginx 启动时后端已就绪，Render 健康检查不会收到 502
python serve_pwa.py &
PWA_PID=$!
echo "[INFO] PWA server starting (pid $PWA_PID)..."

# 等待 PWA 就绪（最多等 60 秒）
READY=0
for i in $(seq 1 60); do
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/ 2>/dev/null | grep -q "200\|302\|404"; then
        echo "[OK] PWA server ready after ${i}s"
        READY=1
        break
    fi
    sleep 1
done

if [ "$READY" -eq 0 ]; then
    echo "[WARN] PWA server not responding after 60s — starting nginx anyway"
fi

# ── 5. 生成 nginx 配置并启动 ──
NGINX_PORT="${PORT:-10000}"
mkdir -p /etc/nginx/conf.d

cat > /etc/nginx/conf.d/default.conf << NGINXEOF
server {
    listen ${NGINX_PORT};

    # 健康检查 — nginx 直接响应，不依赖后端
    location /health {
        access_log off;
        return 200 "OK";
        add_header Content-Type text/plain;
    }

    # WebSocket → gateway
    location /ws {
        proxy_pass http://127.0.0.1:18790;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400;
    }

    # API → PWA 后端
    location /api/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # 前端 → PWA 后端
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINXEOF
echo "[OK] nginx config written for port ${NGINX_PORT}"

if nginx -t 2>&1; then
    nginx
    echo "[OK] nginx started on port ${NGINX_PORT}"
else
    echo "[FATAL] nginx config test failed"
    cat /etc/nginx/conf.d/default.conf
    exit 1
fi

echo "=== NanoSchedule Ready ==="

# ── 6. 前台等待 PWA 进程（Docker 需要前台进程）──
wait $PWA_PID
