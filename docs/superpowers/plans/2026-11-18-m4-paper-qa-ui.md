# M4 论文问答 + Streamlit UI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上传论文 PDF → 解析展示目录 → 带论文上下文向本地资源库提问 → 核验答案附书目出处；Streamlit 界面呈现资源库管理、问答与核验徽章。

**Architecture:** 论文只作"提问上下文"，不入资源库（答案依据仍全部来自库内父块，核验链不动）。新增 paper.py 解析论文（双栏自然阅读序+书签目录+标题/摘要），llm.contextualize_query 把论文背景注入查询改写，agent.ask 增加 paper 参数走同一张 LangGraph 图。Streamlit app.py 复用全部内核函数，内核与 UI 分离（D12）。

**Tech Stack:** pymupdf（已有）、langgraph 1.2.22（已有）、streamlit（新增）、uv、pytest。

**Spec:** `项目计划书.md` §2 模块B、§4 M4 行、§7 第4点（核验状态可视化）；`docs/决策点详解/D01-编排框架-LangGraph.md` §4 模块B、`D12` Streamlit。

**示例论文:** `D:\仲谋\研究生\读论文\CORE_TWC_09101709.pdf`（13 页、30 书签、英文双栏 IEEE 期刊论文，主题双极化感知与 ISAC 教材高度相关）。已勘察：现有 PyMuPDFParser 按 y 排序会把双栏文本交错，论文解析必须改用 PDF 自然存储顺序（实测该论文按栏存储，阅读序正确）。

## Global Constraints

- zh-code-style：每个新建/修改的 .py 文件开头中文功能说明 + 每个函数/功能块中文注释；回复中展示代码给出文件路径与行号；**所有新增 commit message 用中文**（可保留 feat:/fix:/docs: 前缀），不改写历史提交。
- API 密钥只从环境变量 SILICONFLOW_API_KEY 或项目根 .env 读取；.env 已 gitignore；密钥绝不入代码、不入聊天、不提交。
- 宁缺勿错：两级核验链路（机械子串 + LLM 裁判双锚定）绝不削弱；**论文文本不作为答案依据**，只帮助理解问题与改写查询。
- 运行命令统一 `uv run --no-sync`；中文输出加 `PYTHONIOENCODING=utf-8`；Windows Git Bash。
- `data/` 已 gitignore：论文 PDF 复制到 `data/papers/` 使用，**不提交论文文件**。
- 单元测试全部离线（monkeypatch llm.chat / hybrid_search 等）；真实 API 只用于 demo 与验收。
- 每个任务结束提交一次（中文 message）；push 失败（网络重置）则重试一次后延后，告知用户。

---

### Task 1: 论文解析 paper.py + PaperInfo 模型

**Files:**
- Modify: `src/toolbook/models.py`（文件末尾追加 PaperInfo）
- Create: `src/toolbook/paper.py`
- Test: `tests/test_paper.py`

**Interfaces:**
- Consumes: 无（独立模块，只用 pymupdf）
- Produces: `PaperInfo(title: str, outline: list[dict], abstract: str, n_pages: int)`，outline 元素 `{"level": int, "title": str, "page": int}`；方法 `PaperInfo.context() -> str`（标题+摘要，截断 1500 字）；`parse_paper(path) -> PaperInfo`。T2/T3/T4/T5 都消费这两个名字。

- [ ] **Step 1: 写失败测试**

`tests/test_paper.py`：

```python
"""论文解析离线单测：用 pymupdf 现造双栏+书签夹具 PDF，验证标题/目录/摘要/阅读序。"""
import pymupdf
import pytest

from toolbook.paper import parse_paper


@pytest.fixture
def paper_path(tmp_path):
    # 现造一篇最小论文：大字号标题 + 摘要 + 双栏正文（左栏先写入，模拟 LaTeX 存储序）+ 书签
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "Test Paper on Signal Sensing", fontsize=20)
    page.insert_text((72, 120), "Abstract—This paper studies multipath sensing.", fontsize=9)
    page.insert_text((72, 140), "Index Terms—sensing, multipath.", fontsize=9)
    page.insert_text((72, 200), "Left column first line.", fontsize=10)
    page.insert_text((72, 220), "Left column second line.", fontsize=10)
    page.insert_text((320, 200), "Right column first line.", fontsize=10)
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((72, 80), "II. Method", fontsize=11)
    page2.insert_text((72, 110), "Method body text.", fontsize=10)
    doc.set_toc([[1, "I. Introduction", 1], [1, "II. Method", 2]])
    path = tmp_path / "paper.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_parse_paper_title_and_pages(paper_path):
    # 标题取首页最大字号行（而非文件名），页数正确
    info = parse_paper(paper_path)
    assert info.title == "Test Paper on Signal Sensing"
    assert info.n_pages == 2


def test_parse_paper_outline(paper_path):
    # 目录来自书签：层级/标题/页码齐全
    info = parse_paper(paper_path)
    assert info.outline == [
        {"level": 1, "title": "I. Introduction", "page": 1},
        {"level": 1, "title": "II. Method", "page": 2},
    ]


def test_parse_paper_abstract(paper_path):
    # 摘要截取 Abstract 与 Index Terms 之间
    info = parse_paper(paper_path)
    assert "multipath sensing" in info.abstract
    assert "Index Terms" not in info.abstract


def test_paper_context(paper_path):
    # 上下文串含标题与摘要，供查询改写/生成使用
    info = parse_paper(paper_path)
    ctx = info.context()
    assert "Test Paper on Signal Sensing" in ctx and "multipath sensing" in ctx


def test_column_reading_order(paper_path):
    # 双栏阅读序：左栏整段在右栏之前（自然存储序，不按 y 交错）
    from toolbook.paper import _page_text
    doc = pymupdf.open(str(paper_path))
    text = _page_text(doc[0])
    doc.close()
    assert text.index("Left column second line") < text.index("Right column first line")


def test_no_toc_paper(tmp_path):
    # 无书签论文：目录为空列表，不报错（UI 显示"无目录"）
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Plain Paper", fontsize=16)
    path = tmp_path / "plain.pdf"
    doc.save(str(path))
    doc.close()
    info = parse_paper(path)
    assert info.outline == [] and info.title == "Plain Paper"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_paper.py -q`
Expected: FAIL（ModuleNotFoundError: toolbook.paper）

- [ ] **Step 3: 实现**

`src/toolbook/models.py` 末尾追加：

```python
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
```

`src/toolbook/paper.py`：

```python
"""论文解析（模块B）：双栏自然阅读序 + 书签目录 + 标题/摘要提取。

论文只作提问上下文，不导入资源库；答案依据仍全部来自库内原文。
"""
import re
from pathlib import Path

import pymupdf

from .models import PaperInfo


def _page_text(page) -> str:
    """按 PDF 自然存储顺序取整页文本（LaTeX 双栏论文按栏存储），过滤纯页码块。"""
    parts = []
    for b in page.get_text("blocks"):
        text = b[4].strip()
        if not text or re.fullmatch(r"\d{1,4}", text):
            continue
        parts.append(text)
    return "\n".join(parts)


def _extract_title(doc) -> str:
    """标题：优先元数据；否则首页最大字号行拼接（截到 Abstract 前）；兜底文件名。"""
    meta = (doc.metadata.get("title") or "").strip()
    if meta:
        return meta
    spans = []
    for block in doc[0].get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for s in line["spans"]:
                if s["text"].strip():
                    spans.append((s["size"], line["bbox"][1], s["text"]))
    if not spans:
        return Path(doc.name).stem
    max_size = max(s[0] for s in spans)
    # 最大字号（≥95%）的行按 y 坐标分组拼接，即标题区
    lines: dict[int, list[str]] = {}
    for size, y, text in spans:
        if size >= max_size * 0.95:
            lines.setdefault(round(y), []).append(text)
    title = " ".join("".join(v) for _, v in sorted(lines.items()))
    title = re.split(r"\bAbstract\b", title)[0].strip()
    return title or Path(doc.name).stem


def _extract_abstract(doc) -> str:
    """摘要：首页 Abstract 到 Index Terms/Keywords/首个章节标题之间的文本。"""
    text = _page_text(doc[0])
    m = re.search(
        r"Abstract\s*[—–\-:]?\s*(.*?)(?:Index Terms|Keywords|I\.\s|1\.\s|Introduction)",
        text, re.S | re.I)
    return m.group(1).strip() if m else ""


def parse_paper(path) -> PaperInfo:
    """解析论文 PDF：标题 + 书签目录 + 摘要 + 页数；无书签时目录为空。"""
    doc = pymupdf.open(str(path))
    try:
        outline = [{"level": lv, "title": t, "page": pg}
                   for lv, t, pg in doc.get_toc()]
        return PaperInfo(_extract_title(doc), outline,
                         _extract_abstract(doc), len(doc))
    finally:
        doc.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_paper.py -q`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/toolbook/models.py src/toolbook/paper.py tests/test_paper.py
git commit -m "feat: 论文解析（双栏阅读序+书签目录+标题摘要提取，模块B上下文）"
```

---

### Task 2: 论文上下文注入查询改写与答案生成

**Files:**
- Modify: `src/toolbook/llm.py`（末尾追加 contextualize_query）
- Modify: `src/toolbook/answering.py:11-25`（generate_draft 增加 paper_context 参数）
- Test: `tests/test_llm.py`（追加 2 个测试）、`tests/test_answering.py`（追加 1 个测试）

**Interfaces:**
- Consumes: T1 的 `PaperInfo.context() -> str`（本任务只用 str，不 import PaperInfo）
- Produces: `llm.contextualize_query(question: str, paper_context: str) -> str`（失败回退原问题）；`generate_draft(question: str, hits: list, paper_context: str = "") -> list[dict]`（第三参可选，旧调用不受影响）。

- [ ] **Step 1: 写失败测试**

`tests/test_llm.py` 末尾追加：

```python
def test_contextualize_query_success(monkeypatch):
    # 论文上下文改写：提示词含论文背景与问题，输出关键词串
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return " 双极化 polarization 协方差 covariance "

    monkeypatch.setattr(llm, "chat", fake_chat)
    out = llm.contextualize_query("这个接收机为什么用双极化？", "论文《CORE》\n摘要：dual-polarized")
    assert out == "双极化 polarization 协方差 covariance"
    assert "CORE" in captured["prompt"] and "双极化" in captured["prompt"]


def test_contextualize_query_fallback(monkeypatch):
    # 调用失败回退原问题，不阻断检索
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(llm, "chat", boom)
    assert llm.contextualize_query("原问题", "背景") == "原问题"
```

`tests/test_answering.py` 末尾追加：

```python
def test_generate_draft_with_paper_context(monkeypatch):
    # 论文背景进入提示词但明确"不作为答案依据"；资料块仍是唯一答案来源
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return '{"insufficient": false, "sentences": [{"text": "采样频率必须大于最高频率的两倍。", "type": "excerpt", "ref": 0}]}'

    monkeypatch.setattr(aw.llm, "chat", fake_chat)
    draft = aw.generate_draft("采样定理？", [_hit()], paper_context="论文《CORE》\n摘要：sensing")
    assert draft[0]["ref"] == 0
    assert "提问背景" in captured["prompt"] and "CORE" in captured["prompt"]
    assert "不作为答案依据" in captured["prompt"]
    assert "[0]" in captured["prompt"]  # 编号资料块仍在
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_llm.py tests/test_answering.py -q`
Expected: 新增 3 个 FAIL（AttributeError / TypeError），其余 PASS

- [ ] **Step 3: 实现**

`src/toolbook/llm.py` 末尾追加：

```python
def contextualize_query(question: str, paper_context: str) -> str:
    """模块B 查询上下文化：结合论文背景把问题展开为资源库检索关键词；失败回退原问题。"""
    prompt = (f"用户正在阅读的论文背景：\n{paper_context[:1500]}\n\n用户问题：{question}\n"
              "请把问题改写为适合在教材资源库中检索的关键词（中英混合、空格分隔），"
              "突出论文涉及的基础知识点术语，直接输出关键词串，不要解释。")
    try:
        out = chat(prompt).strip()
        return out or question
    except Exception:
        return question
```

`src/toolbook/answering.py` 的 generate_draft 改为（签名加第三参，prompt 前加背景段）：

```python
def generate_draft(question: str, hits: list, paper_context: str = "") -> list[dict]:
    """生成答案草稿 [{"text","type","ref"}]：excerpt 须一字不差摘抄，summary 须有依据。

    paper_context 是用户正在读的论文背景，只帮助理解问题，不作为答案依据。
    资料不足、调用失败或格式异常都返回空列表（由编排层触发重检索/拒答）。
    """
    if not hits:
        return []
    # 编号资料块：每块带完整出处，供 LLM 标引用
    sources = [f"[{i}] 《{h.doc_title}》{h.number} {h.title}（{h.locator}）\n{h.text[:1200]}"
               for i, h in enumerate(hits)]
    # 论文背景段：明确仅供理解问题，答案依据只能是编号资料
    bg = (f"提问背景（用户正在阅读的论文，仅供理解问题，不作为答案依据）：\n{paper_context[:800]}\n\n"
          if paper_context else "")
    prompt = (bg + f"问题：{question}\n\n资料：\n" + "\n\n".join(sources) +
              '\n\n请输出JSON：{"insufficient": false, "sentences": [{"text": "句子", "type": "excerpt"或"summary", "ref": 资料编号}]}\n'
              "要求：type=excerpt 的 text 必须一字不差摘抄资料原文（可截取连续片段）；"
              "type=summary 的每句必须有资料依据并标 ref；"
              '资料不足以回答问题时输出 {"insufficient": true, "sentences": []}。')
    try:
        raw = llm.chat(prompt, _GEN_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        if d.get("insufficient"):
            return []
        return [s for s in d.get("sentences", []) if isinstance(s, dict) and s.get("text")]
    except Exception:
        return []
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_llm.py tests/test_answering.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/toolbook/llm.py src/toolbook/answering.py tests/test_llm.py tests/test_answering.py
git commit -m "feat: 论文上下文注入查询改写与答案生成（论文不作答案依据）"
```

---

### Task 3: agent.ask 接入论文参数

**Files:**
- Modify: `src/toolbook/agent.py`（AgentState 加 paper_context；generate_node 传参；ask 加 paper 参数）
- Test: `tests/test_agent.py`（修 fixture 签名 + 追加 2 个测试）

**Interfaces:**
- Consumes: T1 `PaperInfo`（duck-typing：只用 `.context()`）、T2 `llm.contextualize_query`、`generate_draft(question, hits, paper_context="")`
- Produces: `ask(question: str, db_path=config.DEFAULT_DB, use_rerank: bool = True, paper=None) -> AnswerResult`。paper 为 PaperInfo 或 None；None 时行为与 M3 完全一致。

- [ ] **Step 1: 写失败测试**

`tests/test_agent.py` 的 patch_nodes fixture 中 generate_draft 假函数改签名（兼容第三参）：

```python
    monkeypatch.setattr(ag, "generate_draft", lambda q, hits, ctx="": [{"text": "原文内容", "type": "excerpt", "ref": 0}])
```

末尾追加：

```python
def test_ask_with_paper_contextualizes_query(patch_nodes):
    # 带论文提问：初始查询用上下文化关键词，生成节点收到论文背景
    from toolbook.models import PaperInfo
    seen = {}

    def fake_search(q, **k):
        seen.setdefault("queries", []).append(q)
        return [_hit()]

    def fake_gen(q, hits, ctx=""):
        seen["ctx"] = ctx
        return [{"text": "原文内容", "type": "excerpt", "ref": 0}]

    patch_nodes.setattr(ag, "hybrid_search", fake_search)
    patch_nodes.setattr(ag, "generate_draft", fake_gen)
    patch_nodes.setattr(ag.llm, "contextualize_query", lambda q, ctx: "双极化 polarization 关键词")
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [VerifiedSentence("原文内容", "excerpt", 0, "mechanical", "原文内容")])
    paper = PaperInfo("CORE", [], "dual-polarized sensing", 13)
    r = ag.ask("这个接收机为什么用双极化？", paper=paper)
    assert not r.refused
    assert seen["queries"][0] == "双极化 polarization 关键词"
    assert "CORE" in seen["ctx"]


def test_ask_without_paper_unchanged(patch_nodes):
    # 不带论文：初始查询仍是原问题（M3 行为不变）
    seen = {}
    patch_nodes.setattr(ag, "hybrid_search", lambda q, **k: seen.setdefault("q", q) or [_hit()])
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [VerifiedSentence("原文内容", "excerpt", 0, "mechanical", "原文内容")])
    r = ag.ask("采样定理？")
    assert not r.refused and seen["q"] == "采样定理？"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_agent.py -q`
Expected: 新增 2 个 FAIL（ask 不接受 paper 参数），旧 4 个 PASS

- [ ] **Step 3: 实现**

`src/toolbook/agent.py` 三处修改：

AgentState 加一行字段：

```python
    paper_context: str
```

generate_node 改为：

```python
def generate_node(state: AgentState) -> dict:
    """生成节点：LLM 基于检索父块写逐句带引用的草稿（可带论文提问背景）。"""
    return {"draft": generate_draft(state["question"], state["hits"],
                                    state.get("paper_context", ""))}
```

ask 改为：

```python
def ask(question: str, db_path=config.DEFAULT_DB, use_rerank: bool = True,
        paper=None) -> AnswerResult:
    """问答主入口（模块A/B 共用）：paper 为 PaperInfo 时先做论文上下文查询改写。"""
    query, ctx = question, ""
    if paper is not None:
        ctx = paper.context()
        query = llm.contextualize_query(question, ctx)
    graph = build_graph()
    final = graph.invoke({"question": question, "query": query,
                          "paper_context": ctx,
                          "db_path": db_path, "use_rerank": use_rerank,
                          "retries": 0, "searched": []})
    return final["result"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_agent.py -q`
Expected: 6 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest -q`
Expected: 全部 PASS（M3 的 68 + 新增 11 = 79）

```bash
git add src/toolbook/agent.py tests/test_agent.py
git commit -m "feat: ask 接入论文上下文（模块B 走同一张核验状态图）"
```

---

### Task 4: Streamlit 界面 app.py

**Files:**
- Modify: `pyproject.toml`（uv add streamlit）
- Create: `app.py`（项目根）
- Test: 浏览器人工验证（browser-use MCP），无单元测试（纯 UI 装配，内核已被 T1–T3 覆盖）

**Interfaces:**
- Consumes: `import_file(path, db_path) -> ImportResult`、`build_vector_index(db_path, force=False)`、`LibraryStore.list_documents()/get_tree(doc_id)`、`ask(question, db_path, use_rerank, paper) -> AnswerResult`、`parse_paper(path) -> PaperInfo`、`config.DEFAULT_DB/DATA_DIR`
- Produces: `streamlit run app.py` 可访问的 Web UI（端口 8501）。

- [ ] **Step 1: 加依赖**

Run: `uv add streamlit`
Expected: pyproject.toml 与 uv.lock 更新，安装成功

- [ ] **Step 2: 写 app.py**

```python
"""ToolBook-Paper Agent Streamlit 界面（D12）：资源库管理 + 资源库问答 + 论文问答。

内核与 UI 分离：本文件只做装配与展示，全部逻辑在 toolbook 包内。
启动：uv run streamlit run app.py
"""
import sys
from pathlib import Path

# 允许 streamlit 直接以脚本方式加载（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st

from toolbook import config
from toolbook.agent import ask
from toolbook.importer import import_file
from toolbook.models import AnswerResult
from toolbook.paper import parse_paper
from toolbook.store import LibraryStore
from toolbook.vector_index import build_vector_index

st.set_page_config(page_title="ToolBook-Paper Agent", layout="wide")


def render_answer(r: AnswerResult):
    """渲染一条答案：逐句核验徽章 + 出处目录（拒答时显示原因与已尝试查询）。"""
    if r.refused:
        st.warning(r.message)
        st.caption(f"已尝试查询：{r.searched}（重试 {r.retries} 次）")
        return
    for s in r.sentences:
        badge = "机械✓" if s.badge == "mechanical" else "LLM✓"
        color = "green" if s.badge == "mechanical" else "blue"
        st.markdown(f":{color}[**[{badge}]**] {s.text} `[{s.ref}]`")
    with st.expander(f"出处目录（{len(r.sources)} 条，重试 {r.retries} 次）"):
        for i, src in enumerate(r.sources):
            mark = "" if src.source == "original" else " **[系统编号]**"
            title = src.title.removeprefix(src.number).strip() or src.title
            st.markdown(f"[{i}] 《{src.doc_title}》 {src.number} {title}{mark}（{src.locator}）")


def chat_block(key: str, paper=None):
    """通用问答区：历史消息 + 输入框 +  spinner 跑 ask()；key 区分模块A/B 会话。"""
    hist_key = f"messages_{key}"
    if hist_key not in st.session_state:
        st.session_state[hist_key] = []
    for role, payload in st.session_state[hist_key]:
        with st.chat_message(role):
            if role == "user":
                st.markdown(payload)
            else:
                render_answer(payload)
    prompt = st.chat_input("输入问题…", key=f"input_{key}")
    if not prompt:
        return
    st.session_state[hist_key].append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("检索 → 生成 → 核验中（约 30–60 秒）…"):
            r = ask(prompt, use_rerank=st.session_state.get("use_rerank", True), paper=paper)
        render_answer(r)
    st.session_state[hist_key].append(("assistant", r))


# ---------- 侧边栏：重排开关 + 资源库管理 ----------
st.sidebar.title("ToolBook-Paper Agent")
st.session_state["use_rerank"] = st.sidebar.checkbox("本地重排（更准，CPU 约 +2 秒/轮）", value=True)
st.sidebar.subheader("资源库")
store = LibraryStore(config.DEFAULT_DB)
docs = store.list_documents()
if docs:
    for d in docs:
        st.sidebar.markdown(f"《{d['title']}》（{d['format']}）")
else:
    st.sidebar.info("资源库为空，请先导入书籍")

# 导入新书：上传 → 存 data/books → 导入 → 重建向量索引（会话内按文件名防重复触发）
up = st.sidebar.file_uploader("导入新书（PDF/DOCX/EPUB）", type=["pdf", "docx", "epub"])
if up is not None:
    done = st.session_state.setdefault("imported_files", set())
    if up.name not in done:
        books_dir = config.DATA_DIR / "books"
        books_dir.mkdir(parents=True, exist_ok=True)
        dest = books_dir / up.name
        dest.write_bytes(up.getvalue())
        with st.sidebar.status("导入并建索引中…"):
            res = import_file(dest)
            build_vector_index(config.DEFAULT_DB, force=True)
        done.add(up.name)
        if res.skipped:
            st.sidebar.info(f"《{res.title}》已在库中（哈希去重）")
        else:
            st.sidebar.success(f"《{res.title}》导入成功：{res.sections} 章节行 / {res.chunks} 子块")

# 目录浏览：选书 → 章节树表格
if docs:
    pick = st.sidebar.selectbox("浏览目录", [d["title"] for d in docs])
    doc_id = next(d["doc_id"] for d in docs if d["title"] == pick)
    rows = store.get_tree(doc_id)
    st.sidebar.dataframe(
        [{"编号": r["number"], "标题": r["title"],
          "来源": "原书" if r["source"] == "original" else "系统",
          "定位": r["locator"]} for r in rows],
        height=300, hide_index=True)
store.close()

# ---------- 主区：两个问答页签 ----------
tab_a, tab_b = st.tabs(["资源库问答（模块A）", "论文问答（模块B）"])
with tab_a:
    st.caption("答案只返回核验通过的内容：机械✓=原文摘录子串匹配，LLM✓=逐句裁判+原文双锚定。")
    chat_block("a")
with tab_b:
    st.caption("上传论文 PDF → 展示目录 → 就知识点提问，答案附本地资源库出处（论文本身不作答案依据）。")
    paper_up = st.file_uploader("上传论文 PDF", type=["pdf"], key="paper_upload")
    if paper_up is not None:
        papers_dir = config.DATA_DIR / "papers"
        papers_dir.mkdir(parents=True, exist_ok=True)
        dest = papers_dir / paper_up.name
        if not dest.exists():
            dest.write_bytes(paper_up.getvalue())
        # 同一文件只解析一次（会话状态保存论文上下文，即"等待提问"状态）
        if st.session_state.get("paper_name") != paper_up.name:
            st.session_state["paper"] = parse_paper(dest)
            st.session_state["paper_name"] = paper_up.name
    paper = st.session_state.get("paper")
    if paper is not None:
        st.success(f"已解析《{paper.title}》（{paper.n_pages} 页）")
        if paper.outline:
            with st.expander("论文目录", expanded=True):
                st.dataframe(
                    [{"层级": e["level"], "标题": e["title"], "页码": e["page"]}
                     for e in paper.outline], hide_index=True)
        else:
            st.info("该论文无目录书签，已按全文处理")
        if paper.abstract:
            with st.expander("摘要"):
                st.write(paper.abstract)
        chat_block("b", paper=paper)
    else:
        st.info("请先上传论文 PDF")
```

- [ ] **Step 3: 启动并浏览器验证**

Run（后台）: `PYTHONIOENCODING=utf-8 uv run --no-sync streamlit run app.py --server.headless true --server.port 8501`

用 browser-use MCP 验证黄金路径：
1. `navigate_page` http://localhost:8501 → `take_snapshot`：侧边栏显示《通感一体化…》，两个页签存在
2. 模块A 页签输入"奈奎斯特采样定理说了什么？"→ 等待回答（spinner 消失）→ 确认出现 [机械✓]/[LLM✓] 徽章句与"出处目录"expander，展开见 3.1 节
3. 论文页签 `upload_file` 上传 `data/papers/CORE_TWC_09101709.pdf`（T5 才复制；本步先用 tests 夹具或任意小 PDF 验证上传解析链路，真实论文验收在 T5）→ 确认显示标题/目录表格
4. `take_screenshot` 留档；`list_console_messages` 无报错

Expected: 三步均正常；若 UI 报错，修复后重验。

- [ ] **Step 4: 提交**

```bash
git add app.py pyproject.toml uv.lock
git commit -m "feat: Streamlit 界面（资源库管理+双模块问答+核验徽章与出处可视化，D12）"
```

---

### Task 5: CORE 论文真实验收 + demo_m4.py

**Files:**
- Create: `scripts/demo_m4.py`
- 数据: 复制示例论文到 `data/papers/CORE_TWC_09101709.pdf`（gitignore，不提交）

**Interfaces:**
- Consumes: T1–T3 全部接口
- Produces: 可复跑的 M4 演示脚本；验收结论（论文目录展示 + 2 个知识点问答附库内出处）。

- [ ] **Step 1: 复制论文**

Run: `mkdir -p data/papers && cp "D:/仲谋/研究生/读论文/CORE_TWC_09101709.pdf" data/papers/`
Expected: 文件存在（约 13 页）

- [ ] **Step 2: 写 demo_m4.py**

```python
"""M4 演示：解析 CORE 论文 → 展示目录 → 带论文上下文问两个知识点 → 核验答案附库内出处。"""
import sys
from pathlib import Path

# 允许直接以脚本方式运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.agent import ask
from toolbook.paper import parse_paper

PAPER = Path(__file__).resolve().parents[1] / "data" / "papers" / "CORE_TWC_09101709.pdf"

# 两个与论文主题相关、且资源库覆盖的知识点问题
QUESTIONS = [
    "论文涉及多径接收，匹配滤波怎样产生一个离散样本？",
    "论文用到协方差估计，LMMSE 信道估计的原理是什么？",
]


def main():
    """解析论文并展示目录，逐题跑带论文上下文的问答，打印徽章句与出处。"""
    paper = parse_paper(PAPER)
    print(f"论文：《{paper.title}》（{paper.n_pages} 页，{len(paper.outline)} 条目录）")
    for e in paper.outline[:8]:
        print(f"  {'  ' * (e['level'] - 1)}{e['title']} <p{e['page']}>")
    print(f"摘要：{paper.abstract[:150]}…")
    for q in QUESTIONS:
        print(f"\n=== [论文问答] {q} ===")
        r = ask(q, paper=paper)
        if r.refused:
            print(f"  [拒答] {r.message}；已尝试：{r.searched}")
            continue
        for s in r.sentences:
            mark = "机械✓" if s.badge == "mechanical" else "LLM✓"
            print(f"  [{mark}][{s.ref}] {s.text}")
        for i, src in enumerate(r.sources):
            badge = "" if src.source == "original" else " [系统编号]"
            title = src.title.removeprefix(src.number).strip() or src.title
            print(f"  出处[{i}] 《{src.doc_title}》 {src.number} {title}{badge} <{src.locator}>")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 跑演示验收（真实 API）**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync python scripts/demo_m4.py`（timeout 600000）
Expected:
- 标题解析为 "CORE: Complementary Reception for Motion and Polarimetric Sensing from Communication Multipath"（或近似拼接），30 条目录
- 两题均返回核验徽章句 + 《通感一体化…》出处（6.2 / 7.4 相关节）
- 若某题拒答：分析是查询改写偏了还是库未覆盖；调 contextualize_query 提示词（不改核验链），重跑

- [ ] **Step 4: 浏览器端到端复验（真实论文）**

streamlit 仍在跑（T4 启动的后台进程）：browser-use 论文页签上传 `data/papers/CORE_TWC_09101709.pdf` → 确认 30 条目录表格 → 提问"匹配滤波怎样产生一个离散样本？"→ 确认徽章+出处。截图留档。

- [ ] **Step 5: 全量回归 + 提交**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest -q`
Expected: 79 passed

```bash
git add scripts/demo_m4.py
git commit -m "feat: M4 演示脚本（CORE 论文解析+带上下文问答附出处）"
```

---

### Task 6: 收尾（记忆 + 计划书 v0.7 + push）

**Files:**
- Modify: `项目计划书.md`（版本行 + 状态行 + M4 里程碑行）
- Modify: 项目记忆 `project-requirements-and-stack.md`

**Interfaces:**
- Consumes: T5 验收数字
- Produces: 文档与记忆同步；全部提交推送 GitHub。

- [ ] **Step 1: 更新项目记忆**

追加 M4 完成条目：paper.py 双栏自然阅读序结论（现有书籍解析器按 y 排序会交错双栏，论文必须用存储序）、contextualize_query 链路、streamlit 版本、验收结果、测试数；更新 git 状态与下一步（M5）。

- [ ] **Step 2: 计划书 v0.7**

版本行改 `v0.6（M1、M2、M3 完成）` → `v0.7（M1–M4 完成）`；状态行追加 M4 完成摘要（含验收数字）；里程碑表 M4 行加 ✅ 与完成日期、验收结果。

- [ ] **Step 3: 最终回归 + 提交 + push**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest -q`
Expected: 79 passed

```bash
git add 项目计划书.md
git commit -m "docs: 计划书 v0.7（M4 论文问答与 Streamlit 界面完成）"
git push origin master
```

push 失败重试一次；仍失败则告知用户延后手动 push。

---

## Self-Review 结论

1. **Spec 覆盖**：模块B"解析→展示目录→等待提问→跨库回答附目录"= T1（解析）+ T4（目录展示/会话状态）+ T2/T3（上下文查询）+ T4（出处展示）；D12 核验徽章可视化 = T4 render_answer；验收"上传论文就知识点提问，答案附本地书出处"= T5。M4 不含论文内容问答（答案只来自资源库，符合需求）。
2. **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码。
3. **类型一致性**：PaperInfo.context()、contextualize_query(question, paper_context)、generate_draft(question, hits, paper_context="")、ask(..., paper=None) 在各任务间签名一致；test_agent 旧 fixture 的 lambda 签名已在 T3 Step 1 同步修改。