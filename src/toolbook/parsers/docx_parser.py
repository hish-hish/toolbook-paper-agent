import re
from pathlib import Path

from docx import Document

from ..models import Block, ParsedDocument


class DocxParser:
    def parse(self, path: Path) -> ParsedDocument:
        d = Document(str(path))
        blocks = []
        for i, p in enumerate(d.paragraphs, 1):
            text = p.text.strip()
            if not text:
                continue
            m = re.match(r"(?:Heading|标题)\s*(\d)", p.style.name or "")
            loc = f"p{i}"
            if m:
                blocks.append(Block(text, "heading", int(m.group(1)), loc))
            else:
                blocks.append(Block(text, "paragraph", 0, loc))
        title = (d.core_properties.title or "").strip() or Path(path).stem
        return ParsedDocument(title, blocks)