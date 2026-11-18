from toolbook.models import Block
from toolbook.structure import build_tree, extract_number, iter_nodes


def h(text, level):
    return Block(text, "heading", level, "p1")


def p(text):
    return Block(text, "paragraph", 0, "p1")


def test_extract_number_chinese():
    assert extract_number("第三章 傅里叶变换") == "3"
    assert extract_number("第12节 性质") == "12"


def test_extract_number_decimal():
    assert extract_number("3.2.1 傅里叶变换的性质") == "3.2.1"
    assert extract_number("Chapter 2 Signals") == "2"
    assert extract_number("普通标题没有编号") is None


def test_numbered_headings_original():
    tree = build_tree([h("第1章 绪论", 1), p("正文A"), h("1.1 信号", 2), p("正文B"), h("第2章 系统", 1)])
    assert [n.number for n in tree] == ["1", "2"]
    assert tree[0].children[0].number == "1.1"
    assert tree[0].children[0].source == "original"
    assert tree[0].children[0].text == "正文B"
    assert tree[0].text == "正文A"


def test_unnumbered_headings_system():
    tree = build_tree([h("绪论", 1), h("信号", 2), h("系统", 2), h("变换", 1)])
    assert [n.number for n in tree] == ["S1", "S2"]
    assert [c.number for c in tree[0].children] == ["S1.S1", "S1.S2"]
    assert all(n.source == "system" for n in iter_nodes(tree))


def test_system_number_avoids_collision_with_original():
    tree = build_tree([h("第1章 绪论", 1), h("1.1 信号", 2), h("本章自测", 2)])
    nums = [c.number for c in tree[0].children]
    assert nums == ["1.1", "1.S1"]


def test_part_numbering():
    assert extract_number("第一部分 建立共同语言") == "P1"
    tree = build_tree([h("第一部分 基础", 1), h("第一章 绪论", 2), h("1.1 信号", 3)])
    assert tree[0].number == "P1"
    assert tree[0].children[0].number == "1"
    assert tree[0].children[0].children[0].number == "1.1"


def test_no_headings_promotes_numbered_paragraphs():
    blocks = [p("第1章 绪论"), p("正文A"), p("1.1 信号"), p("正文B"), p("第2章 系统"), p("正文C")]
    tree = build_tree(blocks)
    assert [n.number for n in tree] == ["1", "2"]
    assert tree[0].children[0].number == "1.1"
    assert tree[0].source == "original"


def test_no_structure_single_system_section():
    tree = build_tree([p("随便一段"), p("又一段")], doc_title="无名书")
    assert len(tree) == 1
    assert tree[0].source == "system"
    assert tree[0].title == "无名书"
    assert "随便一段" in tree[0].text


def test_preamble_before_first_heading():
    tree = build_tree([p("版权页"), h("第1章 绪论", 1)])
    assert tree[0].number == "0"
    assert tree[0].title == "前言"
    assert tree[1].number == "1"