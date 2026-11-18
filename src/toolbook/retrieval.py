"""混合检索编排：查询改写 → BM25+向量双路 → RRF 融合 → 父块去重 → 重排 → 带出处章节。

检索命中子块，返回所属父块（整个小节），出处沿 Chunk→Section→Document 回溯（D6/D7）。
"""
from dataclasses import dataclass

from . import config
from .bm25_index import BM25Index
from .llm import rewrite_query
from .store import LibraryStore
from .vector_index import vector_search


@dataclass
class SearchHit:
    """一条检索结果：父块全文 + 完整出处 + 命中方式。"""
    doc_id: int
    section_id: int
    number: str
    title: str
    source: str
    locator: str
    text: str
    score: float
    matched_by: str  # "bm25" / "vector" / "both"
    doc_title: str = ""


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """RRF 倒数排名融合：只看名次不看原始分，score = Σ 1/(k+rank)。"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


def hybrid_search(question: str, db_path=config.DEFAULT_DB, top_k: int = 5,
                  use_llm: bool = True, use_rerank: bool = True,
                  doc_id: int | None = None) -> list[SearchHit]:
    """混合检索主入口：返回 top_k 个父块（小节），含出处与命中方式。"""
    store = LibraryStore(db_path)
    try:
        bm25 = BM25Index(store)
        # 1) 查询改写（断网自动回退原问题）
        kw = rewrite_query(question) if use_llm else {"zh": question, "en": ""}
        # 2) BM25 路：原问题 + 中文关键词 + 英文关键词各查一次
        bm25_rankings, bm25_ids = [], set()
        for q in (question, kw["zh"], kw["en"]):
            if q.strip():
                ranking = [cid for cid, _ in bm25.search(q, 30)]
                bm25_rankings.append(ranking)
                bm25_ids.update(ranking)
        # 3) 向量路：原问题语义检索
        vec_ranking = [cid for cid, _ in vector_search(question, 30, doc_id)]
        vec_ids = set(vec_ranking)
        # 4) RRF 融合多路名次
        fused = rrf_fuse(bm25_rankings + [vec_ranking])
        # 5) 子块 → 父块映射与去重（保留最佳名次，记录命中方式）
        chunk_map = {r["chunk_id"]: r["section_id"] for r in store.conn.execute(
            "SELECT chunk_id, section_id FROM chunks")}
        sec_rows = {r["section_id"]: r for r in store.conn.execute(
            "SELECT s.*, d.title AS doc_title FROM sections s JOIN documents d ON s.doc_id=d.doc_id")}
        best: dict[int, tuple[float, str]] = {}
        for cid, score in fused:
            sid = chunk_map.get(cid)
            if sid is None:
                continue
            row = sec_rows[sid]
            if doc_id is not None and row["doc_id"] != doc_id:
                continue
            matched = "both" if cid in bm25_ids and cid in vec_ids else (
                "bm25" if cid in bm25_ids else "vector")
            if sid not in best:
                best[sid] = (score, matched)
            if len(best) >= 30:
                break
        # 6) 组装父块全文（同编号多 part 拼接）
        hits: list[SearchHit] = []
        for sid, (score, matched) in best.items():
            row = sec_rows[sid]
            parts = store.get_section(row["doc_id"], row["number"])
            text = "\n".join(p["text"] for p in parts if p["title"] == row["title"])
            hits.append(SearchHit(row["doc_id"], sid, row["number"], row["title"],
                                  row["source"], row["locator"], text, score,
                                  matched, row["doc_title"]))
        # 7) 本地重排（失败自动降级为 RRF 序）
        if use_rerank and hits:
            from .rerank import rerank_scores
            scores = rerank_scores(question, [h.text[:1500] for h in hits])
            if scores is not None:
                hits = [h for _, h in sorted(zip(scores, hits), key=lambda x: -x[0])]
        return hits[:top_k]
    finally:
        store.close()