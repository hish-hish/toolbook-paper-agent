from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from ..models import Block, ParsedDocument


class EpubParser:
    def parse(self, path: Path) -> ParsedDocument:
        book = epub.read_epub(str(path))
        meta = book.get_metadata("DC", "title")
        title = meta[0][0] if meta else Path(path).stem
        items = {it.get_id(): it for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
        blocks = []
        for idx, (sid, _) in enumerate(book.spine, 1):
            it = items.get(sid)
            if it is None:
                continue
            soup = BeautifulSoup(it.get_content(), "xml")
            if soup.find("nav"):
                continue
            loc = f"spine{idx}:{it.get_name()}"
            for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "div"]):
                if el.name in ("div", "li") and el.find(["p", "div", "h1", "h2", "h3", "h4"]):
                    continue
                text = el.get_text(" ", strip=True)
                if not text:
                    continue
                if el.name.startswith("h"):
                    blocks.append(Block(text, "heading", int(el.name[1]), loc))
                else:
                    blocks.append(Block(text, "paragraph", 0, loc))
        return ParsedDocument(title, blocks)