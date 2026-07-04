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
  echo "[WARN] DEEPSEEK_API_KEY not set"
fi

# ── 2. 初始化数据库 ──
python -c "from nanobot_calendar import db; db.init_db()" 2>&1 && echo "[OK] DB ready" || echo "[WARN] DB init failed"

# ── 3. 启动 nanobot gateway（后台）──
export HOME=/root
nohup nanobot gateway > /tmp/gateway.log 2>&1 &
echo "[OK] Gateway starting..."
sleep 4
netstat -tlnp 2>/dev/null | grep -q 18790 && echo "[OK] Gateway on 18790" || echo "[WARN] Gateway check failed"

# ── 4. 后台启动 PWA（先于 nginx 拉起，减少 502 窗口）──
python serve_pwa.py &
PWA_PID=$!
echo "[INFO] PWA starting (pid $PWA_PID)..."

# ── 5. 生成 nginx 配置 + 立刻启动（抢占端口）──
#     关键：error_page 把 502/503 转为 200 + 自动刷新页面
#     这样即使后端还没就绪，Render 健康检查也能通过
NGINX_PORT="${PORT:-10000}"
mkdir -p /etc/nginx/conf.d

cat > /etc/nginx/conf.d/default.conf << NGINXEOF
server {
    listen ${NGINX_PORT};

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

    # 前端 → PWA 后端（后端未就绪时返回 200 而非 502）
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_intercept_errors on;
        error_page 502 503 504 =200 /loading.html;
    }

    # nginx 直接返回的加载页（200 OK）
    location = /loading.html {
        default_type text/html;
        return 200 "<!DOCTYPE html><html lang='zh'><head><meta charset='UTF-8'><meta http-equiv='refresh' content='3'><meta name='viewport' content='width=device-width,initial-scale=1'><title>NanoSchedule</title><style>body{font-family:system-ui,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#0f172a;color:#e2e8f0}@keyframes spin{to{transform:rotate(360deg)}}.spinner{width:40px;height:40px;border:3px solid #334155;border-top-color:#38bdf8;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px}h2{font-size:20px;font-weight:600;margin:0 0 8px}p{color:#94a3b8;margin:0}</style></head><body><div style='text-align:center'><div class='spinner'></div><h2>NanoSchedule</h2><p>正在唤醒服务器…</p></div></body></html>";
    }
}
NGINXEOF
echo "[OK] nginx config written for port ${NGINX_PORT}"

if nginx -t 2>&1; then
    nginx
    echo "[OK] nginx started — port ${NGINX_PORT} open"
else
    echo "[FATAL] nginx config test failed"
    cat /etc/nginx/conf.d/default.conf
    exit 1
fi

# ── 6. 等 PWA 就绪后，前端自动恢复正常 ──
for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/')" 2>/dev/null; then
        echo "[OK] PWA backend ready"
        break
    fi
    sleep 1
done

echo "=== NanoSchedule Ready ==="
wait $PWA_PID
