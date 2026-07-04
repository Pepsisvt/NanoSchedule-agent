"""
知识库引擎 —— 文档导入、分块、向量检索

支持格式: .txt, .md, .json
架构: ChromaDB collection "nanoschedule_knowledge"

使用示例:
  from nanobot_calendar.knowledge_base import get_kb
  kb = get_kb()
  kb.ingest_file("课程表.txt", category="课程")
  results = kb.search("周三有什么课", k=3)
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

_lock = threading.Lock()
_kb_instance: "KnowledgeBase | None" = None

CHROMA_DIR = Path.home() / ".nanobot" / "chroma_db"
KB_DIR = Path.home() / ".nanobot" / "knowledge_base"


class KnowledgeBase:
    """文档知识库，基于 ChromaDB 向量检索"""

    def __init__(self):
        os.makedirs(CHROMA_DIR, exist_ok=True)
        os.makedirs(KB_DIR, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="nanoschedule_knowledge",
            metadata={"hnsw:space": "cosine"},
        )

    # ── 文档导入 ──

    def ingest_text(self, content: str, title: str, category: str = "general", source: str = "manual") -> str:
        """导入纯文本，自动分块"""
        chunks = self._chunk_text(content, chunk_size=500, overlap=50)
        ids = []
        for i, chunk in enumerate(chunks):
            doc_id = f"{category}:{_safe_id(title)}:chunk{i}"
            self._collection.upsert(
                documents=[chunk],
                metadatas=[{
                    "title": title,
                    "category": category,
                    "source": source,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "ingested_at": datetime.now().isoformat(),
                }],
                ids=[doc_id],
            )
            ids.append(doc_id)
        return f"[KB] 已导入「{title}」: {len(chunks)} 个片段 (类别: {category})"

    def ingest_file(self, filepath: str, category: str = "general") -> str:
        """导入文件 (.txt .md .json)"""
        path = Path(filepath)
        if not path.exists():
            return f"[KB] 文件不存在: {filepath}"

        ext = path.suffix.lower()
        if ext == ".json":
            content = self._parse_json(path)
        else:
            content = path.read_text(encoding="utf-8")

        title = path.stem
        return self.ingest_text(content, title, category, source=str(path))

    def ingest_directory(self, dirpath: str, category: str = "general") -> str:
        """批量导入目录下所有支持的文件"""
        path = Path(dirpath)
        if not path.is_dir():
            return f"[KB] 目录不存在: {dirpath}"

        count = 0
        for f in path.iterdir():
            if f.suffix.lower() in (".txt", ".md", ".json"):
                result = self.ingest_file(str(f), category)
                if "已导入" in result:
                    count += 1
        return f"[KB] 批量导入完成: {count} 个文件"

    # ── 检索 ──

    def search(self, query: str, k: int = 5, category: str | None = None) -> list[dict]:
        """检索知识库"""
        if self._collection.count() == 0:
            return []

        where = {"category": category} if category else None
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
                    "title": meta.get("title", ""),
                    "category": meta.get("category", ""),
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "similarity": round(1.0 - dist, 4),
                    "source": meta.get("source", ""),
                })
        return items

    def search_formatted(self, query: str, k: int = 5) -> str:
        """返回格式化的检索结果，可直接注入 prompt"""
        results = self.search(query, k)
        if not results:
            return "[KB] 知识库中未找到相关信息"

        lines = [f"[知识库] 找到 {len(results)} 条相关信息："]
        for r in results:
            sim = f"{r['similarity']:.0%}"
            content = r["content"][:200].replace("\n", " ")
            lines.append(f"  [{sim}] {r['title']}: {content}...")
        return "\n".join(lines)

    def list_documents(self) -> list[dict]:
        """列出知识库中的所有文档"""
        if self._collection.count() == 0:
            return []
        results = self._collection.get()
        docs: dict[str, dict] = {}
        if results["ids"]:
            metas = results.get("metadatas", [])
            if metas and isinstance(metas[0], list):
                metas = metas[0]  # ChromaDB newer API returns [[...]]
            for i, doc_id in enumerate(results["ids"]):
                meta = metas[i] if i < len(metas) else {}
                title = meta.get("title", "unknown")
                if title not in docs:
                    docs[title] = {
                        "title": title,
                        "category": meta.get("category", ""),
                        "chunks": 0,
                        "source": meta.get("source", ""),
                        "ingested_at": meta.get("ingested_at", ""),
                    }
                docs[title]["chunks"] += 1
        return sorted(docs.values(), key=lambda d: d["ingested_at"], reverse=True)

    def delete_document(self, title: str) -> str:
        """删除指定标题的所有文档片段"""
        results = self._collection.get(where={"title": title})
        if results["ids"]:
            self._collection.delete(ids=results["ids"])
            return f"[KB] 已删除「{title}」({len(results['ids'])} 个片段)"
        return f"[KB] 未找到文档: {title}"

    def count(self) -> int:
        return self._collection.count()

    # ── 内部 ──

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """简单分块：按段落 + 长度切分"""
        paragraphs = text.split("\n")
        chunks = []
        current = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) < chunk_size:
                current += para + "\n"
            else:
                if current:
                    chunks.append(current.strip())
                # 重叠：保留上一块的结尾
                overlap_text = current[-overlap:] if len(current) > overlap else ""
                current = overlap_text + para + "\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks if chunks else [text[:chunk_size]]

    @staticmethod
    def _parse_json(filepath: Path) -> str:
        """将 JSON 文件转为可读文本"""
        data = json.loads(filepath.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return "\n".join(json.dumps(item, ensure_ascii=False) for item in data)
        elif isinstance(data, dict):
            lines = []
            for key, val in data.items():
                if isinstance(val, str):
                    lines.append(f"{key}: {val}")
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            lines.append(f"{key}: {json.dumps(item, ensure_ascii=False)}")
                        else:
                            lines.append(f"{key}: {item}")
                else:
                    lines.append(f"{key}: {val}")
            return "\n".join(lines)
        return str(data)


def _safe_id(text: str) -> str:
    return text.replace("/", "_").replace(" ", "_")[:60]


def get_kb() -> KnowledgeBase:
    global _kb_instance
    if _kb_instance is None:
        with _lock:
            if _kb_instance is None:
                _kb_instance = KnowledgeBase()
    return _kb_instance
