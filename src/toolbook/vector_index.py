"""Chroma 向量索引：把 SQLite 子块批量向量化后持久化，查询时近邻搜索。

向量随 Chroma 落盘（data/chroma/），导入后建一次即可复用（查询仍需联网向量化问题）。
"""
import chromadb

from . import config
from .llm import embed_texts
from .store import LibraryStore

COLLECTION = "toolbook_chunks"


def get_collection():
    """打开持久化集合（cosine 空间）；显式关闭 chroma 默认 embedding 模型下载。"""
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    return client.get_or_create_collection(
        COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"})


def build_vector_index(db_path=config.DEFAULT_DB, force: bool = False) -> int:
    """全量重建向量索引；子块数与库中一致且非 force 时跳过。返回向量条数。"""
    store = LibraryStore(db_path)
    rows = store.conn.execute(
        "SELECT c.chunk_id, c.section_id, c.text, s.doc_id, s.number, s.title, s.source, s.locator "
        "FROM chunks c JOIN sections s ON c.section_id = s.section_id ORDER BY c.chunk_id").fetchall()
    store.close()
    col = get_collection()
    if not force and col.count() == len(rows):
        return col.count()
    # 清空旧向量，避免删除/重导后残留
    existing = col.get()["ids"]
    if existing:
        col.delete(ids=existing)
    if not rows:
        return 0
    # 批量向量化（bge-m3），再分批写入 Chroma（带出处元数据）
    vecs = embed_texts([r["text"] for r in rows])
    for i in range(0, len(rows), 256):
        batch = rows[i:i + 256]
        col.add(
            ids=[str(r["chunk_id"]) for r in batch],
            embeddings=vecs[i:i + 256],
            documents=[r["text"] for r in batch],
            metadatas=[{"section_id": r["section_id"], "doc_id": r["doc_id"],
                        "number": r["number"], "title": r["title"],
                        "source": r["source"], "locator": r["locator"]} for r in batch])
    return col.count()


def vector_search(question: str, top_k: int = 30, doc_ids: list[int] | None = None) -> list[tuple[int, float]]:
    """问题向量化 → Chroma 近邻；返回 [(chunk_id, 余弦相似度)] 降序。

    doc_ids 限定只搜某些书（多书用 $in 过滤）；None 搜全库，空列表则无命中。
    """
    col = get_collection()
    if col.count() == 0:
        return []
    qv = embed_texts([question])[0]
    where = {"doc_id": {"$in": doc_ids}} if doc_ids is not None else None
    res = col.query(query_embeddings=[qv], n_results=min(top_k, col.count()), where=where)
    # cosine 空间下 distance = 1 - 相似度，换算回相似度便于阅读
    return [(int(cid), 1.0 - dist) for cid, dist in zip(res["ids"][0], res["distances"][0])]