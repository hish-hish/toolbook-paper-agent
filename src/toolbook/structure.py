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


# 非知识节标题关键词：前置（前言/序/目录/致谢）、后置（参考文献/索引）、每章自测及其答案。
# 只用于 system 系统编号节；含知识的附录（推导/术语表/符号地图）标题不含这些词，天然保留。
_NON_CONTENT_PAT = re.compile(
    "前言|写给读者|序言|出版说明|目录|contents|preface|foreword|acknowledg|致谢"
    "|参考文献|references|bibliography|索引|index|本章自测|自测答案|各章自测", re.I)


def is_non_content_section(number: str, title: str, source: str) -> bool:
    """判定一节是否为「与正式章节无关」的非知识内容（前言/目录/参考文献/自测等）。

    只判 system 系统编号节：original 原书正式章节一律保留（即便标题含 Reference/Index，
    如 doc2 的 2.6.2 Reference Signal、5.3.1 Index Modulation，绝不能误删）。
    number=="0" 是导入自动生成的前言；其余按标题关键词命中。知识附录不命中故保留。
    """
    if source != "system":
        return False
    if number == "0":
        return True
    return bool(_NON_CONTENT_PAT.search(title))


def prune_non_content(roots: list[SectionNode]) -> list[SectionNode]:
    """递归剪掉非知识节及其整棵子树，保留正式章节与知识附录（导入入库前调用）。"""
    kept = []
    for n in roots:
        if is_non_content_section(n.number, n.title, n.source):
            continue
        n.children = prune_non_content(n.children)
        kept.append(n)
    return kept