"""章节树构建：规则优先提取编号标题，无结构时可选 LLM 兜底切分（系统编号）。"""
import re
from collections.abc import Iterator

from .models import Block, SectionNode

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn2num(s: str) -> int:
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
    return total + num


_NUM_PATTERNS = [
    (re.compile(r"^第\s*([0-9一二三四五六七八九十百零]+)\s*部分"),
     lambda m: "P" + str(cn2num(m.group(1)))),
    (re.compile(r"^第\s*([0-9一二三四五六七八九十百零]+)\s*[章节節編编篇]"),
     lambda m: str(cn2num(m.group(1)))),
    (re.compile(r"^(?:chapter|section)\s+(\d+(?:\.\d+)*)", re.I),
     lambda m: m.group(1)),
    (re.compile(r"^(\d+(?:\.\d+)+)(?:[\s.、．]|$)"),
     lambda m: m.group(1)),
    (re.compile(r"^(\d+)[.、．\s]+\S"),
     lambda m: m.group(1)),
]


def extract_number(title: str) -> str | None:
    for pat, conv in _NUM_PATTERNS:
        m = pat.match(title.strip())
        if m:
            return conv(m)
    return None


_PROMOTE = [
    (re.compile(r"^第\s*[0-9一二三四五六七八九十百零]+\s*章"), 1),
    (re.compile(r"^第\s*[0-9一二三四五六七八九十百零]+\s*[节節]"), 2),
    (re.compile(r"^\d+(?:\.\d+)+[\s.、．]"), None),
]


def _promote_numbered_paragraphs(blocks: list[Block]) -> list[Block]:
    if any(b.kind == "heading" for b in blocks):
        return blocks
    out, promoted = [], 0
    for b in blocks:
        nb = b
        if b.kind == "paragraph" and len(b.text) <= 60:
            for pat, lvl in _PROMOTE:
                if pat.match(b.text):
                    if lvl is None:
                        dots = b.text.split()[0].rstrip(".、．").count(".")
                        lvl = min(dots + 1, 4)
                    nb = Block(b.text, "heading", lvl, b.locator)
                    promoted += 1
                    break
        out.append(nb)
    return out if promoted >= 2 else blocks


def build_tree(blocks: list[Block], doc_title: str = "", title_proposer=None) -> list[SectionNode]:
    """由解析块建章节树：编号标题→原书编号；无编号标题→S 前缀系统编号。

    完全无结构时：有 title_proposer 则走 LLM 兜底切分（D5），否则单节兜底。
    """
    blocks = _promote_numbered_paragraphs(blocks)
    roots: list[SectionNode] = []
    stack: list[SectionNode] = []
    counters: dict[str, int] = {}
    preamble: list[str] = []
    for b in blocks:
        if b.kind != "heading":
            if stack:
                stack[-1].text += ("\n" if stack[-1].text else "") + b.text
            else:
                preamble.append(b.text)
            continue
        while stack and stack[-1].level >= b.level:
            stack.pop()
        num = extract_number(b.text)
        if num:
            source = "original"
        else:
            key = stack[-1].number if stack else ""
            counters[key] = counters.get(key, 0) + 1
            num = f"{key}.S{counters[key]}" if key else f"S{counters[key]}"
            source = "system"
        node = SectionNode(num, b.text, b.level, source, b.locator, "")
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    if not roots:
        text = "\n".join(b.text for b in blocks)
        # LLM 兜底（D5）：提议标题并按位置切分；失败回退单节
        if title_proposer is not None:
            nodes = _llm_fallback_nodes(blocks, text, title_proposer)
            if nodes:
                return nodes
        roots = [SectionNode("1", doc_title or "全文", 1, "system", "", text)]
    elif preamble:
        roots.insert(0, SectionNode("0", "前言", 1, "system", "", "\n".join(preamble)))
    return roots


def _llm_fallback_nodes(blocks: list[Block], text: str, proposer) -> list[SectionNode]:
    """按 LLM 提议标题切分无结构文本：标题必须能在某个块中定位，至少 2 个才生效。"""
    try:
        titles = proposer(text)
    except Exception:
        return []
    # 每个标题定位到首次出现的块索引
    cuts = []
    for t in titles:
        for i, b in enumerate(blocks):
            if t in b.text:
                cuts.append((i, t))
                break
    cuts.sort(key=lambda x: x[0])
    # 同块去重；不足 2 个切分点则兜底失败
    uniq = []
    for i, t in cuts:
        if not uniq or uniq[-1][0] != i:
            uniq.append((i, t))
    if len(uniq) < 2:
        return []
    nodes = []
    # 首个标题前的内容作为前言保留
    if uniq[0][0] > 0:
        pre = "\n".join(b.text for b in blocks[:uniq[0][0]])
        nodes.append(SectionNode("0", "前言", 1, "system", blocks[0].locator, pre))
    for k, (start, title) in enumerate(uniq):
        end = uniq[k + 1][0] if k + 1 < len(uniq) else len(blocks)
        body = "\n".join(b.text for b in blocks[start:end])
        nodes.append(SectionNode(f"S{k + 1}", title, 1, "system", blocks[start].locator, body))
    return nodes


def iter_nodes(roots: list[SectionNode]) -> Iterator[SectionNode]:
    for n in roots:
        yield n
        yield from iter_nodes(n.children)