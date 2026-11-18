"""论文解析（模块B）：双栏自然阅读序 + 书签目录 + 标题/摘要提取。

论文只作提问上下文，不导入资源库；答案依据仍全部来自库内原文。
"""
import re
from pathlib import Path

import pymupdf

from .models import PaperInfo


def _page_text(page) -> str:
    """按 PDF 自然存储顺序取整页文本（LaTeX 双栏论文按栏存储），过滤纯页码块。"""
    parts = []
    for b in page.get_text("blocks"):
        text = b[4].strip()
        if not text or re.fullmatch(r"\d{1,4}", text):
            continue
        parts.append(text)
    return "\n".join(parts)


def _extract_title(doc) -> str:
    """标题：优先元数据；否则首页最大字号行拼接（截到 Abstract 前）；兜底文件名。"""
    meta = (doc.metadata.get("title") or "").strip()
    if meta:
        return meta
    spans = []
    for block in doc[0].get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for s in line["spans"]:
                if s["text"].strip():
                    spans.append((s["size"], line["bbox"][1], s["text"]))
    if not spans:
        return Path(doc.name).stem
    max_size = max(s[0] for s in spans)
    # 最大字号（≥95%）的行按 y 坐标分组拼接，即标题区
    lines: dict[int, list[str]] = {}
    for size, y, text in spans:
        if size >= max_size * 0.95:
            lines.setdefault(round(y), []).append(text)
    title = " ".join("".join(v) for _, v in sorted(lines.items()))
    title = re.split(r"\bAbstract\b", title)[0].strip()
    return title or Path(doc.name).stem


def _extract_abstract(doc) -> str:
    """摘要：首页 Abstract 到 Index Terms/Keywords/首个章节标题之间的文本。"""
    text = _page_text(doc[0])
    m = re.search(
        r"Abstract\s*[—–\-:]?\s*(.*?)(?:Index Terms|Keywords|I\.\s|1\.\s|Introduction)",
        text, re.S | re.I)
    return m.group(1).strip() if m else ""


def parse_paper(path) -> PaperInfo:
    """解析论文 PDF：标题 + 书签目录 + 摘要 + 页数；无书签时目录为空。"""
    doc = pymupdf.open(str(path))
    try:
        outline = [{"level": lv, "title": t, "page": pg}
                   for lv, t, pg in doc.get_toc()]
        return PaperInfo(_extract_title(doc), outline,
                         _extract_abstract(doc), len(doc))
    finally:
        doc.close()