import pytest

from toolbook.store import LibraryStore


@pytest.fixture
def store(tmp_path):
    s = LibraryStore(tmp_path / "test.db")
    yield s
    s.close()


def test_hash_dedup_lookup(store):
    assert store.find_by_hash("abc") is None
    with store.transaction():
        doc_id = store.add_document("书名", "docx", "abc", "x.docx")
    assert store.find_by_hash("abc")["doc_id"] == doc_id


def test_section_and_chunks_roundtrip(store):
    with store.transaction():
        doc_id = store.add_document("书名", "pdf", "h1", "x.pdf")
        sid = store.insert_section(doc_id, None, "3.2", "傅里叶性质", 2, "original", "p10", 1, "原文全文")
        n = store.insert_chunks(sid, ["子块1", "子块2"])
    rows = store.get_section(doc_id, "3.2")
    assert len(rows) == 1 and rows[0]["text"] == "原文全文"
    assert n == 2
    tree = store.get_tree(doc_id)
    assert tree[0]["number"] == "3.2"


def test_multi_part_section(store):
    with store.transaction():
        doc_id = store.add_document("书", "pdf", "h2", "x.pdf")
        store.insert_section(doc_id, None, "1", "长章", 1, "original", "p1", 1, "上半")
        store.insert_section(doc_id, None, "1", "长章", 1, "original", "p1", 2, "下半")
    rows = store.get_section(doc_id, "1")
    assert [r["part"] for r in rows] == [1, 2]


def test_cascade_delete(store):
    with store.transaction():
        doc_id = store.add_document("书", "epub", "h3", "x.epub")
        sid = store.insert_section(doc_id, None, "1", "章", 1, "system", "", 1, "文")
        store.insert_chunks(sid, ["块"])
    store.delete_document(doc_id)
    assert store.list_documents() == []
    assert store.get_tree(doc_id) == []


def test_transaction_rollback(store):
    try:
        with store.transaction():
            store.add_document("书", "pdf", "h4", "x.pdf")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert store.find_by_hash("h4") is None