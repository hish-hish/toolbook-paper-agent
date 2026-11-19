from toolbook.models import Block, SectionNode
from toolbook.structure import (build_tree, extract_number, iter_nodes,
                                is_non_content_section, prune_non_content)


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


# ---------- 非知识节分类器：只剔 system 前置/后置/自测，正式章节与知识附录保留 ----------

def test_classifier_never_removes_original_chapters():
    # 原书正式章节即便标题含 Reference/Index 也绝不剔（doc2 真实误删守卫）
    assert is_non_content_section("2.6.2", "2.6.2 Pilots (Reference Signal) in 5G", "original") is False
    assert is_non_content_section("5.3.1", "5.3.1 Index Modulation ISAC", "original") is False
    assert is_non_content_section("3.1", "3.1 采样定理", "original") is False


def test_classifier_removes_auto_preamble():
    # number==0 是导入自动生成的前言，剔
    assert is_non_content_section("0", "前言", "system") is True


def test_classifier_removes_front_back_matter():
    # system 前置/后置/自测节：中英文前言、目录、参考文献、索引、致谢、本章自测、自测答案
    for num, title in [("S1", "写给读者"), ("S1", "Preface"), ("S1", "Foreword"),
                       ("S2", "Contents"), ("S2", "目录"), ("P6.S5", "参考文献"),
                       ("S8", "Appendix  References"), ("S8", "Bibliography"),
                       ("S9", "索引"), ("S9", "Index"), ("S10", "致谢"),
                       ("S10", "Acknowledgments"), ("1.S1", "本章自测"),
                       ("P6.S1", "附录 A  各章自测答案与求解要点")]:
        assert is_non_content_section(num, title, "system") is True, title


def test_classifier_keeps_knowledge_system_sections():
    # 含知识/参考价值的 system 节保留：符号地图、附录B推导及子节、附录C术语表、附录D、Part 分隔
    for num, title in [("S2", "符号、单位与学习地图"),
                       ("P6.S2", "附录 B  进一步推导与算法实现要点"),
                       ("P6.S2.S1", "B.1 从正交原理完整推出 LMMSE"),
                       ("P6.S3", "附录 C  中英文术语表与常见混淆"),
                       ("P6.S4", "附录 D  文献核验、复现说明与论文引言组织"),
                       ("S3", "Part I Basics of Communications and Sensing")]:
        assert is_non_content_section(num, title, "system") is False, title


def _node(number, title, source, children=None):
    return SectionNode(number, title, 1, source, "p1", "正文", children or [])


def test_prune_drops_non_content_subtrees_keeps_rest():
    # 前言/参考文献整棵剔；正式章保留但其「本章自测」子节剔；知识附录及其子节保留
    tree = [
        _node("0", "前言", "system"),
        _node("1", "第一章 绪论", "original", [
            _node("1.1", "1.1 信号", "original"),
            _node("1.S1", "本章自测", "system"),
        ]),
        _node("P6.S2", "附录 B  进一步推导", "system", [
            _node("P6.S2.S1", "B.1 正交原理", "system"),
        ]),
        _node("P6.S5", "参考文献", "system"),
    ]
    kept = prune_non_content(tree)
    assert [n.number for n in kept] == ["1", "P6.S2"]
    assert [c.number for c in kept[0].children] == ["1.1"]
    assert [c.number for c in kept[1].children] == ["P6.S2.S1"]


def test_prune_empty_and_all_original():
    assert prune_non_content([]) == []
    tree = [_node("1", "第一章", "original"), _node("2", "第二章", "original")]
    assert [n.number for n in prune_non_content(tree)] == ["1", "2"]