"""论文解析离线单测：用 pymupdf 现造双栏+书签夹具 PDF，验证标题/目录/摘要/阅读序。"""
import pymupdf
import pytest

from toolbook.paper import parse_paper


@pytest.fixture
def paper_path(tmp_path):
    # 现造一篇最小论文：大字号标题 + 摘要 + 双栏正文（左栏先写入，模拟 LaTeX 存储序）+ 书签
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "Test Paper on Signal Sensing", fontsize=20)
    page.insert_text((72, 120), "Abstract—This paper studies multipath sensing.", fontsize=9)
    page.insert_text((72, 140), "Index Terms—sensing, multipath.", fontsize=9)
    page.insert_text((72, 200), "Left column first line.", fontsize=10)
    page.insert_text((72, 220), "Left column second line.", fontsize=10)
    page.insert_text((320, 200), "Right column first line.", fontsize=10)
    # 正文中部的大字号首字母（如章节标题 drop cap），不得被误认为论文标题
    page.insert_text((72, 570), "I", fontsize=28)
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((72, 80), "II. Method", fontsize=11)
    page2.insert_text((72, 110), "Method body text.", fontsize=10)
    doc.set_toc([[1, "I. Introduction", 1], [1, "II. Method", 2]])
    path = tmp_path / "paper.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_parse_paper_title_and_pages(paper_path):
    # 标题取首页最大字号行（而非文件名），页数正确
    info = parse_paper(paper_path)
    assert info.title == "Test Paper on Signal Sensing"
    assert info.n_pages == 2


def test_parse_paper_outline(paper_path):
    # 目录来自书签：层级/标题/页码齐全
    info = parse_paper(paper_path)
    assert info.outline == [
        {"level": 1, "title": "I. Introduction", "page": 1},
        {"level": 1, "title": "II. Method", "page": 2},
    ]


def test_parse_paper_abstract(paper_path):
    # 摘要截取 Abstract 与 Index Terms 之间
    info = parse_paper(paper_path)
    assert "multipath sensing" in info.abstract
    assert "Index Terms" not in info.abstract


def test_paper_context(paper_path):
    # 上下文串含标题与摘要，供查询改写/生成使用
    info = parse_paper(paper_path)
    ctx = info.context()
    assert "Test Paper on Signal Sensing" in ctx and "multipath sensing" in ctx


def test_column_reading_order(paper_path):
    # 双栏阅读序：左栏整段在右栏之前（自然存储序，不按 y 交错）
    from toolbook.paper import _page_text
    doc = pymupdf.open(str(paper_path))
    text = _page_text(doc[0])
    doc.close()
    assert text.index("Left column second line") < text.index("Right column first line")


def test_no_toc_paper(tmp_path):
    # 无书签论文：目录为空列表，不报错（UI 显示"无目录"）
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Plain Paper", fontsize=16)
    path = tmp_path / "plain.pdf"
    doc.save(str(path))
    doc.close()
    info = parse_paper(path)
    assert info.outline == [] and info.title == "Plain Paper"