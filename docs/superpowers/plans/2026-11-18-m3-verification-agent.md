# M3 核验与回答实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现项目招牌能力——两级原文核验（摘录机械子串匹配 + 归纳逐句 LLM 裁判）+ LangGraph 编排（核验失败换词重检索≤2次→拒答）+ 带核验徽章与出处目录的答案，并补上 M1 遗留的 LLM 兜底章节识别。

**Architecture:** 新增三个内核模块：`verify.py`（归一化/机械匹配/逐句裁判/分流核验）、`answering.py`（LLM 生成逐句带引用的答案草稿）、`agent.py`（LangGraph 状态图：retrieve→generate→verify→条件分支 finalize/retry/refuse，retry 回环 retrieve）。数据模型 VerifiedSentence/SourceRef/AnswerResult 进 models.py。LLM 兜底章节识别：llm.propose_titles 提议的标题必须在原文一字不差出现（机械锚定），structure.build_tree 接受 title_proposer 在无结构时按标题位置切分（全部标"系统编号"）。CLI 新增 ask；20 题验收集跑出处定位准确率。

**Tech Stack:** langgraph（StateGraph/START/END）、既有 llm.py（DeepSeek-V3.2）、既有 hybrid_search；pytest 离线单测（monkeypatch 假 LLM/假检索），真实 API 验收走 demo/eval 脚本。

**Spec:** `项目计划书.md` v0.5 第 4 节 M3 行 + 第 7 节要点 3/4 + `docs/决策点详解/D01/D05/D11`。

## Global Constraints

- D1/D5/D11 已定案不得重选：LangGraph 编排；两级混合核验；核验失败重检索最多 2 次；仍不行拒答"资源库未覆盖该知识点"并列出已检索范围。
- 摘录核验零误差：归一化（NFKC 全半角/中英标点统一/小写/去空白）后精确子串匹配；归纳句 LLM 裁判给出的依据 quote 必须再过一遍机械匹配（双重锚定），锚不住即剔除。
- 宁缺勿错：只返回核验通过的成分；LLM 裁判失败/无密钥时归纳句一律剔除（只留摘录）。
- 核验徽章透明：每条内容标"机械✓"或"LLM✓"；出处目录含书名/章节号/标题/定位，系统编号带徽标。
- LLM 兜底章节标题必须原文可定位（防编造章节号），编号一律 S 前缀系统编号；失败回退 M1 单节兜底。
- 密钥只从 .env/环境变量读取；不引入服务型组件；离线单测不触网。
- **zh-code-style**：所有新建/修改 .py 中文文件说明+功能块注释；回复展示代码注明路径行号；**新增 commit message 一律中文**（可保留 feat:/fix:/docs: 前缀），不改写历史提交。
- 每任务结束 commit；网络允许时 push（当前 GitHub 间歇性断连，失败则本地保留待推）。
- M3 验收：20 题评测（16 在库 + 4 超纲），在库题出处宽松命中≥80%，超纲题 100% 拒答。

## 文件结构

```
pyproject.toml                       +langgraph
src/toolbook/models.py               修改：+VerifiedSentence/SourceRef/AnswerResult（补中文注释）
src/toolbook/verify.py               新建：normalize/mechanical_ok/split_sentences/judge_sentence/verify_draft
src/toolbook/answering.py            新建：generate_draft（逐句带引用草稿）
src/toolbook/llm.py                  修改：+alternative_query/propose_titles
src/toolbook/agent.py                新建：LangGraph 状态图 + ask()
src/toolbook/structure.py            修改：build_tree +title_proposer 参数与 _llm_fallback_nodes（补中文注释）
src/toolbook/importer.py             修改：import_file +llm_fallback 参数（补中文注释）
src/toolbook/cli.py                  修改：+ask 子命令、import --no-llm-fallback
scripts/demo_m3.py                   新建：四场景演示（归纳/摘录/超纲拒答/重试）
scripts/eval_m3.py                   新建：20 题评测跑分
data/eval/m3_questions.json          新建：20 题验收集（gitignore 的 data/ 下，另存一份 tests/fixtures/m3_questions.json 入库）
tests/test_verify.py                 新建：归一化/机械匹配/裁判/分流（离线）
tests/test_answering.py              新建：草稿 JSON 解析/不足回退（离线）
tests/test_agent.py                  新建：图 wiring 三路径（离线假节点）
tests/test_llm_fallback.py           新建：标题提议过滤/无结构切分/导入接线（离线）
```

统一接口：`ask(question, db_path=DEFAULT_DB, use_rerank=True) -> AnswerResult`；`AnswerResult.sentences: list[VerifiedSentence]`（ref 与 hits 索引平行）、`sources: list[SourceRef]`（与 hits 平行）、`refused/retries/searched/message`。

---

### Task 1: 依赖 + 答案数据模型 + 核验基础（TDD）

**Files:**
- Modify: `pyproject.toml`（uv add langgraph）、`src/toolbook/models.py`
- Create: `src/toolbook/verify.py`（本任务只含基础三函数）、`tests/test_verify.py`

**Interfaces:**
- Produces:
  - `models.VerifiedSentence(text, kind, ref, badge, quote)`；`models.SourceRef(doc_title, number, title, source, locator)`；`models.AnswerResult(sentences, sources, refused=False, retries=0, searched=[], message="")`
  - `verify.normalize(text) -> str`；`verify.mechanical_ok(excerpt, source) -> bool`；`verify.split_sentences(text) -> list[str]`

- [ ] **Step 1: 安装依赖**

Run: `uv add langgraph`

- [ ] **Step 2: 写失败测试**

```python
# tests/test_verify.py
"""核验模块离线单测：归一化、机械子串匹配、拆句与两级分流。"""
from toolbook.verify import mechanical_ok, normalize, split_sentences


def test_normalize_fullwidth_and_space():
    # 全角字母/空格/中英标点统一后应相等
    assert normalize("Ｆｏｕｒｉｅｒ 变换，性质。") == normalize("fourier变换,性质.")


def test_mechanical_ok_exact():
    src = "采样定理指出：采样频率必须大于信号最高频率的两倍。"
    assert mechanical_ok("采样频率必须大于信号最高频率的两倍", src)
    # 全角/空格差异不影响匹配
    assert mechanical_ok("采样频率 必须大于信号最高频率的两倍", src)


def test_mechanical_rejects_altered():
    src = "采样频率必须大于信号最高频率的两倍。"
    assert not mechanical_ok("采样频率必须大于信号最高频率的三倍", src)
    assert not mechanical_ok("", src)


def test_split_sentences():
    assert split_sentences("第一句。第二句！第三句？") == ["第一句。", "第二句！", "第三句？"]
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_verify.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 4: models.py 追加数据类（文件头补中文说明）**

文件开头加 `"""核心数据模型：解析块、章节树节点、导入结果、核验句与最终答案。"""`，末尾追加：

```python
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
```

- [ ] **Step 5: 实现 verify.py 基础部分**

```python
"""两级原文核验（D11）：摘录走机械子串匹配，归纳走 LLM 逐句裁判 + 依据机械复核。

本项目的招牌防线：只返回核验通过的内容，宁缺勿错。
"""
import re
import unicodedata

# 中英标点统一映射：比对前归一化，避免"内容全对却因标点判失败"
_PUNCT_MAP = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":",
    "（": "(", "）": ")", "【": "[", "】": "]", "“": '"', "”": '"',
    "‘": "'", "’": "'", "、": ",", "－": "-", "—": "-", "～": "~",
})


def normalize(text: str) -> str:
    """核验归一化：NFKC 全半角统一、中英标点统一、转小写、去掉全部空白。"""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_PUNCT_MAP).lower()
    return re.sub(r"\s+", "", t)


def mechanical_ok(excerpt: str, source: str) -> bool:
    """机械核验：归一化后摘录必须是原文的子串（零误差、零成本）。"""
    e = normalize(excerpt)
    return bool(e) and e in normalize(source)


# 中英文句末标点拆句（与分块模块同一套切分哲学）
_SENT_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")


def split_sentences(text: str) -> list[str]:
    """把答案拆成句子（按中英文句末标点），供逐句核验。"""
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_verify.py -q`
Expected: 4 passed

- [ ] **Step 7: Commit（中文 message）**

```bash
git add pyproject.toml uv.lock src/toolbook/models.py src/toolbook/verify.py tests/test_verify.py
git commit -m "feat: 新增核验基础（归一化+机械子串匹配）与答案数据模型"
```

---

### Task 2: LLM 逐句裁判 + 分流核验 verify_draft（TDD）

**Files:**
- Modify: `src/toolbook/verify.py`
- Test: `tests/test_verify.py`（追加）

**Interfaces:**
- Consumes: `llm.chat(prompt, system) -> str`；`models.VerifiedSentence`；Task 1 三函数
- Produces:
  - `verify.judge_sentence(sentence, source) -> dict | None`（{"supported": bool, "quote": str}，失败 None）
  - `verify.verify_draft(sentences: list[dict], hits: list) -> list[VerifiedSentence]`（sentences 元素 {"text","type","ref"}；hits 为 SearchHit 列表，用 .text）

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_verify.py 追加
import toolbook.verify as vf
from toolbook.models import VerifiedSentence
from toolbook.retrieval import SearchHit


def _hit(text):
    # 构造最小 SearchHit 供核验测试
    return SearchHit(1, 1, "3.1", "采样", "original", "p21", text, 0.5, "both", "书")


def test_judge_parses_verdict(monkeypatch):
    monkeypatch.setattr(vf.llm, "chat", lambda *a, **k: '{"supported": true, "quote": "两倍"}')
    v = vf.judge_sentence("采样率要大于最高频率两倍", "采样频率必须大于最高频率的两倍。")
    assert v == {"supported": True, "quote": "两倍"}


def test_judge_failure_returns_none(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(vf.llm, "chat", boom)
    assert vf.judge_sentence("句", "原文") is None


def test_verify_draft_excerpt_mechanical():
    hits = [_hit("采样频率必须大于最高频率的两倍。")]
    draft = [{"text": "采样频率必须大于最高频率的两倍", "type": "excerpt", "ref": 0},
             {"text": "采样频率必须大于最高频率的三倍", "type": "excerpt", "ref": 0}]
    out = vf.verify_draft(draft, hits)
    assert len(out) == 1
    assert out[0].badge == "mechanical" and out[0].kind == "excerpt"


def test_verify_draft_summary_double_anchor(monkeypatch):
    hits = [_hit("采样频率必须大于最高频率的两倍。")]
    # LLM 裁判说支持且 quote 原文可锚 → 通过
    monkeypatch.setattr(vf, "judge_sentence", lambda s, src: {"supported": True, "quote": "两倍"})
    out = vf.verify_draft([{"text": "采样率需超过最高频率两倍", "type": "summary", "ref": 0}], hits)
    assert len(out) == 1 and out[0].badge == "llm"
    # quote 锚不住原文 → 剔除（宁缺勿错）
    monkeypatch.setattr(vf, "judge_sentence", lambda s, src: {"supported": True, "quote": "三倍"})
    assert vf.verify_draft([{"text": "采样率需超过最高频率两倍", "type": "summary", "ref": 0}], hits) == []
    # 裁判失败/不支持 → 剔除
    monkeypatch.setattr(vf, "judge_sentence", lambda s, src: None)
    assert vf.verify_draft([{"text": "句", "type": "summary", "ref": 0}], hits) == []


def test_verify_draft_bad_ref_dropped():
    hits = [_hit("原文")]
    assert vf.verify_draft([{"text": "原文", "type": "excerpt", "ref": 9}], hits) == []
```

注意：verify.py 需 `from . import llm` 与 `from .models import VerifiedSentence`（测试通过 `vf.llm.chat` 打桩）。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_verify.py -q`
Expected: 新增 5 个 FAIL/ERROR

- [ ] **Step 3: verify.py 追加实现**

```python
# --- 第二级：LLM 逐句裁判（管归纳句） ---

_JUDGE_SYSTEM = "你是原文核验裁判。判断给定句子是否有原文依据，只输出JSON，不要解释。"


def judge_sentence(sentence: str, source: str) -> dict | None:
    """LLM 裁判单句：返回 {"supported": bool, "quote": 原文依据}；任何失败返回 None。"""
    prompt = (f"原文：\n{source[:3000]}\n\n待核验句子：{sentence}\n"
              '若句子有原文依据，输出 {"supported": true, "quote": "支撑该句的原文连续片段（一字不差摘抄）"}；'
              '否则输出 {"supported": false, "quote": ""}。只输出JSON。')
    try:
        raw = llm.chat(prompt, _JUDGE_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        return {"supported": bool(d.get("supported")), "quote": str(d.get("quote", ""))}
    except Exception:
        return None


def verify_draft(sentences: list[dict], hits: list) -> list[VerifiedSentence]:
    """分流核验草稿：摘录→机械匹配；归纳→LLM裁判+依据quote机械复核（双重锚定）。

    只返回核验通过的句子；ref 越界、空句、裁判失败一律剔除（宁缺勿错）。
    """
    out: list[VerifiedSentence] = []
    for s in sentences:
        ref = s.get("ref", 0)
        text = str(s.get("text", "")).strip()
        if not isinstance(ref, int) or not (0 <= ref < len(hits)) or not text:
            continue
        h = hits[ref]
        if s.get("type") == "excerpt":
            # 第一级：摘录必须一字不差（归一化后）存在于原文
            if mechanical_ok(text, h.text):
                out.append(VerifiedSentence(text, "excerpt", ref, "mechanical", text))
        else:
            # 第二级：LLM 说支持，且其给出的依据 quote 还能机械锚回原文，才放行
            verdict = judge_sentence(text, h.text)
            if verdict and verdict["supported"] and mechanical_ok(verdict["quote"], h.text):
                out.append(VerifiedSentence(text, "summary", ref, "llm", verdict["quote"]))
    return out
```

文件头 import 区补 `import json`、`from . import llm`、`from .models import VerifiedSentence`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_verify.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/verify.py tests/test_verify.py
git commit -m "feat: 两级核验分流（摘录机械匹配+归纳LLM裁判双重锚定）"
```

---

### Task 3: 答案草稿生成 answering.py + 替代查询（TDD）

**Files:**
- Create: `src/toolbook/answering.py`, `tests/test_answering.py`
- Modify: `src/toolbook/llm.py`（+alternative_query）

**Interfaces:**
- Consumes: `llm.chat`；SearchHit（doc_title/number/title/locator/text）
- Produces:
  - `answering.generate_draft(question, hits) -> list[dict]`（[{"text","type","ref"}]；资料不足/失败返回 []）
  - `llm.alternative_query(question, tried: list[str]) -> str`（失败回退原问题）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_answering.py
"""答案草稿生成离线单测：JSON 解析、资料不足回退、替代查询降级。"""
import toolbook.answering as aw
import toolbook.llm as llm
from toolbook.retrieval import SearchHit


def _hit():
    return SearchHit(1, 1, "3.1", "采样", "original", "p21", "采样频率必须大于最高频率的两倍。", 0.5, "both", "书")


def test_generate_draft_parses_sentences(monkeypatch):
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return '```json\n{"insufficient": false, "sentences": [{"text": "采样频率必须大于最高频率的两倍。", "type": "excerpt", "ref": 0}]}\n```'

    monkeypatch.setattr(aw.llm, "chat", fake_chat)
    draft = aw.generate_draft("采样定理？", [_hit()])
    assert draft[0]["type"] == "excerpt" and draft[0]["ref"] == 0
    # 提示词必须带编号资料与出处
    assert "[0]" in captured["prompt"] and "3.1" in captured["prompt"]


def test_generate_draft_insufficient(monkeypatch):
    monkeypatch.setattr(aw.llm, "chat", lambda *a, **k: '{"insufficient": true, "sentences": []}')
    assert aw.generate_draft("超纲问题", [_hit()]) == []


def test_generate_draft_failure_and_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(aw.llm, "chat", boom)
    assert aw.generate_draft("问题", [_hit()]) == []
    assert aw.generate_draft("问题", []) == []


def test_alternative_query_fallback(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(llm, "chat", boom)
    assert llm.alternative_query("原问题", ["原问题"]) == "原问题"
    monkeypatch.setattr(llm, "chat", lambda *a, **k: " 新关键词 串 ")
    assert llm.alternative_query("原问题", ["原问题"]) == "新关键词 串"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_answering.py -q`
Expected: FAIL（模块不存在 / alternative_query 不存在）

- [ ] **Step 3: 实现 answering.py**

```python
"""答案生成：让 LLM 基于检索父块写逐句带引用的草稿（摘录/归纳分流，供核验）。"""
import json
import re

from . import llm

_GEN_SYSTEM = ("你是严谨的资源库问答助手。只能依据给定资料回答，逐句标注引用。"
               "资料不足时宁可承认不足，绝不编造。只输出JSON。")


def generate_draft(question: str, hits: list) -> list[dict]:
    """生成答案草稿 [{"text","type","ref"}]：excerpt 须一字不差摘抄，summary 须有依据。

    资料不足、调用失败或格式异常都返回空列表（由编排层触发重检索/拒答）。
    """
    if not hits:
        return []
    # 编号资料块：每块带完整出处，供 LLM 标引用
    sources = [f"[{i}] 《{h.doc_title}》{h.number} {h.title}（{h.locator}）\n{h.text[:1200]}"
               for i, h in enumerate(hits)]
    prompt = (f"问题：{question}\n\n资料：\n" + "\n\n".join(sources) +
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

- [ ] **Step 4: llm.py 追加 alternative_query**

```python
def alternative_query(question: str, tried: list[str]) -> str:
    """重检索替代查询：让 LLM 换一组不同的关键词；失败回退原问题。"""
    prompt = (f"原问题：{question}\n已尝试过的查询：{tried}\n"
              "请给出一组与上述都不同的检索关键词（中英混合、空格分隔），直接输出关键词串，不要解释。")
    try:
        out = chat(prompt).strip()
        return out or question
    except Exception:
        return question
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_answering.py -q`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/toolbook/answering.py src/toolbook/llm.py tests/test_answering.py
git commit -m "feat: 带引用答案草稿生成与重检索替代查询"
```

---

### Task 4: LangGraph 编排 agent.py（TDD，离线假节点测图 wiring）

**Files:**
- Create: `src/toolbook/agent.py`, `tests/test_agent.py`

**Interfaces:**
- Consumes: `hybrid_search(question, db_path, top_k, use_llm, use_rerank, doc_id)`、`generate_draft`、`verify_draft`、`llm.alternative_query`、models 三数据类
- Produces:
  - `agent.AgentState`（TypedDict：question/query/hits/draft/verified/retries/searched/result/db_path/use_rerank）
  - `agent.build_graph()`（编译后的 StateGraph）；`agent.ask(question, db_path=config.DEFAULT_DB, use_rerank=True) -> AnswerResult`
  - 节点函数 retrieve_node/generate_node/verify_node/retry_node/finalize_node/refuse_node、条件函数 route_after_verify；常量 MAX_RETRIES=2

图结构：`START→retrieve→generate→verify→{finalize|retry|refuse}`；`retry→retrieve`；`finalize/refuse→END`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agent.py
"""LangGraph 编排离线单测：用假检索/假生成/假核验验证三条路径（成功/重试/拒答）。"""
import pytest

import toolbook.agent as ag
from toolbook.models import VerifiedSentence
from toolbook.retrieval import SearchHit


def _hit():
    return SearchHit(1, 1, "3.1", "采样", "original", "p21", "原文内容", 0.5, "both", "书")


@pytest.fixture
def patch_nodes(monkeypatch):
    # 默认假节点：检索返回 1 个 hit，生成 1 句草稿
    monkeypatch.setattr(ag, "hybrid_search", lambda q, **k: [_hit()])
    monkeypatch.setattr(ag, "generate_draft", lambda q, hits: [{"text": "原文内容", "type": "excerpt", "ref": 0}])
    monkeypatch.setattr(ag.llm, "alternative_query", lambda q, tried: f"替代查询{len(tried)}")
    return monkeypatch


def test_ask_success(patch_nodes):
    # 核验一次通过：答案带徽章与出处，无重试
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [VerifiedSentence("原文内容", "excerpt", 0, "mechanical", "原文内容")])
    r = ag.ask("采样定理？")
    assert not r.refused and r.retries == 0
    assert r.sentences[0].badge == "mechanical"
    assert r.sources[0].number == "3.1"


def test_ask_retry_then_success(patch_nodes):
    # 前两次核验空、第三次通过：retries=2，查询被替换过
    calls = {"n": 0}

    def fake_verify(draft, hits):
        calls["n"] += 1
        if calls["n"] < 3:
            return []
        return [VerifiedSentence("原文内容", "excerpt", 0, "mechanical", "原文内容")]

    patch_nodes.setattr(ag, "verify_draft", fake_verify)
    r = ag.ask("难题？")
    assert not r.refused and r.retries == 2
    assert len(r.searched) == 3


def test_ask_refuse_after_retries(patch_nodes):
    # 核验永远空：重试 2 次后拒答，列出已检索范围
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [])
    r = ag.ask("超纲问题？")
    assert r.refused and r.retries == 2 and r.sentences == []
    assert "未覆盖" in r.message and len(r.searched) == 3


def test_ask_no_hits_refuse(patch_nodes):
    # 检索始终为空：不生成、直接走重试→拒答
    patch_nodes.setattr(ag, "hybrid_search", lambda q, **k: [])
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [])
    r = ag.ask("超纲问题？")
    assert r.refused
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_agent.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 agent.py**

```python
"""LangGraph 编排（D1）：检索→生成→核验→（重试≤2 / 拒答 / 定稿）状态图。

核验不通过沿回头路换查询词重检索；重试超限走拒答路径——宁缺勿错。
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import config, llm
from .answering import generate_draft
from .models import AnswerResult, SourceRef
from .retrieval import hybrid_search
from .verify import verify_draft

MAX_RETRIES = 2


class AgentState(TypedDict, total=False):
    """任务单：随图流转，每个节点读取并更新其中字段。"""
    question: str
    query: str
    db_path: object
    use_rerank: bool
    hits: list
    draft: list
    verified: list
    retries: int
    searched: list
    result: AnswerResult


def retrieve_node(state: AgentState) -> dict:
    """检索节点：用当前查询做混合检索，并记录已尝试的查询。"""
    hits = hybrid_search(state["query"], db_path=state.get("db_path", config.DEFAULT_DB),
                         top_k=5, use_rerank=state.get("use_rerank", True))
    return {"hits": hits, "searched": state.get("searched", []) + [state["query"]]}


def generate_node(state: AgentState) -> dict:
    """生成节点：LLM 基于检索父块写逐句带引用的草稿。"""
    return {"draft": generate_draft(state["question"], state["hits"])}


def verify_node(state: AgentState) -> dict:
    """核验节点：两级分流核验，只保留通过的句子。"""
    return {"verified": verify_draft(state["draft"], state["hits"])}


def route_after_verify(state: AgentState) -> str:
    """条件边：有核验内容→定稿；没有且还有重试额度→重试；否则→拒答。"""
    if state["verified"]:
        return "finalize"
    if state.get("retries", 0) < MAX_RETRIES:
        return "retry"
    return "refuse"


def retry_node(state: AgentState) -> dict:
    """重试节点：换一组关键词（LLM 替代查询，失败回退原问题），计数 +1。"""
    alt = llm.alternative_query(state["question"], state.get("searched", []))
    return {"retries": state.get("retries", 0) + 1, "query": alt}


def finalize_node(state: AgentState) -> dict:
    """定稿节点：组装核验答案 + 出处目录（与 hits 索引平行，供角标引用）。"""
    sources = [SourceRef(h.doc_title, h.number, h.title, h.source, h.locator)
               for h in state["hits"]]
    return {"result": AnswerResult(state["verified"], sources,
                                   retries=state.get("retries", 0),
                                   searched=state.get("searched", []))}


def refuse_node(state: AgentState) -> dict:
    """拒答节点：明确告知未覆盖，并列出已尝试的检索范围。"""
    return {"result": AnswerResult([], [], refused=True,
                                   retries=state.get("retries", 0),
                                   searched=state.get("searched", []),
                                   message="资源库未覆盖该知识点")}


def build_graph():
    """构建并编译状态图：retrieve→generate→verify→条件分支，retry 回环 retrieve。"""
    g = StateGraph(AgentState)
    for name, fn in [("retrieve", retrieve_node), ("generate", generate_node),
                     ("verify", verify_node), ("retry", retry_node),
                     ("finalize", finalize_node), ("refuse", refuse_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "verify")
    g.add_conditional_edges("verify", route_after_verify,
                            {"finalize": "finalize", "retry": "retry", "refuse": "refuse"})
    g.add_edge("retry", "retrieve")
    g.add_edge("finalize", END)
    g.add_edge("refuse", END)
    return g.compile()


def ask(question: str, db_path=config.DEFAULT_DB, use_rerank: bool = True) -> AnswerResult:
    """模块A 问答主入口：跑完整 检索→生成→核验→（重试/拒答）流程。"""
    graph = build_graph()
    final = graph.invoke({"question": question, "query": question,
                          "db_path": db_path, "use_rerank": use_rerank,
                          "retries": 0, "searched": []})
    return final["result"]
```

注意：节点内引用的 hybrid_search/generate_draft/verify_draft/llm 都是模块级名字，测试通过 monkeypatch ag.xxx 打桩。LangGraph invoke 的 recursion_limit 默认 25，本图最长路径约 11 步，够用。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_agent.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/agent.py tests/test_agent.py
git commit -m "feat: LangGraph 编排（检索→生成→核验→重试≤2→拒答/定稿）"
```

---

### Task 5: LLM 兜底章节识别（D5 遗留项，TDD）

**Files:**
- Modify: `src/toolbook/llm.py`（+propose_titles）、`src/toolbook/structure.py`、`src/toolbook/importer.py`、`src/toolbook/cli.py`（import --no-llm-fallback）
- Create: `tests/test_llm_fallback.py`

**Interfaces:**
- Produces:
  - `llm.propose_titles(text) -> list[str]`（只保留原文中一字不差出现、≤60 字的标题；失败 []）
  - `structure.build_tree(blocks, doc_title="", title_proposer=None)`（无结构且有 proposer 时按标题切分，S 编号；<2 个可定位标题回退单节）
  - `importer.import_file(path, db_path=DEFAULT_DB, parser=None, llm_fallback=True)`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_fallback.py
"""LLM 兜底章节识别离线单测：标题原文锚定、无结构切分、导入接线。"""
import pytest

import toolbook.llm as llm
from toolbook.models import Block
from toolbook.structure import build_tree


def test_propose_titles_filters_fabricated(monkeypatch):
    # LLM 提议的标题必须在原文一字不差出现，编造的被过滤
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '["采样定理", "编造的标题"]')
    titles = llm.propose_titles("本章讲采样定理。后面是卷积。")
    assert titles == ["采样定理"]


def test_propose_titles_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(llm, "chat", boom)
    assert llm.propose_titles("文本") == []


def test_build_tree_llm_fallback_splits():
    # 无标题文档：proposer 给出两个可定位标题 → 切成两个系统编号节
    blocks = [Block("开头引言。", "paragraph", 0, "p1"),
              Block("采样定理", "paragraph", 0, "p1"),
              Block("采样频率要大于两倍。", "paragraph", 0, "p1"),
              Block("卷积定义", "paragraph", 0, "p2"),
              Block("卷积是加权求和。", "paragraph", 0, "p2")]
    roots = build_tree(blocks, "书", title_proposer=lambda t: ["采样定理", "卷积定义"])
    nums = [n.number for n in roots]
    assert "S1" in nums and "S2" in nums
    assert all(n.source == "system" for n in roots)
    s1 = next(n for n in roots if n.number == "S1")
    assert "采样频率要大于两倍" in s1.text


def test_build_tree_fallback_fabricated_titles():
    # 标题都锚不住 → 回退 M1 单节兜底
    blocks = [Block("正文一。", "paragraph", 0, "p1"), Block("正文二。", "paragraph", 0, "p2")]
    roots = build_tree(blocks, "书", title_proposer=lambda t: ["不存在标题"])
    assert len(roots) == 1 and roots[0].number == "1"


def test_import_file_llm_fallback(tmp_path, monkeypatch):
    # 无标题 DOCX 导入：默认启用 LLM 兜底（打桩），产出多个系统编号节
    import toolbook.llm as llm_mod
    from docx import Document
    from toolbook.importer import import_file
    from toolbook.store import LibraryStore
    monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: '["甲部分", "乙部分"]')
    d = Document()
    d.add_paragraph("甲部分")
    d.add_paragraph("甲的内容。")
    d.add_paragraph("乙部分")
    d.add_paragraph("乙的内容。")
    p = tmp_path / "flat.docx"
    d.save(str(p))
    db = tmp_path / "lib.db"
    r = import_file(p, db)
    store = LibraryStore(db)
    rows = store.get_tree(r.doc_id)
    store.close()
    assert any(x["number"] == "S1" for x in rows)
    assert any(x["number"] == "S2" for x in rows)
```

注意：`_promote_numbered_paragraphs` 只提升带编号的短段落，"甲部分/乙部分"不带编号不会被提升，走无结构分支。import_file 内部必须以 `from . import llm` 模块引用方式调用 `llm.propose_titles`，测试才能打桩 llm.chat 生效。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_llm_fallback.py -q`
Expected: FAIL

- [ ] **Step 3: llm.py 追加 propose_titles**

```python
def propose_titles(text: str) -> list[str]:
    """LLM 兜底章节识别（D5）：为无结构文本提议章节标题。

    防编造：只保留原文中一字不差出现且 ≤60 字的标题；任何失败返回空列表。
    """
    prompt = (f"以下是一本书的正文片段：\n{text[:3000]}\n\n"
              "请提议 3–10 个章节标题，每个标题必须是原文中一字不差出现的连续片段（不超过60字）。"
              '只输出JSON数组，如 ["标题一", "标题二"]。')
    try:
        raw = chat(prompt, "你是章节结构识别器。只输出JSON数组，不要解释。")
        m = re.search(r"\[.*\]", raw, re.S)
        titles = json.loads(m.group(0))
        return [t for t in titles if isinstance(t, str) and 0 < len(t) <= 60 and t in text]
    except Exception:
        return []
```

- [ ] **Step 4: structure.py 改造（补文件级中文说明与函数注释）**

文件头加 `"""章节树构建：规则优先提取编号标题，无结构时可选 LLM 兜底切分（系统编号）。"""`。
`build_tree` 签名改为 `def build_tree(blocks: list[Block], doc_title: str = "", title_proposer=None) -> list[SectionNode]:`，`if not roots:` 分支改为：

```python
    if not roots:
        text = "\n".join(b.text for b in blocks)
        # LLM 兜底（D5）：提议标题并按位置切分；失败回退单节
        if title_proposer is not None:
            nodes = _llm_fallback_nodes(blocks, text, title_proposer)
            if nodes:
                return nodes
        roots = [SectionNode("1", doc_title or "全文", 1, "system", "", text)]
```

新增函数：

```python
def _llm_fallback_nodes(blocks: list[Block], text: str, proposer) -> list[SectionNode]:
    """按 LLM 提议标题切分无结构文本：标题必须能在某个块中定位，至少 2 个才生效。"""
    try:
        titles = proposer(text)
    except Exception:
        return []
    # 每个标题定位到首次出现的块索引
    cuts = []
    for t in titles:
        for i, b in enumerate(blocks):
            if t in b.text:
                cuts.append((i, t))
                break
    cuts.sort(key=lambda x: x[0])
    # 同块去重；不足 2 个切分点则兜底失败
    uniq = []
    for i, t in cuts:
        if not uniq or uniq[-1][0] != i:
            uniq.append((i, t))
    if len(uniq) < 2:
        return []
    nodes = []
    # 首个标题前的内容作为前言保留
    if uniq[0][0] > 0:
        pre = "\n".join(b.text for b in blocks[:uniq[0][0]])
        nodes.append(SectionNode("0", "前言", 1, "system", blocks[0].locator, pre))
    for k, (start, title) in enumerate(uniq):
        end = uniq[k + 1][0] if k + 1 < len(uniq) else len(blocks)
        body = "\n".join(b.text for b in blocks[start:end])
        nodes.append(SectionNode(f"S{k + 1}", title, 1, "system", blocks[start].locator, body))
    return nodes
```

- [ ] **Step 5: importer.py 接线（补文件级中文说明）**

文件头加 `"""导入流水线：文件哈希幂等 → 解析 → 章节树（可选 LLM 兜底）→ 父子块入库。"""`。
`import_file` 签名与 build_tree 调用改为：

```python
def import_file(path, db_path=DEFAULT_DB, parser: Parser | None = None,
                llm_fallback: bool = True) -> ImportResult:
    """导入一本书：哈希去重 → 解析 → 建章节树 → 单事务入库；llm_fallback 控制无结构文档的 LLM 兜底。"""
    ...
        parsed = (parser or get_parser(path)).parse(path)
        # 无结构文档的 LLM 兜底（D5）：以模块引用传入，便于离线测试打桩
        proposer = None
        if llm_fallback:
            from . import llm
            proposer = llm.propose_titles
        tree = build_tree(parsed.blocks, doc_title=parsed.title, title_proposer=proposer)
    ...
```

- [ ] **Step 6: cli.py import 子命令加 --no-llm-fallback**

```python
    p_imp.add_argument("--no-llm-fallback", action="store_true", help="禁用无结构文档的 LLM 兜底")
```
import 分支调用改 `r = import_file(f, args.db, llm_fallback=not args.no_llm_fallback)`。

- [ ] **Step 7: 全量回归（确认 M1/M2 测试不受影响）**

Run: `uv run --no-sync pytest -q`
Expected: 全部 passed。若有旧测试导入无结构文档触发真实 API，给该测试的 import_file 传 llm_fallback=False（保持离线）。

- [ ] **Step 8: Commit**

```bash
git add src/toolbook/llm.py src/toolbook/structure.py src/toolbook/importer.py src/toolbook/cli.py tests/test_llm_fallback.py
git commit -m "feat: LLM 兜底章节识别（标题原文锚定+系统编号，D5 遗留项补齐）"
```

---

### Task 6: CLI ask + 演示 + 20 题验收

**Files:**
- Modify: `src/toolbook/cli.py`（+ask）
- Create: `scripts/demo_m3.py`, `scripts/eval_m3.py`, `tests/fixtures/m3_questions.json`

**Interfaces:**
- Consumes: `agent.ask`、AnswerResult
- Produces: CLI `python -m toolbook.cli ask QUESTION [--no-rerank]`；`uv run python scripts/demo_m3.py`；`uv run python scripts/eval_m3.py`（读 tests/fixtures/m3_questions.json，报告写 data/eval/m3_report.json）。

- [ ] **Step 1: cli.py 加 ask 子命令**

argparse 区追加：

```python
    # --- M3 新增：资源库问答（检索→核验→带出处答案/拒答） ---
    p_ask = sub.add_parser("ask", help="资源库问答（两级核验+出处目录）")
    p_ask.add_argument("question")
    p_ask.add_argument("--no-rerank", action="store_true", help="跳过本地重排")
```

main 分支（index/search 之后）追加：

```python
    if args.cmd == "ask":
        import os
        from .agent import ask
        if args.no_rerank:
            os.environ["TOOLBOOK_RERANK"] = "off"
        r = ask(args.question, args.db, use_rerank=not args.no_rerank)
        if r.refused:
            print(f"[拒答] {r.message}")
            print(f"已尝试查询：{r.searched}（重试 {r.retries} 次）")
            return
        # 归纳/摘录句逐条打印，带核验徽章与引用角标
        for s in r.sentences:
            mark = "机械✓" if s.badge == "mechanical" else "LLM✓"
            print(f"[{mark}][{s.ref}] {s.text}")
        print(f"\n出处目录（重试 {r.retries} 次）：")
        for i, src in enumerate(r.sources):
            badge = "" if src.source == "original" else " [系统编号]"
            title = src.title.removeprefix(src.number).strip() or src.title
            print(f"  [{i}] 《{src.doc_title}》 {src.number} {title}{badge}  <{src.locator}>")
        return
```

- [ ] **Step 2: 写 20 题验收集 tests/fixtures/m3_questions.json**

16 在库题（expect 为可接受章节号列表）+ 4 超纲题（expect_refuse=true）：

```json
[
  {"id": 1, "question": "奈奎斯特采样定理说了什么？", "expect": ["3.1"]},
  {"id": 2, "question": "两径信道为什么可以写成一个卷积？", "expect": ["3.2"]},
  {"id": 3, "question": "DFT 的物理意义是什么？", "expect": ["3.3"]},
  {"id": 4, "question": "复数在信号表示中起什么作用？", "expect": ["2.1", "2.2"]},
  {"id": 5, "question": "匹配滤波怎样产生一个离散样本？", "expect": ["6.2"]},
  {"id": 6, "question": "QPSK 的误码率怎么推导？", "expect": ["6.3"]},
  {"id": 7, "question": "循环前缀为什么能把线性卷积变成循环卷积？", "expect": ["8.2", "8.1", "8.3"]},
  {"id": 8, "question": "最小二乘估计的几何解释是什么？", "expect": ["5.2"]},
  {"id": 9, "question": "SVD 怎样揭示可观测与不可观测方向？", "expect": ["5.3"]},
  {"id": 10, "question": "雷达方程为什么是四次方损耗？", "expect": ["10.2"]},
  {"id": 11, "question": "距离分辨率由什么决定？", "expect": ["10.3"]},
  {"id": 12, "question": "模糊范围与分辨率有什么区别？", "expect": ["10.4"]},
  {"id": 13, "question": "LMMSE 信道估计的原理是什么？", "expect": ["7.4"]},
  {"id": 14, "question": "导频在信道估计中起什么作用？", "expect": ["7.2", "7.3"]},
  {"id": 15, "question": "What is the role of the cyclic prefix in OFDM?", "expect": ["8.2", "8.3", "8.1"]},
  {"id": 16, "question": "How does Doppler shift cause inter-carrier interference?", "expect": ["8.4"]},
  {"id": 17, "question": "量子色动力学中的渐近自由怎么证明？", "expect_refuse": true},
  {"id": 18, "question": "如何用 CRISPR 技术编辑基因？", "expect_refuse": true},
  {"id": 19, "question": "唐朝的科举制度是怎样的？", "expect_refuse": true},
  {"id": 20, "question": "大语言模型 KV cache 的显存优化有哪些工程技巧？", "expect_refuse": true}
]
```

- [ ] **Step 3: 写 scripts/eval_m3.py**

```python
"""M3 验收评测：20 题（16 在库 + 4 超纲）跑 ask()，统计出处命中与拒答正确率。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.agent import ask
from toolbook.config import DATA_DIR

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "m3_questions.json"


def hit_level(item, result):
    """命中判定：strict=章节号完全一致；loose=允许章级前缀（3 对 3.1）。"""
    nums = [s.number for s in result.sources]
    strict = any(n in item["expect"] for n in nums)
    loose = any(n == e or e.startswith(n + ".") or n.startswith(e + ".")
                for n in nums for e in item["expect"])
    return strict, loose


def main():
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows, n_strict, n_loose, n_in, n_ref_ok, n_ref = [], 0, 0, 0, 0, 0
    for item in items:
        r = ask(item["question"])
        if item.get("expect_refuse"):
            n_ref += 1
            ok = r.refused
            n_ref_ok += ok
            rows.append({"id": item["id"], "type": "out", "ok": ok, "refused": r.refused})
            print(f"[{item['id']:>2}] 超纲 {'✓拒答' if ok else '✗硬答'}  {item['question']}")
        else:
            n_in += 1
            strict, loose = hit_level(item, r)
            n_strict += strict
            n_loose += loose
            nums = [s.number for s in r.sources]
            rows.append({"id": item["id"], "type": "in", "strict": strict, "loose": loose,
                         "expect": item["expect"], "got": nums, "refused": r.refused,
                         "retries": r.retries})
            print(f"[{item['id']:>2}] 在库 {'✓' if loose else '✗'} 期望{item['expect']} 得到{nums}  {item['question']}")
    report = {"in_total": n_in, "strict": n_strict, "loose": n_loose,
              "out_total": n_ref, "refuse_ok": n_ref_ok, "rows": rows}
    out = DATA_DIR / "eval" / "m3_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n在库 {n_in} 题：严格命中 {n_strict}，宽松命中 {n_loose}（{n_loose/n_in:.0%}）")
    print(f"超纲 {n_ref} 题：正确拒答 {n_ref_ok}（{n_ref_ok/n_ref:.0%}）")
    print(f"报告：{out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 写 scripts/demo_m3.py**

```python
"""M3 演示：归纳问答 / 原文摘录 / 超纲拒答 三场景，展示核验徽章与出处目录。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.agent import ask

SCENES = [
    ("归纳问答", "循环前缀为什么能消除符号间干扰？"),
    ("原文摘录", "请摘录原文中关于采样定理条件的原话。"),
    ("超纲拒答", "量子引力理论的重整化方法有哪些？"),
]


def main():
    for label, q in SCENES:
        print(f"\n=== [{label}] {q} ===")
        r = ask(q)
        if r.refused:
            print(f"  [拒答] {r.message}；已尝试：{r.searched}")
            continue
        for s in r.sentences:
            mark = "机械✓" if s.badge == "mechanical" else "LLM✓"
            print(f"  [{mark}][{s.ref}] {s.text}")
        for i, src in enumerate(r.sources):
            badge = "" if src.source == "original" else " [系统编号]"
            print(f"  出处[{i}] 《{src.doc_title}》 {src.number} {src.title}{badge} <{src.locator}>")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 全量离线回归**

Run: `uv run --no-sync pytest -q`
Expected: 全部 passed（M2 46 + M3 新增约 22）。

- [ ] **Step 6: 真实 API 演示与验收**

Run: `uv run python scripts/demo_m3.py`
Expected: 归纳/摘录场景带徽章输出与出处；超纲场景拒答。
Run: `uv run python scripts/eval_m3.py`（20 题 × 每题约 3–8 次 LLM 调用，预计 10–20 分钟）
Expected: 宽松命中≥80%（13/16），超纲 4/4 拒答。未达标则分析 bad case（检索问题修 D7 参数/核验提示词），不砍核验链路。

- [ ] **Step 7: Commit + push（网络允许时）**

```bash
git add src/toolbook/cli.py scripts/demo_m3.py scripts/eval_m3.py tests/fixtures/m3_questions.json
git commit -m "feat: M3 问答 CLI、三场景演示与 20 题验收集"
git push
```

---

### Task 7: 收尾（记忆 + 计划书 + 最终回归）

- [ ] **Step 1: 更新项目记忆**：M3 完成状态、验收数字、LangGraph 版本、兜底接线方式、新坑记录。
- [ ] **Step 2: 计划书 v0.6**：状态行 + M3 行标 ✅（含实际完成日期与验收数字）。
- [ ] **Step 3: 最终回归 + commit + push**：`uv run --no-sync pytest -q` 全过；`git commit -m "docs: 计划书 v0.6（M3 核验与回答完成）"`；push 失败则记录待推。

## Self-Review 结论

- 规格覆盖：D11 两级核验+回炉+拒答→Task 1/2/4；D1 LangGraph 循环→Task 4；D5 LLM 兜底（M1 遗留）→Task 5；出处目录+徽章可视化→Task 6 CLI/demo；M3 验收 20 题→Task 6。
- 离线可测：全部单测 monkeypatch（vf.llm.chat / aw.llm.chat / ag.hybrid_search 等），不触网；真实 API 只在 demo/eval。
- 类型一致性：VerifiedSentence(text,kind,ref,badge,quote)、SourceRef 五字段、AnswerResult 字段、verify_draft/generate_draft/ask 签名已跨任务核对；SearchHit 字段沿用 M2。
- 已知留白：模块B 论文上下文（M4）、Streamlit UI（M4）、评测集扩到 30 题与消融实验（M5）。