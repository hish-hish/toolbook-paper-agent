# M4 增强：会话上下文记忆 + 论文例题抽检 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 模块A 保留最近 5 轮问答记忆、模块B 每篇论文独立记忆（超 6 轮自动压缩、换论文不串上下文），并从 CORE 论文自拟 6 个例题喂入 Streamlit app 抽检、留存问答记录供用户检查。

**Architecture:** 新增 session.py 的 Conversation（轮次列表 + 摘要 digest；截断/压缩/清空），历史只以文本形式注入查询改写与答案生成的"背景段"（明确不作为答案依据），核验链不动。agent.ask 增加 history_context 参数；UI 用 st.session_state 持有模块A 单个 Conversation 与模块B 按论文名键控的 Conversation 字典，聊天记录也按论文名键控。

**Tech Stack:** 现有栈（langgraph 1.2.22 / streamlit 1.67.0 / pytest），无新依赖。

**Spec:** 用户原话："模块A要5轮，模块B要把每篇论文的上下文都记下来，可以自动压缩，不同的论文清空上下文"；"你自己在论文中找些例子，然后喂给这个app，看看输出结果是否正确，把问答保留让我检查"。解读：模块B 每篇论文各自一份记忆（换论文时启用该论文自己的记忆，新论文为空——上下文不跨论文混用）；压缩阈值 6 轮、保留最近 3 轮 + digest 为默认参数。

## Global Constraints

- zh-code-style：.py 文件中文模块 docstring + 函数/功能块中文注释；回复展示代码给路径行号；新增 commit 中文 message。
- 宁缺勿错：历史与论文背景**只供理解问题（指代/追问），绝不作为答案依据**；答案仍只来自库内父块且过两级核验。
- 压缩失败（断网/格式异常）机械回退：旧轮原文拼进 digest 截断，不丢历史不抛异常。
- 运行 `uv run --no-sync`；中文输出 `PYTHONIOENCODING=utf-8`；data/ gitignored（迷你测试论文不提交）。
- 单元测试离线（monkeypatch）；真实 API 仅用于浏览器抽检。
- 每任务一提交（中文）；push 失败重试一次后延后告知用户。

---

### Task 1: 会话记忆 session.py + 压缩摘要 llm.summarize_turns

**Files:**
- Create: `src/toolbook/session.py`
- Modify: `src/toolbook/llm.py`（末尾追加 summarize_turns）
- Test: `tests/test_session.py`（新建）、`tests/test_llm.py`（追加 1 测试）

**Interfaces:**
- Consumes: `llm.chat(prompt, system="", model=None)`
- Produces: `Turn(question: str, answer: str)`；`Conversation(max_turns=5, compress_threshold=0, keep_recent=3)`，方法 `add(question, answer)`、`context() -> str`（无历史返回 ""）、`clear()`；属性 `turns: list[Turn]`、`digest: str`。`llm.summarize_turns(turns_text: str) -> str`（失败抛异常由调用方回退）。

- [ ] **Step 1: 写失败测试**

`tests/test_session.py`：

```python
"""会话记忆离线单测：5 轮截断、自动压缩与失败回退、清空。"""
import toolbook.session as ss


def test_empty_context():
    # 无历史时上下文为空串（ask 走原问题路径）
    assert ss.Conversation().context() == ""


def test_module_a_trims_to_five():
    # 模块A：只保留最近 5 轮，旧轮彻底丢弃
    conv = ss.Conversation(max_turns=5)
    for i in range(7):
        conv.add(f"问{i}", f"答{i}")
    assert len(conv.turns) == 5
    assert conv.turns[0].question == "问2"
    assert "问0" not in conv.context() and "问6" in conv.context()


def test_module_b_compresses(monkeypatch):
    # 模块B：第 7 轮触发压缩，旧 4 轮进 digest，保留最近 3 轮
    monkeypatch.setattr(ss.llm, "summarize_turns", lambda text: "压缩摘要")
    conv = ss.Conversation(max_turns=6, compress_threshold=6, keep_recent=3)
    for i in range(7):
        conv.add(f"问{i}", f"答{i}")
    assert len(conv.turns) == 3 and conv.turns[0].question == "问4"
    assert conv.digest == "压缩摘要"
    assert "压缩摘要" in conv.context() and "问6" in conv.context()


def test_compress_fallback(monkeypatch):
    # LLM 压缩失败：旧轮原文机械拼进 digest，不丢历史不抛异常
    def boom(text):
        raise RuntimeError("offline")
    monkeypatch.setattr(ss.llm, "summarize_turns", boom)
    conv = ss.Conversation(max_turns=6, compress_threshold=6, keep_recent=3)
    for i in range(7):
        conv.add(f"问{i}", f"答{i}")
    assert "问0" in conv.digest and len(conv.turns) == 3


def test_clear():
    # 清空后上下文为空
    conv = ss.Conversation()
    conv.add("问", "答")
    conv.clear()
    assert conv.context() == "" and conv.turns == []
```

`tests/test_llm.py` 末尾追加：

```python
def test_summarize_turns(monkeypatch):
    # 压缩摘要：去首尾空白直接返回
    monkeypatch.setattr(llm, "chat", lambda *a, **k: " 摘要 ")
    assert llm.summarize_turns("问: x\n答: y") == "摘要"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_session.py tests/test_llm.py -q`
Expected: test_session 收集错误（模块不存在）+ summarize 测试 AttributeError

- [ ] **Step 3: 实现**

`src/toolbook/session.py`：

```python
"""会话上下文记忆：模块A 最近 5 轮截断；模块B 每篇论文独立、超阈值自动压缩。

历史只供查询改写与理解问题（指代/追问），绝不作为答案依据。
"""
from dataclasses import dataclass

from . import llm


@dataclass
class Turn:
    """一轮问答：问题 + 答案要点（核验句拼接或拒答原因，截断 400 字）。"""
    question: str
    answer: str


class Conversation:
    """一段会话的记忆：max_turns 截断；compress_threshold>0 时超阈值把旧轮压缩进 digest。"""

    def __init__(self, max_turns: int = 5, compress_threshold: int = 0,
                 keep_recent: int = 3):
        self.max_turns = max_turns
        self.compress_threshold = compress_threshold  # 0=不压缩（模块A）
        self.keep_recent = keep_recent
        self.turns: list[Turn] = []
        self.digest: str = ""

    def add(self, question: str, answer: str):
        """记一轮；超压缩阈值先压缩旧轮，再按 max_turns 截断。"""
        self.turns.append(Turn(question, answer[:400]))
        if self.compress_threshold and len(self.turns) > self.compress_threshold:
            self._compress()
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def _compress(self):
        """除最近 keep_recent 轮外压缩进 digest；LLM 失败回退旧轮原文拼接。"""
        old = self.turns[:-self.keep_recent]
        self.turns = self.turns[-self.keep_recent:]
        text = "\n".join(f"问: {t.question}\n答: {t.answer}" for t in old)
        try:
            summary = llm.summarize_turns(text)
        except Exception:
            summary = ""
        joined = "\n".join(p for p in (self.digest, summary or text) if p)
        self.digest = joined[-800:]

    def context(self) -> str:
        """供改写/生成的上下文文本：早期摘要 + 最近轮次；无历史返回空串。"""
        if not self.turns and not self.digest:
            return ""
        parts = []
        if self.digest:
            parts.append(f"早期对话要点: {self.digest}")
        parts += [f"问: {t.question}\n答: {t.answer}" for t in self.turns]
        return "\n".join(parts)[:2000]

    def clear(self):
        """清空本会话记忆。"""
        self.turns = []
        self.digest = ""
```

`src/toolbook/llm.py` 末尾追加：

```python
def summarize_turns(turns_text: str) -> str:
    """把旧问答轮次压缩成要点（保留知识点与结论）；失败抛异常由调用方回退。"""
    prompt = (f"以下是用户与资源库的历史问答：\n{turns_text[:3000]}\n\n"
              "请压缩成不超过200字的要点，保留讨论过的知识点与结论，直接输出要点。")
    return chat(prompt).strip()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_session.py tests/test_llm.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/toolbook/session.py src/toolbook/llm.py tests/test_session.py tests/test_llm.py
git commit -m "feat: 会话记忆（模块A五轮截断/模块B自动压缩与失败回退）"
```

---

### Task 2: 历史注入改写与生成（agent/answering/llm 提示词）

**Files:**
- Modify: `src/toolbook/llm.py`（contextualize_query 提示词改为通用"提问背景"）
- Modify: `src/toolbook/answering.py`（generate_draft 加 history_context 参数）
- Modify: `src/toolbook/agent.py`（AgentState 加 history_context；generate_node 传参；ask 加 history_context）
- Test: `tests/test_answering.py`（+1）、`tests/test_agent.py`（fixture 签名 +1 测试）

**Interfaces:**
- Consumes: T1 `Conversation.context() -> str`（本任务只收 str）
- Produces: `generate_draft(question, hits, paper_context="", history_context="")`；`ask(question, db_path=config.DEFAULT_DB, use_rerank=True, paper=None, history_context="")`。有 paper 或 history 时初始查询走 `llm.contextualize_query(question, 合并背景)`，否则原问题（M3 行为不变）。

- [ ] **Step 1: 写失败测试**

`tests/test_answering.py` 末尾追加：

```python
def test_generate_draft_with_history(monkeypatch):
    # 对话历史进入提示词且明确"不作为答案依据"
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return '{"insufficient": false, "sentences": [{"text": "采样频率必须大于最高频率的两倍。", "type": "excerpt", "ref": 0}]}'

    monkeypatch.setattr(aw.llm, "chat", fake_chat)
    aw.generate_draft("复基带情形呢？", [_hit()],
                      history_context="问: 采样定理说了什么？\n答: fs>2B")
    assert "对话历史" in captured["prompt"] and "fs>2B" in captured["prompt"]
    assert "不作为答案依据" in captured["prompt"]
```

`tests/test_agent.py`：patch_nodes fixture 的假生成改四参签名：

```python
    monkeypatch.setattr(ag, "generate_draft", lambda q, hits, ctx="", hist="": [{"text": "原文内容", "type": "excerpt", "ref": 0}])
```

test_ask_with_paper_contextualizes_query 内 fake_gen 同步改签名：

```python
    def fake_gen(q, hits, ctx="", hist=""):
        seen["ctx"] = ctx
        return [{"text": "原文内容", "type": "excerpt", "ref": 0}]
```

末尾追加：

```python
def test_ask_with_history_context(patch_nodes):
    # 带历史提问：合并背景进改写、历史进生成节点
    seen = {}

    def fake_search(q, **k):
        seen.setdefault("queries", []).append(q)
        return [_hit()]

    def fake_gen(q, hits, ctx="", hist=""):
        seen["hist"] = hist
        return [{"text": "原文内容", "type": "excerpt", "ref": 0}]

    def fake_ctx(q, bg):
        seen["bg"] = bg
        return "关键词"

    patch_nodes.setattr(ag, "hybrid_search", fake_search)
    patch_nodes.setattr(ag, "generate_draft", fake_gen)
    patch_nodes.setattr(ag.llm, "contextualize_query", fake_ctx)
    patch_nodes.setattr(ag, "verify_draft", lambda d, h: [VerifiedSentence("原文内容", "excerpt", 0, "mechanical", "原文内容")])
    r = ag.ask("复基带情形呢？", history_context="问: 采样定理说了什么？\n答: fs>2B")
    assert not r.refused
    assert "采样定理" in seen["bg"] and "fs>2B" in seen["bg"]
    assert seen["queries"][0] == "关键词"
    assert "采样定理" in seen["hist"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest tests/test_answering.py tests/test_agent.py -q`
Expected: 新增 2 个 FAIL，其余 PASS

- [ ] **Step 3: 实现**

`src/toolbook/llm.py` contextualize_query 的 prompt 首行改为：

```python
    prompt = (f"提问背景（论文摘要与对话历史，仅供理解问题）：\n{paper_context[:1500]}\n\n用户问题：{question}\n"
              "请把问题改写为适合在教材资源库中检索的关键词（中英混合、空格分隔），"
              "结合背景补全指代与省略，突出基础知识点术语，直接输出关键词串，不要解释。")
```

`src/toolbook/answering.py` generate_draft 签名与背景段改为：

```python
def generate_draft(question: str, hits: list, paper_context: str = "",
                   history_context: str = "") -> list[dict]:
    """生成答案草稿 [{"text","type","ref"}]：excerpt 须一字不差摘抄，summary 须有依据。

    paper_context/history_context 只帮助理解问题（指代/追问），不作为答案依据。
    资料不足、调用失败或格式异常都返回空列表（由编排层触发重检索/拒答）。
    """
    if not hits:
        return []
    # 编号资料块：每块带完整出处，供 LLM 标引用
    sources = [f"[{i}] 《{h.doc_title}》{h.number} {h.title}（{h.locator}）\n{h.text[:1200]}"
               for i, h in enumerate(hits)]
    # 背景段：论文与对话历史都明确仅供理解问题，答案依据只能是编号资料
    bg = ""
    if paper_context:
        bg += f"提问背景（用户正在阅读的论文，仅供理解问题，不作为答案依据）：\n{paper_context[:800]}\n\n"
    if history_context:
        bg += f"对话历史（仅供理解当前问题的指代与追问，不作为答案依据）：\n{history_context[:1200]}\n\n"
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

`src/toolbook/agent.py`：AgentState 加 `history_context: str`；generate_node 改为：

```python
def generate_node(state: AgentState) -> dict:
    """生成节点：LLM 基于检索父块写逐句带引用的草稿（可带论文与对话历史背景）。"""
    return {"draft": generate_draft(state["question"], state["hits"],
                                    state.get("paper_context", ""),
                                    state.get("history_context", ""))}
```

ask 改为：

```python
def ask(question: str, db_path=config.DEFAULT_DB, use_rerank: bool = True,
        paper=None, history_context: str = "") -> AnswerResult:
    """问答主入口（模块A/B 共用）：paper/history_context 提供背景时先做上下文化改写。"""
    ctx_parts = []
    if paper is not None:
        ctx_parts.append(paper.context())
    if history_context:
        ctx_parts.append(history_context)
    background = "\n\n".join(ctx_parts)
    query = llm.contextualize_query(question, background) if background else question
    graph = build_graph()
    final = graph.invoke({"question": question, "query": query,
                          "paper_context": paper.context() if paper is not None else "",
                          "history_context": history_context,
                          "db_path": db_path, "use_rerank": use_rerank,
                          "retries": 0, "searched": []})
    return final["result"]
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest -q`
Expected: 86 passed（79 + session 5 + llm 1 + answering 1 + agent 1 = 87？按实际计数核对：79+5+1+1+1=87）

- [ ] **Step 5: 提交**

```bash
git add src/toolbook/llm.py src/toolbook/answering.py src/toolbook/agent.py tests/test_answering.py tests/test_agent.py
git commit -m "feat: 对话历史注入查询改写与答案生成（仅供理解问题不作答案依据）"
```

---

### Task 3: UI 记忆接线（模块A 5轮 / 模块B 按论文独立+压缩+清空按钮）

**Files:**
- Modify: `app.py`（import Conversation；answer_gist；chat_block 加 conv 参数；两个页签接记忆与清空按钮；模块B 聊天记录按论文名键控）
- Test: 离线回归 + T4 浏览器验证

**Interfaces:**
- Consumes: T1 Conversation、T2 ask(history_context=...)
- Produces: UI 行为——模块A 自动记最近 5 轮；模块B 每篇论文独立记忆与聊天记录，超 6 轮自动压缩；"清空对话"按钮。

- [ ] **Step 1: 改 app.py**

import 区加：

```python
from toolbook.session import Conversation
```

render_answer 后加：

```python
def answer_gist(r: AnswerResult) -> str:
    """把一条答案压成记忆要点：核验句拼接；拒答记拒答原因。"""
    if r.refused:
        return r.message
    return "\n".join(s.text for s in r.sentences)[:400]
```

chat_block 改为：

```python
def chat_block(key: str, paper=None, conv=None):
    """通用问答区：历史消息 + 输入框 + spinner 跑 ask()；key 区分会话，conv 为上下文记忆。"""
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
            r = ask(prompt, use_rerank=st.session_state.get("use_rerank", True),
                    paper=paper, history_context=conv.context() if conv else "")
        render_answer(r)
    st.session_state[hist_key].append(("assistant", r))
    # 答完记一轮记忆（下一问的指代/追问靠它补全）
    if conv is not None:
        conv.add(prompt, answer_gist(r))
```

模块A 页签改为：

```python
with tab_a:
    st.caption("答案只返回核验通过的内容：机械✓=原文摘录子串匹配，LLM✓=逐句裁判+原文双锚定。上下文记忆：自动保留最近 5 轮。")
    conv_a = st.session_state.setdefault("conv_a", Conversation(max_turns=5))
    if st.button("清空对话", key="clear_a"):
        conv_a.clear()
        st.session_state["messages_a"] = []
        st.rerun()
    chat_block("a", conv=conv_a)
```

模块B 页签 `chat_block("b", paper=paper)` 一行替换为：

```python
        # 每篇论文独立记忆与聊天记录：换论文不串上下文，新论文从空开始
        convs = st.session_state.setdefault("convs_b", {})
        conv = convs.setdefault(st.session_state["paper_name"],
                                Conversation(max_turns=6, compress_threshold=6, keep_recent=3))
        st.caption("每篇论文的对话记忆独立；超过 6 轮自动压缩旧轮；换论文不串上下文。")
        if st.button("清空本论文对话", key="clear_b"):
            conv.clear()
            st.session_state[f"messages_b_{st.session_state['paper_name']}"] = []
            st.rerun()
        chat_block(f"b_{st.session_state['paper_name']}", paper=paper, conv=conv)
```

- [ ] **Step 2: 全量回归**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest -q`
Expected: 87 passed

- [ ] **Step 3: 提交**

```bash
git add app.py
git commit -m "feat: UI 上下文记忆（模块A五轮/模块B按论文独立+自动压缩+清空按钮）"
```

---

### Task 4: 浏览器抽检 6 例 + 换论文隔离验证 + 留存问答记录

**Files:**
- Create: `docs/问答抽检-M4.md`（问答全文 + 徽章 + 出处 + 正确性判定 + 记忆行为观察，供用户检查）
- 数据: `data/papers/mini_switch_test.pdf`（pymupdf 现造，gitignore 不提交）

**Interfaces:**
- Consumes: T3 UI；CORE 论文 data/papers/CORE_TWC_09101709.pdf
- Produces: 抽检记录文档；记忆功能实证。

**例题设计（论文依据 → 期望库内出处）：**
- A1「奈奎斯特采样定理说了什么？」→ 3.1（fs>2B + 抗混叠）
- A2「那复基带情形呢？」（追问，靠记忆补全"采样率"）→ 3.1 复基带句（带宽 B、采样率略大于 B）
- B1「论文中目标运动引入多普勒频移；书里相位、频率与速度是什么关系？」（论文 p3 运动 observable/ν）→ 2.3
- B2「论文用时间平均估计接收协方差矩阵 Ry；书里最小二乘估计的几何解释是什么？」（论文 p4 协方差平均）→ 5.2
- B3「论文的协方差参数化接收机属于用先验的统计估计；书里 LMMSE 信道估计的原理是什么？」（论文 p4 Ry 模型）→ 7.4
- B4「那它的先验协方差失配会怎样？」（追问，靠记忆补全 LMMSE）→ 7.4 失配句（"协方差失配时优势可能消失…"）

- [ ] **Step 1: 造迷你论文并重启服务**

Run:
```bash
PYTHONIOENCODING=utf-8 uv run --no-sync python -c "
import pymupdf
doc = pymupdf.open()
p = doc.new_page()
p.insert_text((72, 80), 'Switch Test Paper', fontsize=18)
p.insert_text((72, 120), 'Abstract—A minimal paper for switch isolation test.', fontsize=9)
doc.set_toc([[1, 'I. Introduction', 1]])
doc.save('data/papers/mini_switch_test.pdf')
"
```
重启 streamlit 后台服务（先 TaskStop 旧实例再 `uv run --no-sync streamlit run app.py --server.headless true --server.port 8501`）。

- [ ] **Step 2: 模块A 两轮链（browser-use）**

打开 http://localhost:8501 → 模块A 输入 A1 → 等答案（wait_for 超时就直接 take_snapshot 看无障碍树）→ 记录 sentences/徽章/出处 → 输入 A2 → 记录。**判定**：A2 答案须含复基带采样率内容且出处含 3.1；若答非所问（记忆失效）记 FAIL 并分析。

- [ ] **Step 3: 模块B 四问（上传 CORE）**

论文页签上传 CORE → 依次 B1、B2、B3、B4 → 每问记录全文。**判定**：B1→2.3、B2→5.2、B3→7.4、B4 含失配句且出处 7.4。

- [ ] **Step 4: 换论文隔离验证**

上传 mini_switch_test.pdf → 确认聊天区为空（无 CORE 的四问）、标题为 Switch Test Paper → 再上传回 CORE → 确认四问历史恢复（每篇论文记忆独立保留）。截图留档。

- [ ] **Step 5: 写抽检记录文档**

`docs/问答抽检-M4.md`：逐问记录【问题】【答案全文（含徽章与引用角标）】【出处目录】【正确性判定：PASS/FAIL + 一句理由】【记忆行为观察】；末尾汇总表 + 换论文隔离结论 + 抽检时间。答案文本从浏览器无障碍树逐字抄录。

- [ ] **Step 6: 提交**

```bash
git add docs/问答抽检-M4.md
git commit -m "docs: M4 上下文记忆抽检记录（6 例问答全文+正确性判定，供检查）"
```

---

### Task 5: 收尾（记忆 + 计划书 v0.8 + push）

**Files:**
- Modify: `项目计划书.md`（v0.8 + 状态行追加上下文记忆与抽检结论）
- Modify: 项目记忆 project-requirements-and-stack.md

- [ ] **Step 1: 更新记忆与计划书**（记忆追加：session.py 参数、UI 键控方式、抽检结论与文档路径；计划书版本/状态行更新，M4 行验收补充"上下文记忆+6 例抽检"）
- [ ] **Step 2: 最终回归 + 提交 + push**

Run: `PYTHONIOENCODING=utf-8 uv run --no-sync pytest -q` → 87 passed
```bash
git add 项目计划书.md
git commit -m "docs: 计划书 v0.8（上下文记忆与问答抽检完成）"
git push origin master
```
push 失败重试一次后延后告知用户。

---

## Self-Review 结论

1. **Spec 覆盖**：模块A 5 轮 = T1 max_turns=5 + T3 conv_a；模块B 每篇论文记忆 = T3 convs_b 按 paper_name 键控 + 聊天记录同键；自动压缩 = T1 compress_threshold=6；不同论文清空上下文 = 键控隔离（新论文空记忆）；抽检留存 = T4 文档。
2. **占位符扫描**：无 TBD/TODO；代码步骤均含完整代码。
3. **类型一致性**：Conversation/add/context/clear、summarize_turns、generate_draft 四参、ask 五参在 T1–T3 与测试间一致；test_agent 旧 fixture 与 fake_gen 签名已在 T2 Step 1 同步改四参。