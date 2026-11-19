"""出处展示支持：按书名分组出处 + 节标签去编号重复，供界面展示。

纯函数、不依赖 Streamlit，离线可测。分组保留原始索引，确保答案句的引用角标 [i] 不错位。
"""
import re

from .models import SourceRef

# 标题已自带「第X章/节/部分」等中文编号时，前面的数字编号属冗余（如「1 第一章」）
_CHAPTER_TITLE_PAT = re.compile(r"^第[0-9一二三四五六七八九十百零]+\s*[章节節部分篇编編]")


def section_label(number: str, title: str) -> str:
    """拼接节的展示标签，避免编号与标题重复。

    先去掉标题中与 number 相同的前缀；若标题本身以「第X章/节/部分」开头，
    数字编号冗余 → 只返回标题（「第一章 …」而非「1 第一章 …」）；否则返回「编号 标题」。
    「第三方」等非章节词不会被误判；空标题回退为编号本身。
    """
    t = title.removeprefix(number).strip() or title
    if not t:
        return number
    if _CHAPTER_TITLE_PAT.match(t):
        return t
    return f"{number} {t}"


def group_sources_by_book(sources: list[SourceRef]) -> list[tuple[str, list[tuple[int, SourceRef]]]]:
    """按书名分组出处，返回 [(书名, [(原始索引, 出处), ...]), ...]。

    书序按首次出现排列；每条保留其在原 sources 中的索引 i，
    使界面分组展示时引用角标 [i] 仍与答案句一致。
    """
    groups: dict[str, list[tuple[int, SourceRef]]] = {}
    for i, src in enumerate(sources):
        groups.setdefault(src.doc_title, []).append((i, src))
    return list(groups.items())