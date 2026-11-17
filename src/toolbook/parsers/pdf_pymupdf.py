import re
from collections import Counter
from pathlib import Path

import pymupdf

from ..models import Block, ParsedDocument


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


class PyMuPDFParser:
    def parse(self, path: Path) -> ParsedDocument:
        doc = pymupdf.open(str(path))
        toc_map = {_norm(t): lv for lv, t, _ in doc.get_toc()}
        lines = []
        sizes: Counter = Counter()
        for pno, page in enumerate(doc, 1):
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    spans = line["spans"]
                    text = "".join(s["text"] for s in spans).strip()
                    if not text:
                        continue
                    size = max(s["size"] for s in spans)
                    lines.append((text, size, pno))
                    sizes[round(size, 1)] += len(text)
        body = sizes.most_common(1)[0][0] if sizes else 11.0
        blocks = []
        for text, size, page in lines:
            loc = f"p{page}"
            level = toc_map.get(_norm(text), 0)
            if not level and len(text) <= 80:
                m = re.match(r"^(\d+(?:\.\d+)+)[\s.、．]", text)
                if m and size >= body * 1.05:
                    level = min(m.group(1).count(".") + 1, 4)
                elif size >= body * 1.5:
                    level = 1
                elif size >= body * 1.15:
                    level = 2
            blocks.append(Block(text, "heading" if level else "paragraph", level, loc))
        title = (doc.metadata.get("title") or "").strip() or Path(path).stem
        doc.close()
        return ParsedDocument(title, blocks)