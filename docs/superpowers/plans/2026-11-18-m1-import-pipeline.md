# M1 导入管道实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现"DOCX/PDF/EPUB → 解析 → 章节树 → 父子块分块 → SQLite 入库"的完整导入管道，附 CLI 与三格式演示脚本。

**Architecture:** 核心逻辑放独立包 `src/toolbook`（D12 内核与 UI 分离）。解析器做成可替换接口（D3 止损条款）：默认 PyMuPDF+规则，MinerU 限时尝试、成功则加适配器。解析产物统一为 Block 流 → 规则建章节树（D5，LLM 兜底留到 M3 接 LLM 客户端时补）→ 父子块分块（D6）→ SQLite 三表（D13，文件哈希幂等）。

**Tech Stack:** Python 3.13（.venv 已建）、uv 管理依赖；python-docx、ebooklib、beautifulsoup4+lxml、PyMuPDF；pytest。

**Spec:** `项目计划书.md`（v0.3）第 1/2/4/7 节 + `docs/决策点详解/D03/D04/D05/D06/D13`。

## Global Constraints

- 比赛截止 2026-11-30；M1 验收：3 种格式各 1 本导入成功，章节号与原书目录一致。
- 内核与 UI 分离：核心逻辑全部在 `src/toolbook` 包，CLI 只是薄壳。
- 解析器可替换接口：PDF 默认 PyMuPDF+规则；MinerU 配置限时 1 天（11.18），失败即降级，不阻塞下游。
- 导入幂等：SHA-256 文件哈希去重，重复导入跳过。
- 章节来源标记：`original`（原书）/ `system`（系统编号），一路透传。
- 子块目标 300 字、父块上限 2000 字（超长小节切多个 part，章节号不变）。
- 数据目录 `data/`（gitignore）；数据库 `data/library.db`。
- 不引入服务型组件；不新增已定案之外的选型。
- GitHub 网络当前不通（connection reset）：只本地 commit，不 push；remote 待用户建仓库后配置。
- 每个任务结束 commit 一次；commit message 用 conventional 风格（feat/test/chore）。

## 文件结构

```
.gitignore                          忽略 .venv/data/__pycache__ 等
pyproject.toml                      uv 依赖 + pytest 配置（修改）
src/toolbook/__init__.py
src/toolbook/config.py              数据目录/默认 DB 路径
src/toolbook/models.py              Block/ParsedDocument/SectionNode/ImportResult
src/toolbook/structure.py           章节树构建（编号正则+系统编号+无标题提升规则）
src/toolbook/chunking.py            父子块切分
src/toolbook/store.py               SQLite 三表 + 事务 + 幂等查询
src/toolbook/parsers/__init__.py    get_parser 注册表
src/toolbook/parsers/base.py        Parser 协议
src/toolbook/parsers/docx_parser.py
src/toolbook/parsers/epub_parser.py
src/toolbook/parsers/pdf_pymupdf.py
src/toolbook/parsers/pdf_mineru.py  （MinerU 尝试成功才建）
src/toolbook/importer.py            import_file 编排
src/toolbook/cli.py                 import/list/tree/show
scripts/make_demo_books.py          生成三格式示例书
scripts/demo_m1.py                  M1 演示：导入+章节树+直查+幂等
tests/test_structure.py
tests/test_chunking.py
tests/test_store.py
tests/test_parsers.py
tests/test_importer.py
```

统一中间表示（所有解析器的产物）：`Block(text, kind="heading"|"paragraph", level, locator)`；locator 格式：PDF `p页码`、DOCX `p段落号`、EPUB `spine序号:文件名`。

---

### Task 1: 脚手架 + 依赖 + 数据模型

**Files:**
- Create: `.gitignore`, `src/toolbook/__init__.py`, `src/toolbook/config.py`, `src/toolbook/models.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `Block(text: str, kind: str, level: int = 0, locator: str = "")`；`ParsedDocument(title: str, blocks: list[Block])`；`SectionNode(number, title, level, source, locator, text, children)`；`ImportResult(doc_id, title, fmt, skipped, sections, chunks)`；`DEFAULT_DB: Path`、`DATA_DIR: Path`。

- [ ] **Step 1: 写 .gitignore**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
dist/
*.egg-info/
```

- [ ] **Step 2: uv 安装依赖**

Run: `uv add python-docx ebooklib beautifulsoup4 lxml pymupdf && uv add --dev pytest`
Expected: pyproject.toml dependencies 更新，.venv 安装成功。若 pypi 慢/失败，改 `uv add --default-index https://pypi.tuna.tsinghua.edu.cn/simple ...`。

- [ ] **Step 3: pyproject.toml 追加打包与 pytest 配置**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/toolbook"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 4: 写 models.py 与 config.py**

```python
# src/toolbook/models.py
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
```

```python
# src/toolbook/config.py
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "library.db"
```

`src/toolbook/__init__.py` 为空文件。

- [ ] **Step 5: 验证安装**

Run: `uv run python -c "import docx, ebooklib, fitz, bs4; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml uv.lock src/
git commit -m "chore: scaffold toolbook package and dependencies"
```

（首次 commit 会带上已暂存的 docs/计划书/.idea，属预期。）

---

### Task 2: 章节树构建 structure.py（TDD）

**Files:**
- Create: `src/toolbook/structure.py`, `tests/test_structure.py`

**Interfaces:**
- Consumes: `Block`, `SectionNode`（Task 1）
- Produces: `build_tree(blocks: list[Block], doc_title: str = "") -> list[SectionNode]`；`extract_number(title: str) -> str | None`；`iter_nodes(roots) -> Iterator[SectionNode]`（DFS，含父节点）。

规则（D5）：
1. 有 heading 块：按 level 用栈建树。标题带编号（`第X章/节`、`Chapter N`、`3.2.1 xxx`）→ `source="original"`；不带编号 → 按父章节号+同级计数器生成系统编号，`source="system"`。
2. 全文无 heading：把"短行（≤60字）且以编号开头"的段落提升为 heading（`第X章`→1级、`第X节`→2级、`N.N.N`→点数+1级，上限4），至少提升 2 个才生效；然后走规则 1。
3. 仍无结构：整篇作为一个 `system` 章节（number="1"，标题=书名或"全文"）。
4. 首个 heading 之前的正文 → number="0" 的"前言"节点（system）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_structure.py
from toolbook.models import Block
from toolbook.structure import build_tree, extract_number, iter_nodes

def h(text, level): return Block(text, "heading", level, "p1")
def p(text): return Block(text, "paragraph", 0, "p1")

def test_extract_number_chinese():
    assert extract_number("第三章 傅里叶变换") == "3"
    assert extract_number("第12节 性质") == "12"

def test_extract_number_decimal():
    assert extract_number("3.2.1 傅里叶变换的性质") == "3.2.1"
    assert extract_number("Chapter 2 Signals") == "2"
    assert extract_number("普通标题没有编号") is None

def test_numbered_headings_original():
    tree = build_tree([h("第1章 绪论", 1), p("正文A"), h("1.1 信号", 2), p("正文B"), h("第2章 系统", 1)])
    assert [n.number for n in tree] == ["1", "2"]
    assert tree[0].children[0].number == "1.1"
    assert tree[0].children[0].source == "original"
    assert tree[0].children[0].text == "正文B"
    assert tree[0].text == "正文A"

def test_unnumbered_headings_system():
    tree = build_tree([h("绪论", 1), h("信号", 2), h("系统", 2), h("变换", 1)])
    assert [n.number for n in tree] == ["1", "2"]
    assert [c.number for c in tree[0].children] == ["1.1", "1.2"]
    assert all(n.source == "system" for n in iter_nodes(tree))

def test_no_headings_promotes_numbered_paragraphs():
    blocks = [p("第1章 绪论"), p("正文A"), p("1.1 信号"), p("正文B"), p("第2章 系统"), p("正文C")]
    tree = build_tree(blocks)
    assert [n.number for n in tree] == ["1", "2"]
    assert tree[0].children[0].number == "1.1"
    assert tree[0].source == "original"

def test_no_structure_single_system_section():
    tree = build_tree([p("随便一段"), p("又一段")], doc_title="无名书")
    assert len(tree) == 1
    assert tree[0].source == "system"
    assert tree[0].title == "无名书"
    assert "随便一段" in tree[0].text

def test_preamble_before_first_heading():
    tree = build_tree([p("版权页"), h("第1章 绪论", 1)])
    assert tree[0].number == "0"
    assert tree[0].title == "前言"
    assert tree[1].number == "1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_structure.py -v`
Expected: FAIL（ModuleNotFoundError: toolbook.structure）

- [ ] **Step 3: 实现 structure.py**

```python
# src/toolbook/structure.py
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

def build_tree(blocks: list[Block], doc_title: str = "") -> list[SectionNode]:
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
            num = f"{key}.{counters[key]}" if key else str(counters[key])
            source = "system"
        node = SectionNode(num, b.text, b.level, source, b.locator, "")
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    if preamble:
        roots.insert(0, SectionNode("0", "前言", 1, "system", "", "\n".join(preamble)))
    if not roots:
        text = "\n".join(b.text for b in blocks)
        roots = [SectionNode("1", doc_title or "全文", 1, "system", "", text)]
    return roots

def iter_nodes(roots: list[SectionNode]) -> Iterator[SectionNode]:
    for n in roots:
        yield n
        yield from iter_nodes(n.children)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_structure.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/structure.py tests/test_structure.py
git commit -m "feat: rule-based section tree builder with system-numbering fallback"
```

---

### Task 3: 父子块分块 chunking.py（TDD）

**Files:**
- Create: `src/toolbook/chunking.py`, `tests/test_chunking.py`

**Interfaces:**
- Consumes: 纯文本
- Produces: `child_chunks(text: str, target: int = 300) -> list[str]`；`parent_parts(text: str, max_chars: int = 2000) -> list[str]`（空文本返回 `[""]`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chunking.py
from toolbook.chunking import child_chunks, parent_parts

def test_child_chunks_size_and_sentences():
    text = "".join(f"这是第{i}个句子，用来测试分块边界。" for i in range(60))
    chunks = child_chunks(text, target=300)
    assert all(len(c) <= 330 for c in chunks)
    assert all(c.endswith("。") for c in chunks)
    assert "".join(chunks) == text

def test_child_chunks_short_text_single():
    assert child_chunks("一句话。") == ["一句话。"]

def test_parent_parts_split_long_section():
    text = "\n".join("段落" * 200 for _ in range(10))  # 每段400字，共4000字
    parts = parent_parts(text, max_chars=2000)
    assert len(parts) >= 2
    assert all(len(p) <= 2000 for p in parts)

def test_parent_parts_empty():
    assert parent_parts("") == [""]

def test_parent_parts_hard_split_giant_paragraph():
    text = "字" * 5000
    parts = parent_parts(text, max_chars=2000)
    assert all(len(p) <= 2000 for p in parts)
    assert sum(len(p) for p in parts) == 5000
```

注意：`test_child_chunks_size_and_sentences` 中断言 `<=330` 是因为单句追加允许略超 target（句子不切断）；实现须保证不切句。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_chunking.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 chunking.py**

```python
# src/toolbook/chunking.py
import re

_SENT_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")

def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]

def child_chunks(text: str, target: int = 300) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for sent in _sentences(text.replace("\n", "")):
        if len(sent) > target * 2:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(sent), target):
                chunks.append(sent[i:i + target])
            continue
        if cur and len(cur) + len(sent) > target:
            chunks.append(cur)
            cur = ""
        cur += sent
    if cur:
        chunks.append(cur)
    return chunks

def parent_parts(text: str, max_chars: int = 2000) -> list[str]:
    parts: list[str] = []
    cur = ""
    for para in text.split("\n"):
        if len(para) > max_chars:
            if cur:
                parts.append(cur)
                cur = ""
            for sent in _sentences(para):
                if cur and len(cur) + len(sent) > max_chars:
                    parts.append(cur)
                    cur = ""
                cur += sent
                while len(cur) > max_chars:
                    parts.append(cur[:max_chars])
                    cur = cur[max_chars:]
        elif cur and len(cur) + len(para) + 1 > max_chars:
            parts.append(cur)
            cur = para
        else:
            cur = cur + "\n" + para if cur else para
    if cur:
        parts.append(cur)
    return parts or [""]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_chunking.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/chunking.py tests/test_chunking.py
git commit -m "feat: parent-child chunking (300-char children, 2000-char parent parts)"
```

---

### Task 4: SQLite 存储 store.py（TDD）

**Files:**
- Create: `src/toolbook/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `DEFAULT_DB`（config）
- Produces: `LibraryStore(db_path: Path | str)`，方法：
  - `find_by_hash(file_hash: str) -> sqlite3.Row | None`
  - `add_document(title, fmt, file_hash, source_path) -> int`
  - `insert_section(doc_id, parent_id, number, title, level, source, locator, part, text) -> int`
  - `insert_chunks(section_id, texts: list[str]) -> int`（返回条数）
  - `get_section(doc_id, number) -> list[sqlite3.Row]`（按 part 排序，含所有 part）
  - `list_documents() -> list[sqlite3.Row]`
  - `get_tree(doc_id) -> list[sqlite3.Row]`（按 section_id）
  - `delete_document(doc_id) -> None`（级联）
  - `transaction()` 上下文管理器（with 内原子提交，异常回滚）
  - `close()`

三表 schema 按 D13：documents / sections（含 part、source、locator、parent_id）/ chunks。`PRAGMA foreign_keys=ON`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_store.py
import pytest
from toolbook.store import LibraryStore

@pytest.fixture
def store(tmp_path):
    s = LibraryStore(tmp_path / "test.db")
    yield s
    s.close()

def test_hash_dedup_lookup(store):
    assert store.find_by_hash("abc") is None
    with store.transaction():
        doc_id = store.add_document("书名", "docx", "abc", "x.docx")
    assert store.find_by_hash("abc")["doc_id"] == doc_id

def test_section_and_chunks_roundtrip(store):
    with store.transaction():
        doc_id = store.add_document("书名", "pdf", "h1", "x.pdf")
        sid = store.insert_section(doc_id, None, "3.2", "傅里叶性质", 2, "original", "p10", 1, "原文全文")
        n = store.insert_chunks(sid, ["子块1", "子块2"])
    rows = store.get_section(doc_id, "3.2")
    assert len(rows) == 1 and rows[0]["text"] == "原文全文"
    assert n == 2
    tree = store.get_tree(doc_id)
    assert tree[0]["number"] == "3.2"

def test_multi_part_section(store):
    with store.transaction():
        doc_id = store.add_document("书", "pdf", "h2", "x.pdf")
        store.insert_section(doc_id, None, "1", "长章", 1, "original", "p1", 1, "上半")
        store.insert_section(doc_id, None, "1", "长章", 1, "original", "p1", 2, "下半")
    rows = store.get_section(doc_id, "1")
    assert [r["part"] for r in rows] == [1, 2]

def test_cascade_delete(store):
    with store.transaction():
        doc_id = store.add_document("书", "epub", "h3", "x.epub")
        sid = store.insert_section(doc_id, None, "1", "章", 1, "system", "", 1, "文")
        store.insert_chunks(sid, ["块"])
    store.delete_document(doc_id)
    assert store.list_documents() == []
    assert store.get_tree(doc_id) == []

def test_transaction_rollback(store):
    try:
        with store.transaction():
            store.add_document("书", "pdf", "h4", "x.pdf")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert store.find_by_hash("h4") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 store.py**

```python
# src/toolbook/store.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  format TEXT NOT NULL,
  file_hash TEXT NOT NULL UNIQUE,
  source_path TEXT,
  imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sections(
  section_id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  number TEXT NOT NULL,
  title TEXT NOT NULL,
  level INTEGER NOT NULL,
  parent_id INTEGER REFERENCES sections(section_id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  locator TEXT,
  part INTEGER NOT NULL DEFAULT 1,
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks(
  chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
  section_id INTEGER NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sections_doc ON sections(doc_id, number);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_id);
"""

class LibraryStore:
    def __init__(self, db_path: Path | str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    @contextmanager
    def transaction(self):
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def find_by_hash(self, file_hash: str):
        return self.conn.execute(
            "SELECT * FROM documents WHERE file_hash=?", (file_hash,)).fetchone()

    def add_document(self, title, fmt, file_hash, source_path) -> int:
        cur = self.conn.execute(
            "INSERT INTO documents(title, format, file_hash, source_path) VALUES(?,?,?,?)",
            (title, fmt, file_hash, str(source_path)))
        return cur.lastrowid

    def insert_section(self, doc_id, parent_id, number, title, level,
                       source, locator, part, text) -> int:
        cur = self.conn.execute(
            "INSERT INTO sections(doc_id, parent_id, number, title, level, source, locator, part, text)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (doc_id, parent_id, number, title, level, source, locator, part, text))
        return cur.lastrowid

    def insert_chunks(self, section_id, texts) -> int:
        self.conn.executemany(
            "INSERT INTO chunks(section_id, seq, text) VALUES(?,?,?)",
            [(section_id, i, t) for i, t in enumerate(texts, 1)])
        return len(texts)

    def get_section(self, doc_id, number):
        return self.conn.execute(
            "SELECT * FROM sections WHERE doc_id=? AND number=? ORDER BY part",
            (doc_id, number)).fetchall()

    def list_documents(self):
        return self.conn.execute("SELECT * FROM documents ORDER BY doc_id").fetchall()

    def get_tree(self, doc_id):
        return self.conn.execute(
            "SELECT * FROM sections WHERE doc_id=? ORDER BY section_id",
            (doc_id,)).fetchall()

    def delete_document(self, doc_id):
        with self.transaction():
            self.conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))

    def close(self):
        self.conn.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_store.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/store.py tests/test_store.py
git commit -m "feat: SQLite library store with hash dedup and cascade delete"
```

---

### Task 5: 三个解析器（TDD，程序化生成夹具）

**Files:**
- Create: `src/toolbook/parsers/__init__.py`, `base.py`, `docx_parser.py`, `epub_parser.py`, `pdf_pymupdf.py`, `tests/test_parsers.py`

**Interfaces:**
- Consumes: `Block`, `ParsedDocument`
- Produces: `Parser` 协议 `parse(path: Path) -> ParsedDocument`；`get_parser(path: Path) -> Parser`（按后缀：.docx→DocxParser，.epub→EpubParser，.pdf→PyMuPDFParser；其他抛 ValueError）。三个解析器类同名暴露。

要点：
- DOCX：样式名 `Heading N` / `标题 N` → heading；locator `p段落号`；标题取 core_properties.title 或文件名。
- EPUB：按 spine 顺序读 HTML，h1–h4 → heading，p/li/无嵌套 div → paragraph；locator `spine序号:文件名`；标题取 DC.title。
- PDF（PyMuPDF+规则）：有书签 → 书签标题匹配行作 heading（level 来自书签）；无书签 → 字号启发（≥正文1.5倍→1级，≥1.15倍→2级，行长≤80）；`N.N.N` 编号行 → 点数+1 级。正文字号=按字符数加权的众数字号。locator `p页码`。

- [ ] **Step 1: 写失败测试（夹具现场生成，不依赖真实书籍）**

```python
# tests/test_parsers.py
import pytest
from pathlib import Path
from toolbook.parsers import get_parser
from toolbook.parsers.docx_parser import DocxParser
from toolbook.parsers.epub_parser import EpubParser
from toolbook.parsers.pdf_pymupdf import PyMuPDFParser

@pytest.fixture
def docx_file(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("第1章 绪论", level=1)
    d.add_paragraph("这是绪论正文。")
    d.add_heading("1.1 信号", level=2)
    d.add_paragraph("这是信号小节正文。")
    p = tmp_path / "book.docx"
    d.save(str(p))
    return p

@pytest.fixture
def epub_file(tmp_path):
    from ebooklib import epub
    b = epub.EpubBook()
    b.set_identifier("id1"); b.set_title("Sample Book"); b.set_language("en")
    c1 = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    c1.content = "<h1>Chapter 1 Introduction</h1><p>Intro body text.</p><h2>1.1 Signals</h2><p>Signals body.</p>"
    b.add_item(c1)
    b.spine = ["nav", c1]
    b.add_item(epub.EpubNav())
    b.add_item(epub.EpubNcx())
    p = tmp_path / "book.epub"
    epub.write_epub(str(p), b)
    return p

@pytest.fixture
def pdf_file(tmp_path):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "第1章 绪论", fontname="china-s", fontsize=22)
    page.insert_text((72, 120), "这是绪论正文。", fontname="china-s", fontsize=11)
    page.insert_text((72, 150), "1.1 信号", fontname="china-s", fontsize=16)
    page.insert_text((72, 180), "这是信号小节正文。", fontname="china-s", fontsize=11)
    doc.set_toc([[1, "第1章 绪论", 1], [2, "1.1 信号", 1]])
    p = tmp_path / "book.pdf"
    doc.save(str(p))
    doc.close()
    return p

def test_docx_headings_and_locators(docx_file):
    parsed = DocxParser().parse(docx_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("第1章 绪论", 1), ("1.1 信号", 2)]
    assert all(b.locator.startswith("p") for b in parsed.blocks)
    assert any("绪论正文" in b.text for b in parsed.blocks)

def test_epub_headings_and_locators(epub_file):
    parsed = EpubParser().parse(epub_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("Chapter 1 Introduction", 1), ("1.1 Signals", 2)]
    assert parsed.title == "Sample Book"
    assert all(b.locator.startswith("spine") for b in parsed.blocks)

def test_pdf_bookmark_headings(pdf_file):
    parsed = PyMuPDFParser().parse(pdf_file)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert [(b.text, b.level) for b in heads] == [("第1章 绪论", 1), ("1.1 信号", 2)]
    assert all(b.locator == "p1" for b in parsed.blocks)

def test_pdf_font_fallback_without_toc(tmp_path):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One", fontsize=24)
    page.insert_text((72, 120), "Body text here.", fontsize=11)
    p = tmp_path / "notoc.pdf"
    doc.save(str(p)); doc.close()
    parsed = PyMuPDFParser().parse(p)
    heads = [b for b in parsed.blocks if b.kind == "heading"]
    assert heads and heads[0].text == "Chapter One"

def test_get_parser_registry(docx_file, epub_file, pdf_file, tmp_path):
    assert isinstance(get_parser(docx_file), DocxParser)
    assert isinstance(get_parser(epub_file), EpubParser)
    assert isinstance(get_parser(pdf_file), PyMuPDFParser)
    with pytest.raises(ValueError):
        get_parser(tmp_path / "x.mobi")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 base.py 与注册表**

```python
# src/toolbook/parsers/base.py
from pathlib import Path
from typing import Protocol
from ..models import ParsedDocument

class Parser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...
```

```python
# src/toolbook/parsers/__init__.py
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
```

- [ ] **Step 4: 实现 docx_parser.py**

```python
# src/toolbook/parsers/docx_parser.py
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
```

- [ ] **Step 5: 实现 epub_parser.py**

```python
# src/toolbook/parsers/epub_parser.py
from pathlib import Path
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
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
            soup = BeautifulSoup(it.get_content(), "lxml")
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
```

- [ ] **Step 6: 实现 pdf_pymupdf.py**

```python
# src/toolbook/parsers/pdf_pymupdf.py
import re
from collections import Counter
from pathlib import Path
import fitz
from ..models import Block, ParsedDocument

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()

class PyMuPDFParser:
    def parse(self, path: Path) -> ParsedDocument:
        doc = fitz.open(str(path))
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
```

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: 6 passed。若 PDF 字号启发测试因字体渲染差异失败，调整倍数阈值而非放宽断言。

- [ ] **Step 8: Commit**

```bash
git add src/toolbook/parsers/ tests/test_parsers.py
git commit -m "feat: docx/epub/pymupdf parsers with swappable interface"
```

---

### Task 6: 导入编排 importer.py + CLI（TDD）

**Files:**
- Create: `src/toolbook/importer.py`, `src/toolbook/cli.py`, `tests/test_importer.py`

**Interfaces:**
- Consumes: `get_parser`、`build_tree`、`iter_nodes`、`parent_parts`、`child_chunks`、`LibraryStore`、`DEFAULT_DB`
- Produces: `import_file(path: Path | str, db_path: Path | str = DEFAULT_DB, parser: Parser | None = None) -> ImportResult`；CLI：`python -m toolbook.cli import <files...> [--db PATH]` / `list` / `tree <doc_id>` / `show <doc_id> <number>`。

导入流程：SHA-256 → 查重（命中即 skipped）→ 解析 → 建树 → 单事务内 DFS 写 sections（每节点按 parent_parts 写 1..N 个 part 行，part 文本切 child_chunks 写 chunks；子节点 parent_id 指向该节点第一个 part 行）→ 返回统计。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_importer.py
import pytest
from toolbook.importer import import_file
from toolbook.store import LibraryStore

@pytest.fixture
def docx_file(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("第1章 绪论", level=1)
    d.add_paragraph("这是绪论正文。" * 30)
    d.add_heading("1.1 信号", level=2)
    d.add_paragraph("这是信号小节正文。")
    p = tmp_path / "book.docx"
    d.save(str(p))
    return p

def test_import_end_to_end(tmp_path, docx_file):
    db = tmp_path / "lib.db"
    r = import_file(docx_file, db)
    assert not r.skipped and r.sections >= 2 and r.chunks >= 2
    store = LibraryStore(db)
    rows = store.get_section(r.doc_id, "1.1")
    assert rows and rows[0]["source"] == "original"
    assert "信号小节正文" in rows[0]["text"]
    assert rows[0]["locator"].startswith("p")
    store.close()

def test_import_idempotent(tmp_path, docx_file):
    db = tmp_path / "lib.db"
    r1 = import_file(docx_file, db)
    r2 = import_file(docx_file, db)
    assert r2.skipped and r2.doc_id == r1.doc_id
    store = LibraryStore(db)
    assert len(store.list_documents()) == 1
    store.close()

def test_long_section_multi_part(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("第1章 长章", level=1)
    for _ in range(20):
        d.add_paragraph("很长的一段。" * 100)
    p = tmp_path / "long.docx"
    d.save(str(p))
    r = import_file(p, tmp_path / "lib.db")
    store = LibraryStore(tmp_path / "lib.db")
    rows = store.get_section(r.doc_id, "1")
    assert len(rows) >= 2
    assert all(len(x["text"]) <= 2000 for x in rows)
    store.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_importer.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 importer.py**

```python
# src/toolbook/importer.py
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
```

- [ ] **Step 4: 实现 cli.py**

```python
# src/toolbook/cli.py
import argparse
import sys
from .config import DEFAULT_DB
from .importer import import_file
from .store import LibraryStore

def main(argv=None):
    ap = argparse.ArgumentParser(prog="toolbook", description="ToolBook 资源库管理")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import", help="导入 docx/epub/pdf")
    p_imp.add_argument("files", nargs="+")
    sub.add_parser("list", help="列出已导入文档")
    p_tree = sub.add_parser("tree", help="显示章节树")
    p_tree.add_argument("doc_id", type=int)
    p_show = sub.add_parser("show", help="按章节号直查原文")
    p_show.add_argument("doc_id", type=int)
    p_show.add_argument("number")
    args = ap.parse_args(argv)

    if args.cmd == "import":
        for f in args.files:
            r = import_file(f, args.db)
            if r.skipped:
                print(f"[跳过] 《{r.title}》已导入（doc_id={r.doc_id}，哈希相同）")
            else:
                print(f"[导入] 《{r.title}》 doc_id={r.doc_id} 章节行={r.sections} 子块={r.chunks}")
        return
    store = LibraryStore(args.db)
    if args.cmd == "list":
        for d in store.list_documents():
            print(f"{d['doc_id']}\t{d['title']}\t{d['format']}\t{d['imported_at']}")
    elif args.cmd == "tree":
        for s in store.get_tree(args.doc_id):
            badge = "" if s["source"] == "original" else " [系统编号]"
            part = f" (part {s['part']})" if s["part"] > 1 else ""
            print(f"{'  ' * (s['level'] - 1)}{s['number']} {s['title']}{badge}{part}  <{s['locator']}>")
    elif args.cmd == "show":
        rows = store.get_section(args.doc_id, args.number)
        if not rows:
            print(f"未找到章节 {args.number}")
            sys.exit(1)
        for r in rows:
            badge = "" if r["source"] == "original" else " [系统编号]"
            print(f"== {r['number']} {r['title']}{badge}  定位:{r['locator']} part:{r['part']} ==")
            print(r["text"])
    store.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑全部测试确认通过**

Run: `uv run pytest -v`
Expected: 全部 passed（约 26 个）

- [ ] **Step 6: Commit**

```bash
git add src/toolbook/importer.py src/toolbook/cli.py tests/test_importer.py
git commit -m "feat: idempotent import pipeline and CLI (import/list/tree/show)"
```

---

### Task 7: M1 演示（三格式示例书 + demo 脚本）

**Files:**
- Create: `scripts/make_demo_books.py`, `scripts/demo_m1.py`

**Interfaces:**
- Consumes: Task 6 的 `import_file` / `LibraryStore` / CLI
- Produces: `data/demo_books/` 下三本示例书；`uv run python scripts/demo_m1.py` 一键演示。

- [ ] **Step 1: 写 make_demo_books.py**

生成三本内容对应的小书（中文 DOCX《示例教材：信号与系统基础》、英文 EPUB "Sample Textbook: Signals and Systems"、中文 PDF《示例讲义：傅里叶分析入门》带书签）。每本 2 章、每章 2 节，正文含可检索的知识点句子（傅里叶变换、卷积、采样定理等），每节 3–5 段。DOCX 用 add_heading；EPUB 用 h1/h2；PDF 用 fitz insert_text（fontname="china-s"，标题 22/16pt、正文 11pt）+ set_toc。

- [ ] **Step 2: 写 demo_m1.py**

```python
# scripts/demo_m1.py
"""M1 演示：三格式导入 → 章节树 → 章节号直查 → 幂等复导入。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from make_demo_books import make_all
from toolbook.config import DATA_DIR
from toolbook.importer import import_file
from toolbook.store import LibraryStore

def main():
    db = DATA_DIR / "demo_m1.db"
    if db.exists():
        db.unlink()
    books = make_all(DATA_DIR / "demo_books")
    for b in books:
        r = import_file(b, db)
        print(f"[导入] 《{r.title}》 doc_id={r.doc_id} 章节行={r.sections} 子块={r.chunks}")
    store = LibraryStore(db)
    for d in store.list_documents():
        print(f"\n=== 《{d['title']}》 章节树 ===")
        for s in store.get_tree(d["doc_id"]):
            badge = "" if s["source"] == "original" else " [系统编号]"
            print(f"{'  ' * (s['level'] - 1)}{s['number']} {s['title']}{badge}  <{s['locator']}>")
    doc_id = store.list_documents()[0]["doc_id"]
    rows = store.get_section(doc_id, "1.1")
    print(f"\n=== 章节号直查 {doc_id} / 1.1 ===")
    print(rows[0]["text"][:200] if rows else "未命中")
    store.close()
    print("\n=== 幂等性：重复导入同一文件 ===")
    r = import_file(books[0], db)
    print(f"skipped={r.skipped}（应为 True）")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 运行演示并人工验收**

Run: `uv run python scripts/demo_m1.py`
Expected: 三本导入成功；章节号与原书目录一致（1/1.1/1.2/2/2.1/2.2）；直查 1.1 返回原文；重复导入 skipped=True。
对照 M1 验收标准逐条确认。

- [ ] **Step 4: Commit**

```bash
git add scripts/
git commit -m "feat: M1 demo - three-format sample books and import walkthrough"
```

---

### Task 8: MinerU 限时尝试（止损：当天不通即降级）

**Files:**
- Create（仅当安装成功）: `src/toolbook/parsers/pdf_mineru.py`, `tests/test_mineru_adapter.py`
- Modify（仅当成功）: `src/toolbook/parsers/__init__.py`（环境变量 `TOOLBOOK_PDF_PARSER=mineru` 时注册表返回 MinerUParser）

- [ ] **Step 1: 后台尝试安装（与 Task 2–7 并行）**

Run: `uv add "mineru[core]"`（后台执行；失败/超时即记录降级，不重试超过 2 次；可试清华镜像）。
注意：Python 3.13 兼容性、数 GB 模型下载都是风险点。安装失败 → 在计划书风险节记录"已触发止损，M1 用 PyMuPDF"，任务结束。

- [ ] **Step 2: 若安装成功：写适配器**

MinerUParser.parse：调 `mineru.cli.common.do_parse`（或 mineru 2.x 对应 API，以实际安装版本文档为准）输出 content_list.json → 遍历块：`type=="text"` 且 `text_level>=1` → heading（level=text_level），否则 paragraph；locator=`p{page_idx+1}`。解析在独立子进程跑（显存错峰，D10 约束），结束即释放。

- [ ] **Step 3: 用 Task 7 的 PDF 示例书验证**

Run: `TOOLBOOK_PDF_PARSER=mineru uv run python scripts/demo_m1.py`
Expected: 章节树与 PyMuPDF 版一致或更好。失败则回退默认解析器并记录。

- [ ] **Step 4: Commit（若有改动）**

```bash
git add src/toolbook/parsers/ pyproject.toml uv.lock tests/
git commit -m "feat: optional MinerU PDF parser adapter (env-switchable)"
```

---

### Task 9: 收尾（记忆更新 + push 尝试）

- [ ] **Step 1: 更新项目记忆**

`project-requirements-and-stack.md`：评审形式=提交作品包（2026-11-18 确认）；M1 状态；MinerU 尝试结果；git 仅本地 commit、remote 未建。

- [ ] **Step 2: 尝试配置 remote 并 push**

前提：用户已在 github.com/hish-hish 建好空仓库（建议名 toolbook-paper-agent）。
Run: `git remote add origin https://github.com/hish-hish/toolbook-paper-agent.git && git push -u origin master`
网络仍不通 → 保留本地 commit，告知用户明早 push。

- [ ] **Step 3: 全量回归**

Run: `uv run pytest -v`
Expected: 全部 passed。

## Self-Review 结论

- 规格覆盖：D3（可替换解析器+止损）→Task 5/8；D4→Task 5；D5 规则部分→Task 2（LLM 兜底显式留 M3，因 LLM 客户端尚未建）；D6→Task 3；D13→Task 4；幂等→Task 4/6；M1 验收→Task 7。
- 类型一致性：Block/SectionNode/ImportResult 签名、store 方法名、parser 注册表在各任务间已核对一致。
- 已知留白（有意为之）：LLM 兜底章节识别、Chroma 向量化（M2）、核验（M3）不在 M1 范围。