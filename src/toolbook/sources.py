"""出处展示支持：把答案出处目录按书名分组，供界面「分书目参考」展示。

纯函数、不依赖 Streamlit，离线可测。分组保留原始索引，确保答案句的引用角标 [i] 不错位。
"""
from .models import SourceRef


def group_sources_by_book(sources: list[SourceRef]) -> list[tuple[str, list[tuple[int, SourceRef]]]]:
    """按书名分组出处，返回 [(书名, [(原始索引, 出处), ...]), ...]。

    书序按首次出现排列；每条保留其在原 sources 中的索引 i，
    使界面分组展示时引用角标 [i] 仍与答案句一致。
    """
    groups: dict[str, list[tuple[int, SourceRef]]] = {}
    for i, src in enumerate(sources):
        groups.setdefault(src.doc_title, []).append((i, src))
    return list(groups.items())