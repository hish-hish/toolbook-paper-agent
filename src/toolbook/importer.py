import hashlib
from pathlib import Path

from .chunking import child_chunks, parent_parts
from .config import DEFAULT_DB
from .models import ImportResult, SectionNode
from .parsers import get_parser
from .parsers.base import Parser
from .store import LibraryStore
from .structure import build_tree


def import_file(path, db_path=DEFAULT_DB, parser: Parser | None = None) -> ImportResult:
    path = Path(path)
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    store = LibraryStore(db_path)
    try:
        existing = store.find_by_hash(file_hash)
        if existing:
            return ImportResult(existing["doc_id"], existing["title"],
                                existing["format"], skipped=True)
        parsed = (parser or get_parser(path)).parse(path)
        tree = build_tree(parsed.blocks, doc_title=parsed.title)
        fmt = path.suffix.lstrip(".").lower()
        n_sec = n_chunk = 0
        with store.transaction():
            doc_id = store.add_document(parsed.title, fmt, file_hash, path)
            for root in tree:
                s, c = _save_node(store, doc_id, root, None)
                n_sec += s
                n_chunk += c
        return ImportResult(doc_id, parsed.title, fmt, sections=n_sec, chunks=n_chunk)
    finally:
        store.close()


def _save_node(store, doc_id, node: SectionNode, parent_id):
    first_id = None
    n_sec = n_chunk = 0
    for i, part in enumerate(parent_parts(node.text), 1):
        sid = store.insert_section(doc_id, parent_id, node.number, node.title,
                                   node.level, node.source, node.locator, i, part)
        if first_id is None:
            first_id = sid
        n_sec += 1
        n_chunk += store.insert_chunks(sid, child_chunks(part))
    for child in node.children:
        s, c = _save_node(store, doc_id, child, first_id)
        n_sec += s
        n_chunk += c
    return n_sec, n_chunk