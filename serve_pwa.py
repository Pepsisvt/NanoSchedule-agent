"""PWA 前端服务器 + 主动推送引擎（akashic-agent Proactive Push）"""

import http.server
import json
import socket
import sys
import urllib.parse
from pathlib import Path

WEBUI_DIR = Path(__file__).parent / "webui"


class PWAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBUI_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/stats":
            self._handle_stats()
        elif parsed.path == "/api/notifications":
            self._handle_notifications()
        elif parsed.path == "/api/poll-interval":
            self._handle_poll_interval()
        elif parsed.path == "/api/user-active":
            self._handle_user_active()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/user-active":
            self._handle_user_active()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_stats(self):
        try:
            from nanobot_calendar.stats_api import compute_stats
            data = compute_stats()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def _handle_notifications(self):
        """返回待推送通知（由 ProactiveBrain 后台填充）"""
        try:
            from nanobot_calendar.proactive import pop_notifications
            items = pop_notifications()
            body = json.dumps({"notifications": items}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def _handle_poll_interval(self):
        """自适应轮询间隔"""
        try:
            from nanobot_calendar.proactive import next_reminder_seconds
            secs = next_reminder_seconds()
            if secs is None:
                interval = 15000
            elif secs < 60:
                interval = 2000
            elif secs < 300:
                interval = 5000
            else:
                interval = 10000
            body = json.dumps({"interval_ms": interval}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            body = json.dumps({"interval_ms": 5000}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def _handle_user_active(self):
        """标记用户活跃（每次聊天时前端调用，重置 battery）"""
        try:
            from nanobot_calendar.proactive import get_brain
            get_brain().user_active()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":false}')

    def log_message(self, format, *args):
        try:
            if args and not any(isinstance(a, str) and "/api/" in a for a in args):
                print(f"[{self.address_string()}] {format % args}")
        except Exception:
            pass


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 3000
    local_ip = get_local_ip()

    # 启动主动大脑
    from nanobot_calendar.proactive import get_brain
    get_brain().start()

    # 初始化 RAG 记忆引擎
    from nanobot_calendar.rag_memory import init_rag
    init_rag(import_json=True)

    # 自动导入 knowledge/ 目录下的文档
    from nanobot_calendar.knowledge_base import get_kb
    kb = get_kb()
    kb_dir = Path(__file__).parent / "knowledge"
    if kb_dir.is_dir() and kb.count() == 0:
        imported = kb.ingest_directory(str(kb_dir))
        print(f"  KB: {imported}")

    # 启动对话历史索引器（每5分钟扫描新对话）
    from nanobot_calendar.conversation_indexer import ConversationWatcher
    conv_watcher = ConversationWatcher(interval_seconds=300)
    conv_watcher.start()

    server = http.server.HTTPServer((host, port), PWAHandler)

    print("=" * 55)
    print("  Schedule Assistant (Proactive Push)")
    print("=" * 55)
    print(f"  Local:       http://localhost:{port}")
    print(f"  Mobile:      http://{local_ip}:{port}")
    print(f"  Brain:       active (adaptive: 20s-120s)")
    print(f"  RAG:         enabled (vector memory)")
    print(f"  Alerts:      upcoming events")
    print(f"  Content:     missing reminders")
    print(f"  Context:     daily summary")
    print("=" * 55)
    sys.stdout.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        get_brain().stop()
        print("\nServer stopped.")
