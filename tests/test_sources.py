"""出处按书分组纯函数离线单测：分组正确、书序按首次出现、引用角标索引不变。"""
from toolbook.models import SourceRef
from toolbook.sources import group_sources_by_book


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