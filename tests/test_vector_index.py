"""向量索引离线单测：用确定性假向量验证建索引/查询/幂等，不触网。"""
import pytest

import toolbook.vector_index as vi
from toolbook.store import LibraryStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    # 隔离 Chroma 目录与 embedding：假向量 = [文本长度, 1.0]
    monkeypatch.setattr(vi.config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(vi, "embed_texts", lambda texts, **k: [[float(len(t)), 1.0] for t in texts])
    db = tmp_path / "lib.db"
    s = LibraryStore(db)
    with s.transaction():
        doc_id = s.add_document("书", "docx", "h", "x.docx")
        sid = s.insert_section(doc_id, None, "1.1", "节", 2, "original", "p1", 1, "正文")
        s.insert_chunks(sid, ["短块", "这是一个比较长的子块文本"])
    s.close()
    return db


def test_build_and_count(env):
    # 建索引返回条数；数量一致时幂等跳过
    assert vi.build_vector_index(env) == 2
    assert vi.build_vector_index(env) == 2


def test_force_rebuild(env):
    # force=True 强制重建后条数不变
    vi.build_vector_index(env)
    assert vi.build_vector_index(env, force=True) == 2


def test_vector_search_returns_chunk_ids(env):
    # 查询"短块"：等长假向量最近，排第一；相似度降序
    vi.build_vector_index(env)
    hits = vi.vector_search("短块", top_k=2)
    assert len(hits) == 2
    assert hits[0][0] == 1
    assert hits[0][1] >= hits[1][1]


@pytest.fixture
def env2(tmp_path, monkeypatch):
    # 两本书各一节一块：doc1→chunk1、doc2→chunk2，用于验证书目过滤（$in）
    monkeypatch.setattr(vi.config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(vi, "embed_texts", lambda texts, **k: [[float(len(t)), 1.0] for t in texts])
    db = tmp_path / "lib.db"
    s = LibraryStore(db)
    with s.transaction():
        d1 = s.add_document("书A", "docx", "hA", "a.docx")
        sid1 = s.insert_section(d1, None, "1.1", "节A", 2, "original", "p1", 1, "正文A")
        s.insert_chunks(sid1, ["甲"])
        d2 = s.add_document("书B", "docx", "hB", "b.docx")
        sid2 = s.insert_section(d2, None, "1.1", "节B", 2, "original", "p1", 1, "正文B")
        s.insert_chunks(sid2, ["乙"])
    s.close()
    return db


def test_vector_search_doc_ids_single(env2):
    # 只选书1：仅返回 doc1 的子块（chunk1），doc2 被过滤掉
    vi.build_vector_index(env2)
    hits = vi.vector_search("甲", top_k=5, doc_ids=[1])
    assert [cid for cid, _ in hits] == [1]


def test_vector_search_doc_ids_multi(env2):
    # 选书1+2：两本书的子块都返回
    vi.build_vector_index(env2)
    hits = vi.vector_search("甲", top_k=5, doc_ids=[1, 2])
    assert {cid for cid, _ in hits} == {1, 2}


def test_vector_search_doc_ids_none_returns_all(env2):
    # 不传 doc_ids（None）：搜全库，两本书都返回（向后兼容）
    vi.build_vector_index(env2)
    hits = vi.vector_search("甲", top_k=5)
    assert {cid for cid, _ in hits} == {1, 2}