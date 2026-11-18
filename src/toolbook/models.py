"""核心数据模型：解析块、章节树节点、导入结果、核验句与最终答案。"""
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


@dataclass
class VerifiedSentence:
    """一条核验通过的答案句：文本 + 类型 + 引用索引 + 核验徽章 + 原文依据。"""
    text: str
    kind: str    # "excerpt"（原文摘录）| "summary"（归纳）
    ref: int     # 引用检索结果（hits）的索引
    badge: str   # "mechanical"（机械核验✓）| "llm"（LLM核验✓）
    quote: str   # 支撑该句的原文片段


@dataclass
class SourceRef:
    """出处目录条目：书名 + 章节号 + 标题 + 编号来源 + 原文定位。"""
    doc_title: str
    number: str
    title: str
    source: str  # "original" | "system"
    locator: str


@dataclass
class AnswerResult:
    """最终答案：核验句 + 出处目录；拒答时 sentences 为空且 refused=True。"""
    sentences: list[VerifiedSentence]
    sources: list[SourceRef]
    refused: bool = False
    retries: int = 0
    searched: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class PaperInfo:
    """模块B 论文上下文：标题 + 书签目录 + 摘要 + 页数；论文不入资源库。"""
    title: str
    outline: list[dict]  # [{"level", "title", "page"}]
    abstract: str
    n_pages: int

    def context(self) -> str:
        """供 LLM 的提问背景文本：标题 + 摘要（截断 1500 字）。"""
        return f"论文《{self.title}》\n摘要：{self.abstract}"[:1500]