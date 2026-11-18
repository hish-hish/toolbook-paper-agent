import pytest

from toolbook.parsers import get_parser
from toolbook.parsers.docx_parser import DocxParser
from toolbook.parsers.epub_parser import EpubParser
from toolbook.parsers.pdf_pymupdf import PyMuPDFParser


@pytest.fixture
def docx_file(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("第1章 绪论", level=1)
    d.add_paragraph("这是绪论正文。")
    d.add_heading("1.1 信号", level=2)
    d.add_paragraph("这是信号小节正文。")
    p = tmp_path / "book.docx"
    d.save(str(p))
    return p


@pytest.fixture
def epub_file(tmp_path):
    from ebooklib import epub
    b = epub.EpubBook()
    b.set_identifier("id1")
    b.set_title("Sample Book")
    b.set_language("en")
    c1 = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    c1.content = ("<h1>Chapter 1 Introduction</h1><p>Intro body text.</p>"
                  "<h2>1.1 Signals</h2><p>Signals body.</p>")
    b.add_item(c1)
    b.spine = ["nav", c1]
    b.add_item(epub.EpubNav())
    b.add_item(epub.EpubNcx())
    p = tmp_path / "book.epub"
    epub.write_epub(str(p), b)
    return p


@pytest.fixture
def pdf_file(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "第1章 绪论", fontname="china-s", fontsize=22)
    page.insert_text((72, 120), "这是绪论正文。", fontname="china-s", fontsize=11)
    page.insert_text((72, 150), "1.1 信号", fontname="china-s", fontsize=16)
    page.insert_text((72, 180), "这是信号小节正文。", fontname="china-s", fontsize=11)
    doc.set_toc([[1, "第1章 绪论", 1], [2, "1.1 信号", 1]])
    p = tmp_path / "book.pdf"
    doc.save(str(p))
    doc.close()
    return p


def test_docx_headings_and_locators(docx_file):
    parsed = DocxParser().parse(docx_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("第1章 绪论", 1), ("1.1 信号", 2)]
    assert all(b.locator.startswith("p") for b in parsed.blocks)
    assert any("绪论正文" in b.text for b in parsed.blocks)


def test_epub_headings_and_locators(epub_file):
    parsed = EpubParser().parse(epub_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("Chapter 1 Introduction", 1), ("1.1 Signals", 2)]
    assert parsed.title == "Sample Book"
    assert all(b.locator.startswith("spine") for b in parsed.blocks)


def test_pdf_bookmark_headings(pdf_file):
    parsed = PyMuPDFParser().parse(pdf_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("第1章 绪论", 1), ("1.1 信号", 2)]
    assert all(b.locator == "p1" for b in parsed.blocks)


def test_pdf_font_fallback_without_toc(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One", fontsize=24)
    page.insert_text((72, 120), "Body text here.", fontsize=11)
    p = tmp_path / "notoc.pdf"
    doc.save(str(p))
    doc.close()
    parsed = PyMuPDFParser().parse(p)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert heads and heads[0].text == "Chapter One"


def test_pdf_toc_driven_with_wrapped_title(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "第一章 绪论", fontname="china-s", fontsize=22)
    page.insert_text((72, 110), "这是绪论正文。", fontname="china-s", fontsize=11)
    page.insert_text((72, 150), "第二章 复数、相位与复基带：", fontname="china-s", fontsize=22)
    page.insert_text((72, 176), "为什么信号要写成复数", fontname="china-s", fontsize=22)
    page.insert_text((72, 214), "这是第二章正文。", fontname="china-s", fontsize=11)
    page.insert_text((72, 250), "2.1 复数坐标", fontname="china-s", fontsize=16)
    page.insert_text((72, 280), "这是小节正文。", fontname="china-s", fontsize=11)
    doc.set_toc([
        [1, "第一章 绪论", 1],
        [1, "第二章 复数、相位与复基带：为什么信号要写成复数", 1],
        [2, "2.1 复数坐标", 1],
    ])
    p = tmp_path / "wrapped.pdf"
    doc.save(str(p))
    doc.close()
    parsed = PyMuPDFParser().parse(p)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [
        ("第一章 绪论", 1),
        ("第二章 复数、相位与复基带：为什么信号要写成复数", 1),
        ("2.1 复数坐标", 2),
    ]
    paras = [b.text for b in parsed.blocks if b.kind == "paragraph"]
    assert "这是第二章正文。" in paras
    assert "为什么信号要写成复数" not in paras


def test_get_parser_registry(docx_file, epub_file, pdf_file, tmp_path):
    assert isinstance(get_parser(docx_file), DocxParser)
    assert isinstance(get_parser(epub_file), EpubParser)
    assert isinstance(get_parser(pdf_file), PyMuPDFParser)
    with pytest.raises(ValueError):
        get_parser(tmp_path / "x.mobi")