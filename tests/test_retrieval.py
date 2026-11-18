"""混合检索离线单测：RRF 融合、父块去重、端到端（假向量+真 BM25）。"""
import pytest

import toolbook.retrieval as rt
from toolbook.importer import import_file


def test_rrf_fuse_orders_by_both_lists():
    # 两路都靠前的块应排最前；只出现在单路末尾的块靠后
    fused = rt.rrf_fuse([[1, 2, 3], [2, 1, 4]])
    ids = [cid for cid, _ in fused]
    assert set(ids) == {1, 2, 3, 4}
    assert ids[0] in (1, 2)
    assert ids.index(4) > ids.index(3)


def test_rrf_single_list():
    # 单路融合：分数即 1/(60+名次)
    fused = rt.rrf_fuse([[7, 8]])
    assert [cid for cid, _ in fused] == [7, 8]
    assert fused[0][1] == pytest.approx(1 / 61)


@pytest.fixture
def library(tmp_path, monkeypatch):
    # 三节文档：2.1 傅里叶、2.2 采样、2.3 编码（第三节避免 BM25 零 IDF 退化）
    # 假向量让语义查询偏向 2.2 的子块（chunk_id=2）
    from docx import Document
    d = Document()
    d.add_heading("第2章 傅里叶分析", level=1)
    d.add_heading("2.1 傅里叶变换", level=2)
    d.add_paragraph("傅里叶变换把时域信号分解为不同频率的正弦分量，是频域分析的核心工具。")
    d.add_heading("2.2 采样定理", level=2)
    d.add_paragraph("采样定理给出从离散样本无失真恢复连续信号的条件：采样频率必须大于最高频率两倍。")
    d.add_heading("2.3 信道编码", level=2)
    d.add_paragraph("信道编码通过增加冗余提高传输可靠性。")
    p = tmp_path / "b.docx"
    d.save(str(p))
    db = tmp_path / "lib.db"
    import_file(p, db)
    monkeypatch.setattr(rt, "vector_search",
                        lambda q, top_k=30, doc_id=None: [(2, 0.9), (1, 0.5)])
    return db


def test_hybrid_keyword_query(library):
    # 关键词查询：BM25 精确命中 2.1，应排第一且带出处
    hits = rt.hybrid_search("傅里叶变换", db_path=library, use_llm=False, use_rerank=False)
    assert hits and hits[0].number == "2.1"
    assert hits[0].source == "original"
    assert hits[0].locator.startswith("p")
    assert "频域分析" in hits[0].text


def test_hybrid_semantic_query(library):
    # 语义查询：假向量偏向 2.2，BM25 也命中采样相关词，融合后 2.2 第一
    hits = rt.hybrid_search("怎样从离散样本恢复连续信号", db_path=library, use_llm=False, use_rerank=False)
    assert hits and hits[0].number == "2.2"


def test_parent_dedup(library):
    # 同一父块的多个子块命中只返回一条结果
    hits = rt.hybrid_search("傅里叶 采样 信号", db_path=library, use_llm=False, use_rerank=False, top_k=10)
    section_ids = [h.section_id for h in hits]
    assert len(section_ids) == len(set(section_ids))


def test_rerank_overrides_order_and_score(library, monkeypatch):
    # 假重排把 RRF 第二名抬到第一：排序与展示分都应被重排分覆盖
    import toolbook.rerank as rr
    monkeypatch.setattr(rr, "rerank_scores", lambda q, texts: [0.2, 0.9, 0.1][:len(texts)])
    hits = rt.hybrid_search("傅里叶变换", db_path=library, use_llm=False, use_rerank=True)
    assert hits[0].number == "2.2"
    assert hits[0].score == pytest.approx(0.9)
    assert hits[0].score >= hits[1].score


def test_use_vector_false_skips_vector_route(library, monkeypatch):
    # 消融开关：关向量路时 vector_search 绝不被调用，纯 BM25 关键词命中 2.1
    calls = []
    monkeypatch.setattr(rt, "vector_search", lambda *a, **k: calls.append(1) or [])
    hits = rt.hybrid_search("傅里叶变换", db_path=library, use_llm=False,
                            use_rerank=False, use_vector=False)
    assert calls == []
    assert hits and hits[0].number == "2.1"
    assert all(h.matched_by == "bm25" for h in hits)


def test_use_bm25_false_skips_bm25_route(library, monkeypatch):
    # 消融开关：关 BM25 路时其 search 绝不被调用，纯向量命中 2.2（fixture 假向量偏向 chunk2）
    bm25_calls = []

    class FakeBM25:
        def __init__(self, store):
            pass

        def search(self, q, n):
            bm25_calls.append(q)
            return []

    monkeypatch.setattr(rt, "BM25Index", FakeBM25)
    hits = rt.hybrid_search("怎样从离散样本恢复连续信号", db_path=library, use_llm=False,
                            use_rerank=False, use_bm25=False)
    assert bm25_calls == []
    assert hits and hits[0].number == "2.2"
    assert all(h.matched_by == "vector" for h in hits)