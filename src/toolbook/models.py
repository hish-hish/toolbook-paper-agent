from dataclasses import dataclass, field


@dataclass
class Block:
    text: str
    kind: str  # "heading" | "paragraph"
    level: int = 0
    locator: str = ""


@dataclass
class ParsedDocument:
    title: str
    blocks: list[Block]


@dataclass
class SectionNode:
    number: str
    title: str
    level: int
    source: str  # "original" | "system"
    locator: str
    text: str
    children: list["SectionNode"] = field(default_factory=list)


@dataclass
class ImportResult:
    doc_id: int
    title: str
    fmt: str
    skipped: bool = False
    sections: int = 0
    chunks: int = 0