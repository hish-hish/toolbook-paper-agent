import re
from pathlib import Path

from ..models import Block, ParsedDocument
from ..structure import extract_number

_NUM_HEAD = re.compile(
    r"^(?:第\s*[0-9一二三四五六七八九十百零]+\s*[章节節]|\d+(?:\.\d+)+[\s.、．])")


def _fix_number_spacing(s: str) -> str:
    return re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", s)


class MinerUParser:
    """MinerU 4.x 进程内解析（无需启动服务）。模型在进程退出时释放显存。"""

    def parse(self, path: Path) -> ParsedDocument:
        from mineru.parser import parse as mineru_parse

        result = mineru_parse(str(path), page_range="all")
        d = result.to_dict()
        blocks = []
        for page in d["pages"]:
            loc = f"p{page['page_idx'] + 1}"
            for b in page["blocks"]:
                text = "".join(c.get("content", "") for c in b.get("content", [])
                               if c.get("type") == "text").strip()
                if not text:
                    continue
                if b["type"] == "paragraph_title":
                    text = _fix_number_spacing(text)
                    level = b.get("level") or 1
                    num = extract_number(text)
                    if num:
                        level = min(num.count(".") + 1, 4)
                    blocks.append(Block(text, "heading", level, loc))
                elif b["type"] == "text":
                    cand = _fix_number_spacing(text)
                    if len(cand) <= 60 and _NUM_HEAD.match(cand):
                        num = extract_number(cand)
                        level = min(num.count(".") + 1, 4) if num else 2
                        blocks.append(Block(cand, "heading", level, loc))
                    else:
                        blocks.append(Block(text, "paragraph", 0, loc))
        title = (d.get("metadata", {}).get("document", {}).get("title") or "").strip()
        return ParsedDocument(title or Path(path).stem, blocks)