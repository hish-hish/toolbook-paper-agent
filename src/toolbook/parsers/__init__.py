from pathlib import Path

from .base import Parser
from .docx_parser import DocxParser
from .epub_parser import EpubParser
from .pdf_pymupdf import PyMuPDFParser

_REGISTRY = {".docx": DocxParser, ".epub": EpubParser, ".pdf": PyMuPDFParser}


def get_parser(path: Path) -> Parser:
    cls = _REGISTRY.get(Path(path).suffix.lower())
    if cls is None:
        raise ValueError(f"不支持的格式: {Path(path).suffix}（支持 docx/epub/pdf）")
    return cls()