"""BM25 关键词检索索引：jieba 中英分词 + rank_bm25 打分。

从 SQLite chunks 表在内存构建（3 本书规模毫秒级），进程重启自动重建，无需持久化。
"""
import re

import jieba
from rank_bm25 import BM25Okapi

from .store import LibraryStore


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文转小写，jieba 切分，丢弃纯标点/空白 token。"""
    return [t for t in jieba.lcut(text.lower())
            if re.search(r"[\w一-鿿]", t)]


class BM25Index:
    """以子块为单位的 BM25Okapi 索引；chunk_ids/section_ids 与语料同序。"""

    def __init__(self, store: LibraryStore):
        # 从库里读全部子块，构建分词语料与 ID 映射
        rows = store.conn.execute(
            "SELECT chunk_id, section_id, text FROM chunks ORDER BY chunk_id").fetchall()
        self.chunk_ids = [r["chunk_id"] for r in rows]
        self.section_ids = [r["section_id"] for r in rows]
        corpus = [tokenize(r["text"]) for r in rows]
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, top_k: int = 30) -> list[tuple[int, float]]:
        """关键词检索：返回 [(chunk_id, BM25分)] 降序，零分与空查询返回空列表。"""
        if self.bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        return [(self.chunk_ids[i], float(scores[i])) for i in order if scores[i] > 0]