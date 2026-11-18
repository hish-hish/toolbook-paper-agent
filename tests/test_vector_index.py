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