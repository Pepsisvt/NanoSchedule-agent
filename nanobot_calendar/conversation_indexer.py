"""
对话索引器 —— 自动将对话历史存入向量库

功能:
  1. 监听 workspace/sessions/ 目录下的 .jsonl 对话文件
  2. 自动将用户-Agent 对话对提取并向量化
  3. 支持增量索引（只处理新内容）
  4. Agent 可通过工具搜索历史对话

使用:
  from nanobot_calendar.conversation_indexer import get_indexer
  idx = get_indexer()
  idx.scan_and_index()  # 扫描新对话
  idx.search("上次聊了啥", k=3)  # 搜索历史
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

_lock = threading.Lock()
_indexer_instance: "ConversationIndexer | None" = None

CHROMA_DIR = Path.home() / ".nanobot" / "chroma_db"
SESSIONS_DIR = Path(__file__).parent.parent / "workspace" / "sessions"
CURSOR_FILE = Path(__file__).parent.parent / "workspace" / "memory" / ".index_cursor"


class ConversationIndexer:
    """对话历史向量索引器"""

    def __init__(self):
        os.makedirs(CHROMA_DIR, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="nanoschedule_conversations",
            metadata={"hnsw:space": "cosine"},
        )
        self._cursor = self._load_cursor()

    # ── 扫描与索引 ──

    def scan_and_index(self) -> dict:
        """扫描 sessions 目录，索引新对话。返回统计信息。"""
        if not SESSIONS_DIR.exists():
            return {"new_files": 0, "new_messages": 0, "total_indexed": self._collection.count()}

        files = sorted(SESSIONS_DIR.glob("*.jsonl"))
        new_files = 0
        new_messages = 0

        for f in files:
            file_key = f"{f.name}:{f.stat().st_mtime}"
            if file_key in self._cursor:
                continue

            messages = self._extract_messages(f)
            if messages:
                self._index_messages(messages, f.name)
                new_messages += len(messages)

            self._cursor[file_key] = datetime.now().isoformat()
            new_files += 1

        self._save_cursor()
        return {
            "new_files": new_files,
            "new_messages": new_messages,
            "total_indexed": self._collection.count(),
        }

    # ── 检索 ──

    def search(self, query: str, k: int = 5, date_from: str = "") -> list[dict]:
        """搜索历史对话"""
        if self._collection.count() == 0:
            return []

        where = None
        if date_from:
            where = {"date": {"$gte": date_from}}

        results = self._collection.query(
            query_texts=[query],
            n_results=min(k, self._collection.count()),
            where=where,
        )

        items = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 1.0
                items.append({
                    "id": doc_id,
                    "speaker": meta.get("speaker", ""),
                    "message": results["documents"][0][i] if results["documents"] else "",
                    "similarity": round(1.0 - dist, 4),
                    "date": meta.get("date", ""),
                    "channel": meta.get("channel", ""),
                })
        return items

    def search_formatted(self, query: str, k: int = 5) -> str:
        """返回格式化的历史对话搜索结果"""
        results = self.search(query, k)
        if not results:
            return "[对话历史] 未找到相关对话"

        lines = [f"[对话历史] 找到 {len(results)} 条相关对话："]
        for r in results:
            sim = f"{r['similarity']:.0%}"
            speaker_icon = "👤" if r["speaker"] == "user" else "🤖"
            msg = r["message"][:200]
            lines.append(f"  [{sim}] {r['date'][:10]} {speaker_icon} {msg}")
        return "\n".join(lines)

    def count(self) -> int:
        return self._collection.count()

    def stats(self) -> dict:
        """索引统计"""
        if self._collection.count() == 0:
            return {"total": 0, "user_msgs": 0, "agent_msgs": 0, "date_range": ""}

        results = self._collection.get()
        user_count = 0
        agent_count = 0
        dates = []
        if results["metadatas"]:
            for meta in results["metadatas"]:
                if meta.get("speaker") == "user":
                    user_count += 1
                else:
                    agent_count += 1
                if meta.get("date"):
                    dates.append(meta["date"][:10])

        return {
            "total": self._collection.count(),
            "user_msgs": user_count,
            "agent_msgs": agent_count,
            "date_range": f"{min(dates)} ~ {max(dates)}" if dates else "",
        }

    # ── 内部 ──

    def _extract_messages(self, filepath: Path) -> list[dict]:
        """从 .jsonl 文件中提取用户和 Agent 的消息对"""
        messages = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 提取用户消息
                    user_msg = record.get("user", "") or record.get("content", "") or record.get("text", "")
                    if user_msg and len(str(user_msg)) > 3:
                        messages.append({
                            "speaker": "user",
                            "message": str(user_msg)[:1000],
                            "date": record.get("timestamp", "") or record.get("time", ""),
                            "channel": record.get("channel", filepath.stem),
                        })

                    # 提取 Agent 回复
                    agent_msg = record.get("assistant", "") or record.get("response", "") or record.get("reply", "")
                    if agent_msg and len(str(agent_msg)) > 5:
                        messages.append({
                            "speaker": "agent",
                            "message": str(agent_msg)[:1000],
                            "date": record.get("timestamp", "") or record.get("time", ""),
                            "channel": record.get("channel", filepath.stem),
                        })
        except Exception:
            pass
        return messages

    def _index_messages(self, messages: list[dict], source: str) -> None:
        """批量索引消息到向量库"""
        if not messages:
            return

        batch_size = 50
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            ids = []
            docs = []
            metas = []
            for j, msg in enumerate(batch):
                msg_id = f"{source}:msg{i+j}"
                # 检查是否已存在
                existing = self._collection.get(ids=[msg_id])
                if existing["ids"]:
                    continue
                ids.append(msg_id)
                docs.append(msg["message"])
                metas.append({
                    "speaker": msg["speaker"],
                    "date": msg["date"],
                    "channel": msg["channel"],
                    "source": source,
                })

            if ids:
                try:
                    self._collection.add(documents=docs, metadatas=metas, ids=ids)
                except Exception:
                    pass

    def _load_cursor(self) -> dict:
        if CURSOR_FILE.exists():
            try:
                return json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_cursor(self) -> None:
        CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        CURSOR_FILE.write_text(json.dumps(self._cursor, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 后台线程 ──

class ConversationWatcher:
    """后台定时扫描对话文件夹的守护线程"""

    def __init__(self, interval_seconds: int = 300):
        self._interval = interval_seconds
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                idx = get_indexer()
                stats = idx.scan_and_index()
                if stats["new_files"] > 0:
                    print(f"[ConvIndexer] Indexed {stats['new_messages']} messages from {stats['new_files']} files (total: {stats['total_indexed']})")
            except Exception:
                pass
            time.sleep(self._interval)


def get_indexer() -> ConversationIndexer:
    global _indexer_instance
    if _indexer_instance is None:
        with _lock:
            if _indexer_instance is None:
                _indexer_instance = ConversationIndexer()
    return _indexer_instance
