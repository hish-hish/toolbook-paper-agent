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
        toc = doc.get_toc()
        if len(toc) >= 3:
            blocks = self._parse_with_toc(doc, toc)
        else:
            blocks = self._parse_by_font(doc, toc)
        title = (doc.metadata.get("title") or "").strip() or Path(path).stem
        doc.close()
        return ParsedDocument(title, blocks)

    def _parse_with_toc(self, doc, toc) -> list[Block]:
        anchors = []
        for lv, title, pg in toc:
            pno = min(max(pg - 1, 0), len(doc) - 1)
            page = doc[pno]
            rects = page.search_for(title)
            if not rects:
                rects = page.search_for(re.sub(r"\s+", " ", title).strip())
            if not rects:
                for n in range(len(title) - 1, 5, -1):
                    rects = page.search_for(title[:n])
                    if rects:
                        break
            y = rects[0].y0 if rects else -1.0
            anchors.append((pno, y, lv, title))
        anchors.sort(key=lambda a: (a[0], a[1]))

        page_lines: dict[int, list[tuple[float, str]]] = {}
        for pno, page in enumerate(doc):
            lines = []
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if text:
                        lines.append((line["bbox"][1], text))
            lines.sort()
            page_lines[pno] = lines

        blocks: list[Block] = []
        first = anchors[0]
        for pg in range(first[0] + 1):
            for ly, text in page_lines.get(pg, []):
                if (pg, ly) < (first[0], first[1]):
                    blocks.append(Block(text, "paragraph", 0, f"p{pg + 1}"))
        for i, (pno, y, lv, title) in enumerate(anchors):
            blocks.append(Block(title, "heading", lv, f"p{pno + 1}"))
            end = anchors[i + 1][:2] if i + 1 < len(anchors) else (len(doc), float("inf"))
            title_norm = _norm(title)
            for pg in range(pno, min(end[0], len(doc) - 1) + 1):
                for ly, text in page_lines.get(pg, []):
                    if (pg, ly) <= (pno, y) or (pg, ly) >= end:
                        continue
                    if _norm(text) in title_norm:
                        continue
                    blocks.append(Block(text, "paragraph", 0, f"p{pg + 1}"))
        return blocks

    def _parse_by_font(self, doc, toc) -> list[Block]:
        toc_map = {_norm(t): lv for lv, t, _ in toc}
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
        return blocks