"""出处展示支持离线单测：按书分组（角标不变）+ 节标签去编号重复。"""
from toolbook.models import SourceRef
from toolbook.sources import group_sources_by_book, section_label


def _src(book, num):
    # 构造最小出处条目
    return SourceRef(book, num, f"{num} 标题", "original", "p1")


def test_group_empty():
    # 空出处 → 空分组
    assert group_sources_by_book([]) == []


def test_group_single_book():
    # 同一本书：一个分组，角标按原序 0,1
    sources = [_src("书A", "1.1"), _src("书A", "1.2")]
    groups = group_sources_by_book(sources)
    assert len(groups) == 1
    book, items = groups[0]
    assert book == "书A"
    assert [i for i, _ in items] == [0, 1]


def test_group_multi_book_preserves_indices_and_order():
    # 交错出处：书A[0]、书B[1]、书A[2] → 按书分组，书序按首次出现（A 先 B 后），角标不变
    sources = [_src("书A", "1.1"), _src("书B", "2.1"), _src("书A", "1.2")]
    groups = group_sources_by_book(sources)
    assert [b for b, _ in groups] == ["书A", "书B"]
    assert [i for i, _ in groups[0][1]] == [0, 2]
    assert [i for i, _ in groups[1][1]] == [1]
    # 角标完整性：每个 (i, src) 必须与原列表对应位置一致（引用 [i] 不能错位）
    for _book, items in groups:
        for i, src in items:
            assert src is sources[i]


# ---------- section_label：编号+标题去重复（标题自带「第X章/节」时不再叠加数字编号） ----------

def test_label_chinese_chapter_drops_redundant_number():
    # 标题已含「第一章/第十六章」，数字编号 1/16 冗余 → 只显示标题本身
    assert section_label("1", "第一章 从一个无线回波开始理解 ISAC") == "第一章 从一个无线回波开始理解 ISAC"
    assert section_label("16", "第十六章 统一系统模型：先定义谁知道什么") == "第十六章 统一系统模型：先定义谁知道什么"


def test_label_chinese_part_drops_redundant_number():
    # 「第一部分」同理：P1 冗余 → 只显示「第一部分 …」
    assert section_label("P1", "第一部分 建立共同语言") == "第一部分 建立共同语言"


def test_label_decimal_self_numbered_dedups_normally():
    # 标题自带「3.1」编号：removeprefix 正常去重，仍保留 3.1 前缀
    assert section_label("3.1", "3.1 采样不等于随意少取一些点") == "3.1 采样不等于随意少取一些点"


def test_label_system_appendix_keeps_number():
    # 系统编号附录标题不含「第X章」→ 保留 P6.S3 定位编号
    assert section_label("P6.S3", "附录 C 中英文术语表与常见混淆") == "P6.S3 附录 C 中英文术语表与常见混淆"


def test_label_plain_title_keeps_number():
    # 普通无编号标题：编号+标题正常拼接
    assert section_label("2.3", "信道估计") == "2.3 信道估计"


def test_label_third_party_not_mistaken_for_chapter():
    # 「第三方」以「第」开头但不是「第X章」→ 不能误删编号 5.2
    assert section_label("5.2", "5.2 第三方测试") == "5.2 第三方测试"


def test_label_empty_title_falls_back_to_number():
    # 空标题回退为编号本身，不留尾随空格
    assert section_label("1", "") == "1"