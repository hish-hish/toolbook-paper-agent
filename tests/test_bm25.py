"""BM25 索引离线单测：中英分词与关键词精确命中。"""
import pytest

from toolbook.bm25_index import BM25Index, tokenize
from toolbook.store import LibraryStore


def test_tokenize_mixed():
    # 中英混合分词：中文被切出、英文转小写
    tokens = tokenize("傅里叶变换 Fourier Transform 3.2")
    assert "傅里叶" in tokens or "傅里叶变换" in tokens
    assert "fourier" in tokens
    assert "transform" in tokens


@pytest.fixture
def store(tmp_path):
    # 三节小库：2.1 傅里叶、2.2 采样、3.1 信道编码（第三块避免 BM25 两文档 IDF=0 的退化情形）
    s = LibraryStore(tmp_path / "t.db")
    with s.transaction():
        doc_id = s.add_document("书", "docx", "h", "x.docx")
        sid1 = s.insert_section(doc_id, None, "2.1", "傅里叶变换", 2, "original", "p1", 1, "傅里叶变换把信号分解为不同频率的正弦分量。")
        sid2 = s.insert_section(doc_id, None, "2.2", "采样定理", 2, "original", "p2", 1, "采样定理给出从离散样本无失真恢复连续信号的条件。")
        sid3 = s.insert_section(doc_id, None, "3.1", "信道编码", 2, "original", "p3", 1, "信道编码通过增加冗余提高传输可靠性。")
        s.insert_chunks(sid1, ["傅里叶变换把信号分解为不同频率的正弦分量。"])
        s.insert_chunks(sid2, ["采样定理给出从离散样本无失真恢复连续信号的条件。"])
        s.insert_chunks(sid3, ["信道编码通过增加冗余提高传输可靠性。"])
    yield s
    s.close()


def test_bm25_exact_term_hits_right_chunk(store):
    # 关键词查询应命中含该词的子块且得分最高
    idx = BM25Index(store)
    hits = idx.search("傅里叶变换")
    assert hits and hits[0][0] == idx.chunk_ids[0]
    assert hits[0][1] > 0


def test_bm25_empty_query(store):
    # 空查询返回空列表而不是报错
    assert BM25Index(store).search("") == []