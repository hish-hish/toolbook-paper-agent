import pytest

pytest.importorskip("mineru")

from toolbook.parsers.pdf_mineru import MinerUParser


@pytest.fixture(scope="module")
def pdf_file(tmp_path_factory):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "第1章 绪论", fontname="china-s", fontsize=22)
    page.insert_text((72, 120), "这是绪论正文。", fontname="china-s", fontsize=11)
    page.insert_text((72, 150), "1.1 信号", fontname="china-s", fontsize=16)
    page.insert_text((72, 180), "这是信号小节正文。", fontname="china-s", fontsize=11)
    p = tmp_path_factory.mktemp("mineru") / "book.pdf"
    doc.save(str(p))
    doc.close()
    return p


def test_mineru_headings_levels_and_locators(pdf_file):
    parsed = MinerUParser().parse(pdf_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("第1章 绪论", 1), ("1.1 信号", 2)]
    assert all(b.locator == "p1" for b in parsed.blocks)
    assert any("绪论正文" in b.text for b in parsed.blocks)