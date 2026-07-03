"""
RAG 记忆引擎 —— 基于向量检索的语义记忆

相比原始 memory_engine.py 的 JSON 遍历查找，RAG 引擎提供：
  1. 语义相似度检索 —— "上次那个饭局" 能匹配到 "和朋友聚餐"
  2. 混合检索 —— 关键词 + 向量双路召回
  3. 自动去重 —— 存储时合并重复记忆

存储:
  ChromaDB (向量) + user_profile.json (结构化数据)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

# ── 全局单例 ──
_rag_instance: "RAGMemory | None" = None
_lock = threading.Lock()

CHROMA_DIR = Path.home() / ".nanobot" / "chroma_db"
PROFILE_PATH = Path.home() / ".nanobot" / "workspace" / "user_profile.json"


class RAGMemory:
    """基于 ChromaDB 的向量记忆引擎"""

    def __init__(self):
        os.makedirs(CHROMA_DIR, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="nanoschedule_memories",
            metadata={"hnsw:space": "cosine"},
        )

    # ── 写入 ──

    def remember(self, key: str, value: str, metadata: dict | None = None) -> str:
        """记住一条信息，自动去重"""
        existing = self._search_exact(key, value)
        if existing:
            return f"[SKIP] 已存在: {key} — {value}"

        doc_id = f"{key}:{_safe_id(value)}"
        meta = metadata or {}
        meta["key"] = key
        meta["value"] = value
        meta["timestamp"] = datetime.now().isoformat()
        meta["source"] = meta.get("source", "agent")

        self._collection.add(
            documents=[f"{key}: {value}"],
            metadatas=[meta],
            ids=[doc_id],
        )
        return f"[OK] 已记忆: {key} — {value}"

    def remember_batch(self, items: list[dict]) -> list[str]:
        """批量记忆"""
        results = []
        for item in items:
            r = self.remember(
                item.get("key", ""),
                item.get("value", ""),
                item.get("metadata"),
            )
            results.append(r)
        return results

    # ── 检索 ──

    def search(self, query: str, k: int = 5) -> list[dict]:
        """语义检索最相关的记忆"""
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_texts=[query],
            n_results=min(k, self._collection.count()),
        )

        memories = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 1.0
                # cosine distance -> similarity: 1 - distance
                similarity = 1.0 - dist if dist is not None else 0.0
                memories.append({
                    "id": doc_id,
                    "key": meta.get("key", ""),
                    "value": meta.get("value", ""),
                    "similarity": round(similarity, 4),
                    "timestamp": meta.get("timestamp", ""),
                    "source": meta.get("source", ""),
                })
        return memories

    def search_with_threshold(self, query: str, k: int = 5, threshold: float = 0.3) -> list[dict]:
        """检索并过滤低相似度结果"""
        results = self.search(query, k)
        return [r for r in results if r["similarity"] >= threshold]

    def get_context_for_prompt(self, query: str, k: int = 5) -> str:
        """生成可注入 LLM prompt 的上下文字符串"""
        results = self.search_with_threshold(query, k, threshold=0.25)
        if not results:
            return ""

        lines = ["[相关记忆 — 来自历史对话]"]
        for r in results:
            sim_icon = "★" if r["similarity"] > 0.7 else "·"
            lines.append(f"  {sim_icon} {r['key']}: {r['value']} (相关度:{r['similarity']:.0%})")
        return "\n".join(lines)

    # ── 管理 ──

    def count(self) -> int:
        return self._collection.count()

    def list_all(self, limit: int = 50) -> list[dict]:
        """列出所有记忆"""
        if self._collection.count() == 0:
            return []
        results = self._collection.get(limit=limit)
        memories = []
        if results["ids"]:
            for i, doc_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                memories.append({
                    "id": doc_id,
                    "key": meta.get("key", ""),
                    "value": meta.get("value", ""),
                    "timestamp": meta.get("timestamp", ""),
                })
        return sorted(memories, key=lambda m: m["timestamp"], reverse=True)

    def delete(self, doc_id: str) -> bool:
        """删除一条记忆"""
        try:
            self._collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def import_from_json(self, filepath: str | None = None) -> int:
        """从 user_profile.json 导入历史记忆"""
        path = Path(filepath) if filepath else PROFILE_PATH
        if not path.exists():
            return 0

        data = json.loads(path.read_text(encoding="utf-8"))
        memories = data.get("memories", [])
        imported = 0
        for m in memories:
            result = self.remember(m["key"], m["value"], {
                "timestamp": m.get("time", ""),
                "source": "import",
            })
            if "[OK]" in result:
                imported += 1
        return imported

    # ── 内部 ──

    def _search_exact(self, key: str, value: str) -> bool:
        """检查是否已存在完全相同的记忆"""
        doc_id = f"{key}:{_safe_id(value)}"
        try:
            existing = self._collection.get(ids=[doc_id])
            return len(existing["ids"]) > 0
        except Exception:
            return False


def _safe_id(text: str) -> str:
    """生成安全的 ID"""
    return text.replace("/", "_")[:80]


# ── 全局访问 ──

def get_rag() -> RAGMemory:
    """获取全局 RAG 引擎实例（线程安全）"""
    global _rag_instance
    if _rag_instance is None:
        with _lock:
            if _rag_instance is None:
                _rag_instance = RAGMemory()
    return _rag_instance


def init_rag(import_json: bool = True) -> RAGMemory:
    """初始化 RAG 引擎，可选从 JSON 导入历史数据"""
    rag = get_rag()
    if import_json:
        imported = rag.import_from_json()
        if imported > 0:
            print(f"[RAG] Imported {imported} memories from user_profile.json")
    print(f"[RAG] Ready — {rag.count()} memories indexed")
    return rag
