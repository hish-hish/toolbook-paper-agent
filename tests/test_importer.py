import pytest

from toolbook.importer import import_file
from toolbook.store import LibraryStore


@pytest.fixture
def docx_file(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("第1章 绪论", level=1)
    d.add_paragraph("这是绪论正文。" * 30)
    d.add_heading("1.1 信号", level=2)
    d.add_paragraph("这是信号小节正文。")
    p = tmp_path / "book.docx"
    d.save(str(p))
    return p


def test_import_end_to_end(tmp_path, docx_file):
    db = tmp_path / "lib.db"
    r = import_file(docx_file, db)
    assert not r.skipped and r.sections >= 2 and r.chunks >= 2
    store = LibraryStore(db)
    rows = store.get_section(r.doc_id, "1.1")
    assert rows and rows[0]["source"] == "original"
    assert "信号小节正文" in rows[0]["text"]
    assert rows[0]["locator"].startswith("p")
    store.close()


def test_import_idempotent(tmp_path, docx_file):
    db = tmp_path / "lib.db"
    r1 = import_file(docx_file, db)
    r2 = import_file(docx_file, db)
    assert r2.skipped and r2.doc_id == r1.doc_id
    store = LibraryStore(db)
    assert len(store.list_documents()) == 1
    store.close()


def test_long_section_multi_part(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("第1章 长章", level=1)
    for _ in range(20):
        d.add_paragraph("很长的一段。" * 100)
    p = tmp_path / "long.docx"
    d.save(str(p))
    r = import_file(p, tmp_path / "lib.db")
    store = LibraryStore(tmp_path / "lib.db")
    rows = store.get_section(r.doc_id, "1")
    assert len(rows) >= 2
    assert all(len(x["text"]) <= 2000 for x in rows)
    store.close()


def test_import_prunes_non_content(tmp_path):
    # 导入即过滤：前言（前导文字自动生成0）、本章自测、参考文献入库前被剪掉，正式章节保留
    from docx import Document
    d = Document()
    d.add_paragraph("版权页与出版说明文字。")
    d.add_heading("第1章 绪论", level=1)
    d.add_paragraph("这是绪论正文。" * 20)
    d.add_heading("1.1 信号", level=2)
    d.add_paragraph("这是信号小节正文。")
    d.add_heading("本章自测", level=2)
    d.add_paragraph("自测题：请简述采样定理。")
    d.add_heading("参考文献", level=1)
    d.add_paragraph("[1] 某作者. 某论文. 某期刊, 2020.")
    p = tmp_path / "mixed.docx"
    d.save(str(p))
    db = tmp_path / "lib.db"
    r = import_file(p, db)
    store = LibraryStore(db)
    assert store.get_section(r.doc_id, "0") == []        # 前言被剪
    assert store.get_section(r.doc_id, "1.S1") == []     # 本章自测被剪
    assert store.get_section(r.doc_id, "1")              # 正式章保留
    assert store.get_section(r.doc_id, "1.1")            # 正式小节保留
    titles = [row["title"] for row in store.get_tree(r.doc_id)]
    assert not any("参考文献" in t for t in titles)       # 参考文献被剪
    store.close()