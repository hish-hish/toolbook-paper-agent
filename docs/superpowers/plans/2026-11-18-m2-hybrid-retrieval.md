# M2 混合检索实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M1 导入管道之上实现"BM25 + 向量 + RRF 混合检索 + 本地重排 + 章节号直查 + LLM 双语查询改写"，关键词与语义两类查询均返回正确章节号与出处。

**Architecture:** 检索双路并行：BM25 路（jieba 分词 + rank_bm25，内存索引，LLM 改写出中英关键词各查一次）与向量路（硅基流动 bge-m3 → Chroma 持久化近邻）；RRF（k=60）按名次融合 → 子块映射父块去重 → bge-reranker-v2-m3 本地精排（默认 CPU，可关/可降级）→ top-5 带出处章节。章节号直查走 SQLite 旁路（M1 已有 get_section）。所有云端调用集中在 llm.py，密钥从 .env/环境变量读取。

**Tech Stack:** chromadb、rank-bm25、jieba、openai（硅基流动兼容接口）、sentence-transformers（CrossEncoder，CPU torch）；pytest 离线单测（monkeypatch 假向量/假 LLM），真实 API 验收走 demo 脚本。

**Spec:** `项目计划书.md` v0.4 第 4 节 M2 行 + `docs/决策点详解/D07/D08/D09/D10`。

## Global Constraints

- D7/D8/D9/D10 已定案不得重选：BM25+向量+RRF；硅基流动 BAAI/bge-m3（base_url=https://api.siliconflow.cn/v1）；Chroma 嵌入式；bge-reranker-v2-m3 本地（可退 CPU）。
- 对话模型默认 `deepseek-ai/DeepSeek-V3.2`（已核实平台可用），配置可换。
- 密钥只从环境变量 SILICONFLOW_API_KEY 或项目根 .env 读取；绝不写入代码/提交入库。
- 不引入服务型组件；Chroma 用 PersistentClient（data/chroma/，gitignore 已覆盖 data/）。
- 显存调度：reranker 默认 CPU（D10 方案B），与 MinerU 零冲突；设备可配 TOOLBOOK_RERANK_DEVICE。
- 断网降级：无密钥/网络失败时查询改写回退原问题；reranker 加载失败回退 RRF 序（接口不变）。
- **zh-code-style 规范**：所有新建/修改 .py 文件开头中文功能说明，每个函数/功能块中文注释；回复中展示代码注明文件路径与行号。
- 离线可测：单测不依赖真实 API（monkeypatch）；真实 API 验收由 scripts/demo_m2.py 完成。
- 每任务结束 commit；push 到 origin/master（已建仓库 hish-hish/toolbook-paper-agent）。
- M2 验收：关键词与语义两类查询均返回正确章节号（在 ISAC 教材上人工核对）。

## 文件结构

```
pyproject.toml                       +chromadb rank-bm25 jieba openai sentence-transformers
src/toolbook/config.py               修改：+模型/路径常量、load_api_key()、RERANK_DEVICE
src/toolbook/llm.py                  新建：硅基流动客户端（embed_texts/chat/rewrite_query）
src/toolbook/bm25_index.py           新建：jieba 分词 + BM25Okapi 内存索引
src/toolbook/vector_index.py         新建：Chroma 建索引/近邻查询
src/toolbook/rerank.py               新建：本地 CrossEncoder 重排（懒加载、可降级）
src/toolbook/retrieval.py            新建：rrf_fuse + hybrid_search + SearchHit
src/toolbook/cli.py                  修改：+index/search 子命令（补中文注释）
scripts/demo_m2.py                   新建：真实 API 检索演示与验收
tests/test_llm.py                    新建：改写 JSON 解析/降级（离线）
tests/test_bm25.py                   新建：分词与关键词命中（离线）
tests/test_vector_index.py           新建：假向量建索引/查询（离线）
tests/test_retrieval.py              新建：RRF/父块去重/端到端（离线假向量）
```

统一数据流：`hybrid_search(question) → [SearchHit(doc_id, section_id, number, title, source, locator, text, score, matched_by, doc_title)]`。

---

### Task 1: 依赖 + 配置 + 硅基流动客户端 llm.py（TDD）

**Files:**
- Modify: `pyproject.toml`（uv add）、`src/toolbook/config.py`
- Create: `src/toolbook/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `config.load_api_key() -> str`；常量 `SILICONFLOW_BASE_URL`、`EMBED_MODEL="BAAI/bge-m3"`、`CHAT_MODEL="deepseek-ai/DeepSeek-V3.2"`、`RERANK_MODEL="BAAI/bge-reranker-v2-m3"`、`RERANK_DEVICE`、`CHROMA_DIR`
  - `llm.embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]`
  - `llm.chat(prompt: str, system: str = "", model: str | None = None) -> str`
  - `llm.rewrite_query(question: str) -> dict`（{"zh": str, "en": str}，失败回退 {"zh": 原问题, "en": ""}）

- [ ] **Step 1: 安装依赖（sentence-transformers 后台装，限时）**

Run: `uv add chromadb rank-bm25 jieba openai`
后台 Run: `uv add sentence-transformers`（torch CPU 轮子较大；失败/超时不阻塞后续任务，Task 5 再处理）

- [ ] **Step 2: 写失败测试**

```python
# tests/test_llm.py
"""llm 模块离线单测：查询改写的 JSON 解析与失败降级，不触网。"""
import toolbook.llm as llm


def test_rewrite_parses_json_in_markdown(monkeypatch):
    # 模拟 LLM 返回包裹在 markdown 代码块里的 JSON
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '```json\n{"zh": "采样 定理", "en": "sampling theorem"}\n```')
    kw = llm.rewrite_query("什么是采样定理")
    assert kw == {"zh": "采样 定理", "en": "sampling theorem"}


def test_rewrite_fallback_on_error(monkeypatch):
    # 模拟网络/密钥故障：改写必须回退为原问题，绝不抛异常中断检索
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(llm, "chat", boom)
    kw = llm.rewrite_query("什么是采样定理")
    assert kw == {"zh": "什么是采样定理", "en": ""}


def test_embed_texts_batches(monkeypatch):
    # 模拟 embedding 接口：验证分批调用且结果按输入顺序拼接
    calls = []

    class FakeEmbeddings:
        def create(self, model, input):
            calls.append(len(input))
            return type("R", (), {"data": [type("D", (), {"embedding": [float(len(t))]})() for t in input]})()

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(llm, "get_client", lambda: FakeClient())
    vecs = llm.embed_texts(["a", "bb", "ccc", "dddd", "eeeee"], batch_size=2)
    assert calls == [2, 2, 1]
    assert [v[0] for v in vecs] == [1.0, 2.0, 3.0, 4.0, 5.0]
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_llm.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 扩展 config.py（补文件级中文说明）**

在 `src/toolbook/config.py` 追加（保留原有 PROJECT_ROOT/DATA_DIR/DEFAULT_DB）：

```python
"""全局配置：数据目录、数据库路径、硅基流动模型与密钥读取、重排设备。"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "library.db"
CHROMA_DIR = DATA_DIR / "chroma"

# 硅基流动 OpenAI 兼容接口与模型（D2/D8/D10 定案）
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
EMBED_MODEL = "BAAI/bge-m3"
CHAT_MODEL = "deepseek-ai/DeepSeek-V3.2"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
# 重排默认 CPU（D10 方案B），避免与 MinerU 争显存；可设 cuda
RERANK_DEVICE = os.environ.get("TOOLBOOK_RERANK_DEVICE", "cpu")


def load_api_key() -> str:
    """读取硅基流动密钥：优先环境变量，其次项目根 .env 文件；都没有返回空串。"""
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if key:
        return key
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SILICONFLOW_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""
```

- [ ] **Step 5: 实现 llm.py**

```python
"""硅基流动云端客户端：bge-m3 批量向量化、DeepSeek/Qwen 对话、双语查询改写。

全项目唯一的云端出口；密钥经 config.load_api_key() 从 .env/环境变量读取。
"""
import json
import re

from openai import OpenAI

from . import config

_client = None


def get_client() -> OpenAI:
    """懒加载 OpenAI 兼容客户端（指向硅基流动）；无密钥时抛出带指引的异常。"""
    global _client
    if _client is None:
        key = config.load_api_key()
        if not key:
            raise RuntimeError("未配置 SILICONFLOW_API_KEY：请在项目根 .env 填入硅基流动密钥")
        _client = OpenAI(api_key=key, base_url=config.SILICONFLOW_BASE_URL)
    return _client


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """批量向量化（bge-m3，1024 维），按 batch_size 分批，结果与输入同序。"""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        resp = get_client().embeddings.create(
            model=config.EMBED_MODEL, input=texts[i:i + batch_size])
        out.extend(d.embedding for d in resp.data)
    return out


def chat(prompt: str, system: str = "", model: str | None = None) -> str:
    """单轮对话调用（查询改写/后续核验共用），temperature=0 保证可复现。"""
    msgs = ([{"role": "system", "content": system}] if system else [])
    msgs.append({"role": "user", "content": prompt})
    resp = get_client().chat.completions.create(
        model=model or config.CHAT_MODEL, messages=msgs, temperature=0)
    return resp.choices[0].message.content or ""


def rewrite_query(question: str) -> dict:
    """LLM 把问题改写为中英双语关键词（BM25 跨语言用）；任何失败回退原问题。"""
    system = "你是检索查询改写器。把用户问题改写为适合关键词检索的中英双语关键词，只输出JSON，不要解释。"
    prompt = (f"问题：{question}\n"
              '输出格式：{"zh": "中文关键词 空格分隔", "en": "english keywords space separated"}')
    try:
        raw = chat(prompt, system)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        return {"zh": str(d.get("zh", "")), "en": str(d.get("en", ""))}
    except Exception:
        # 断网/无密钥/格式异常都不阻断检索：回退原问题
        return {"zh": question, "en": ""}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_llm.py -v`
Expected: 3 passed

- [ ] **Step 7: 真实 API 冒烟（人工验证）**

Run: `uv run --no-sync python -c "from toolbook.llm import embed_texts, rewrite_query; print(len(embed_texts(['测试'])[0])); print(rewrite_query('什么是奈奎斯特采样定理'))"`
Expected: 1024；改写返回中英关键词（需 .env 密钥已填）。

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/toolbook/config.py src/toolbook/llm.py tests/test_llm.py
git commit -m "feat: SiliconFlow client (bge-m3 embeddings, chat, bilingual query rewrite)"
```

---

### Task 2: BM25 关键词索引 bm25_index.py（TDD）

**Files:**
- Create: `src/toolbook/bm25_index.py`, `tests/test_bm25.py`

**Interfaces:**
- Consumes: `LibraryStore`（M1）
- Produces: `tokenize(text: str) -> list[str]`；`BM25Index(store)`（属性 `chunk_ids: list[int]`、`section_ids: list[int]`）；`BM25Index.search(query: str, top_k: int = 30) -> list[tuple[int, float]]`（chunk_id, score，降序，零分不返回）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_bm25.py
"""BM25 索引离线单测：中英分词与关键词精确命中。"""
import pytest

from toolbook.bm25_index import BM25Index, tokenize
from toolbook.store import LibraryStore


def test_tokenize_mixed():
    tokens = tokenize("傅里叶变换 Fourier Transform 3.2")
    assert "傅里叶" in tokens or "傅里叶变换" in tokens
    assert "fourier" in tokens
    assert "transform" in tokens


@pytest.fixture
def store(tmp_path):
    s = LibraryStore(tmp_path / "t.db")
    with s.transaction():
        doc_id = s.add_document("书", "docx", "h", "x.docx")
        sid1 = s.insert_section(doc_id, None, "2.1", "傅里叶变换", 2, "original", "p1", 1, "傅里叶变换把信号分解为不同频率的正弦分量。")
        sid2 = s.insert_section(doc_id, None, "2.2", "采样定理", 2, "original", "p2", 1, "采样定理给出从离散样本无失真恢复连续信号的条件。")
        s.insert_chunks(sid1, ["傅里叶变换把信号分解为不同频率的正弦分量。"])
        s.insert_chunks(sid2, ["采样定理给出从离散样本无失真恢复连续信号的条件。"])
    yield s
    s.close()


def test_bm25_exact_term_hits_right_chunk(store):
    idx = BM25Index(store)
    hits = idx.search("傅里叶变换")
    assert hits and hits[0][0] == idx.chunk_ids[0]
    assert hits[0][1] > 0


def test_bm25_empty_query(store):
    assert BM25Index(store).search("") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_bm25.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 bm25_index.py**

```python
"""BM25 关键词检索索引：jieba 中英分词 + rank_bm25 打分。

从 SQLite chunks 表在内存构建（3 本书规模毫秒级），进程重启自动重建，无需持久化。
"""
import re

import jieba
from rank_bm25 import BM25Okapi

from .store import LibraryStore


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文转小写，jieba 切分，丢弃纯标点/空白 token。"""
    return [t for t in jieba.lcut(text.lower())
            if re.search(r"[\w\u4e00-\u9fff]", t)]


class BM25Index:
    """以子块为单位的 BM25Okapi 索引；chunk_ids/section_ids 与语料同序。"""

    def __init__(self, store: LibraryStore):
        rows = store.conn.execute(
            "SELECT chunk_id, section_id, text FROM chunks ORDER BY chunk_id").fetchall()
        self.chunk_ids = [r["chunk_id"] for r in rows]
        self.section_ids = [r["section_id"] for r in rows]
        corpus = [tokenize(r["text"]) for r in rows]
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, top_k: int = 30) -> list[tuple[int, float]]:
        """关键词检索：返回 [(chunk_id, BM25分)] 降序，零分与空查询返回空列表。"""
        if self.bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
        return [(self.chunk_ids[i], float(scores[i])) for i in order if scores[i] > 0]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_bm25.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/bm25_index.py tests/test_bm25.py
git commit -m "feat: BM25 keyword index with jieba bilingual tokenization"
```

---

### Task 3: Chroma 向量索引 vector_index.py（TDD，假向量离线测）

**Files:**
- Create: `src/toolbook/vector_index.py`, `tests/test_vector_index.py`

**Interfaces:**
- Consumes: `llm.embed_texts`、`LibraryStore`、`config.CHROMA_DIR`
- Produces:
  - `build_vector_index(db_path=DEFAULT_DB, force: bool = False) -> int`（全量重建；数量一致且非 force 时跳过；返回向量数）
  - `vector_search(question: str, top_k: int = 30, doc_id: int | None = None) -> list[tuple[int, float]]`（chunk_id, 余弦相似度，降序）
  - `get_collection()`（chroma Collection，embedding_function=None，cosine 空间）
  - 元数据字段：section_id/doc_id/number/title/source/locator（int/str）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_vector_index.py
"""向量索引离线单测：用确定性假向量验证建索引/查询/幂等，不触网。"""
import pytest

import toolbook.vector_index as vi
from toolbook.store import LibraryStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    # 隔离 Chroma 目录与 embedding：假向量 = [文本长度, 1.0]
    monkeypatch.setattr(vi.config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(vi, "embed_texts", lambda texts, **k: [[float(len(t)), 1.0] for t in texts])
    db = tmp_path / "lib.db"
    s = LibraryStore(db)
    with s.transaction():
        doc_id = s.add_document("书", "docx", "h", "x.docx")
        sid = s.insert_section(doc_id, None, "1.1", "节", 2, "original", "p1", 1, "正文")
        s.insert_chunks(sid, ["短块", "这是一个比较长的子块文本"])
    s.close()
    return db


def test_build_and_count(env):
    assert vi.build_vector_index(env) == 2
    # 幂等：数量一致时跳过重建
    assert vi.build_vector_index(env) == 2


def test_force_rebuild(env):
    vi.build_vector_index(env)
    assert vi.build_vector_index(env, force=True) == 2


def test_vector_search_returns_chunk_ids(env):
    vi.build_vector_index(env)
    hits = vi.vector_search("短块", top_k=2)
    assert len(hits) == 2
    assert hits[0][0] == 1  # 与"短块"等长的假向量最近
    assert hits[0][1] >= hits[1][1]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_vector_index.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 vector_index.py**

```python
"""Chroma 向量索引：把 SQLite 子块批量向量化后持久化，查询时近邻搜索。

向量随 Chroma 落盘（data/chroma/），导入后建一次即可离线复用（查询仍需联网向量化问题）。
"""
import chromadb

from . import config
from .llm import embed_texts
from .store import LibraryStore

COLLECTION = "toolbook_chunks"


def get_collection():
    """打开持久化集合（cosine 空间）；显式关闭 chroma 默认 embedding 模型下载。"""
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    return client.get_or_create_collection(
        COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"})


def build_vector_index(db_path=config.DEFAULT_DB, force: bool = False) -> int:
    """全量重建向量索引；子块数与库中一致且非 force 时跳过。返回向量条数。"""
    store = LibraryStore(db_path)
    rows = store.conn.execute(
        "SELECT c.chunk_id, c.section_id, c.text, s.doc_id, s.number, s.title, s.source, s.locator "
        "FROM chunks c JOIN sections s ON c.section_id = s.section_id ORDER BY c.chunk_id").fetchall()
    store.close()
    col = get_collection()
    if not force and col.count() == len(rows):
        return col.count()
    # 清空旧向量，避免删除/重导后残留
    existing = col.get()["ids"]
    if existing:
        col.delete(ids=existing)
    if not rows:
        return 0
    vecs = embed_texts([r["text"] for r in rows])
    for i in range(0, len(rows), 256):
        batch = rows[i:i + 256]
        col.add(
            ids=[str(r["chunk_id"]) for r in batch],
            embeddings=vecs[i:i + 256],
            documents=[r["text"] for r in batch],
            metadatas=[{"section_id": r["section_id"], "doc_id": r["doc_id"],
                        "number": r["number"], "title": r["title"],
                        "source": r["source"], "locator": r["locator"]} for r in batch])
    return col.count()


def vector_search(question: str, top_k: int = 30, doc_id: int | None = None) -> list[tuple[int, float]]:
    """问题向量化 → Chroma 近邻；返回 [(chunk_id, 余弦相似度)] 降序。"""
    col = get_collection()
    if col.count() == 0:
        return []
    qv = embed_texts([question])[0]
    where = {"doc_id": doc_id} if doc_id is not None else None
    res = col.query(query_embeddings=[qv], n_results=min(top_k, col.count()), where=where)
    # cosine 空间下 distance = 1 - 相似度，换算回相似度便于阅读
    return [(int(cid), 1.0 - dist) for cid, dist in zip(res["ids"][0], res["distances"][0])]
```

注意：若 chromadb 版本对 `embedding_function=None` 报错，改用其文档规定的"无 embedding 函数"写法（如 `chromadb.api.types.EmbeddingFunction` 空实现），以实际安装版本为准，但禁止触发默认模型下载。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_vector_index.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/vector_index.py tests/test_vector_index.py
git commit -m "feat: persistent Chroma vector index with batch embedding build"
```

---

### Task 4: 混合检索 retrieval.py（TDD，离线端到端）

**Files:**
- Create: `src/toolbook/retrieval.py`, `tests/test_retrieval.py`

**Interfaces:**
- Consumes: `BM25Index`、`vector_search`、`rewrite_query`、`LibraryStore`、`rerank.rerank_scores`（Task 5 提供；本任务先以 `use_rerank=False` 测试，导入放函数内延迟引用）
- Produces:
  - `SearchHit` dataclass：`doc_id, section_id, number, title, source, locator, text, score, matched_by, doc_title`
  - `rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]`
  - `hybrid_search(question: str, db_path=DEFAULT_DB, top_k: int = 5, use_llm: bool = True, use_rerank: bool = True, doc_id: int | None = None) -> list[SearchHit]`

流程：改写 → BM25 三查询（原问题/中文关键词/英文关键词）+ 向量一路 → RRF 融合 top30 子块 → 映射父块去重（保留最佳名次，记录 matched_by）→ 取父块全文（多 part 拼接）→ rerank（可降级）→ top_k。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_retrieval.py
"""混合检索离线单测：RRF 融合、父块去重、端到端（假向量+真 BM25）。"""
import pytest

import toolbook.retrieval as rt
from toolbook.importer import import_file


def test_rrf_fuse_orders_by_both_lists():
    # a 在两路都靠前应排第一；只出现在单路的靠后
    fused = rt.rrf_fuse([[1, 2, 3], [2, 1, 4]])
    ids = [cid for cid, _ in fused]
    assert set(ids) == {1, 2, 3, 4}
    assert ids[0] in (1, 2)
    assert ids.index(4) > ids.index(3) or 3 not in ids[:2]


def test_rrf_single_list():
    fused = rt.rrf_fuse([[7, 8]])
    assert [cid for cid, _ in fused] == [7, 8]
    assert fused[0][1] == pytest.approx(1 / 61)


@pytest.fixture
def library(tmp_path, monkeypatch):
    # 两节文档：2.1 讲傅里叶、2.2 讲采样；假向量让"恢复信号"偏向 2.2
    from docx import Document
    d = Document()
    d.add_heading("第2章 傅里叶分析", level=1)
    d.add_heading("2.1 傅里叶变换", level=2)
    d.add_paragraph("傅里叶变换把时域信号分解为不同频率的正弦分量，是频域分析的核心工具。")
    d.add_heading("2.2 采样定理", level=2)
    d.add_paragraph("采样定理给出从离散样本无失真恢复连续信号的条件：采样频率必须大于最高频率两倍。")
    p = tmp_path / "b.docx"
    d.save(str(p))
    db = tmp_path / "lib.db"
    import_file(p, db)
    monkeypatch.setattr(rt, "vector_search",
                        lambda q, top_k=30, doc_id=None: [(2, 0.9), (1, 0.5)])
    return db


def test_hybrid_keyword_query(library):
    hits = rt.hybrid_search("傅里叶变换", db_path=library, use_llm=False, use_rerank=False)
    assert hits and hits[0].number == "2.1"
    assert hits[0].source == "original"
    assert hits[0].locator.startswith("p")
    assert "频域分析" in hits[0].text


def test_hybrid_semantic_query(library):
    hits = rt.hybrid_search("怎样从离散样本恢复连续信号", db_path=library, use_llm=False, use_rerank=False)
    assert hits and hits[0].number == "2.2"


def test_parent_dedup(library):
    hits = rt.hybrid_search("傅里叶 采样 信号", db_path=library, use_llm=False, use_rerank=False, top_k=10)
    section_ids = [h.section_id for h in hits]
    assert len(section_ids) == len(set(section_ids))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_retrieval.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 retrieval.py**

```python
"""混合检索编排：查询改写 → BM25+向量双路 → RRF 融合 → 父块去重 → 重排 → 带出处章节。

检索命中子块，返回所属父块（整个小节），出处沿 Chunk→Section→Document 回溯（D6/D7）。
"""
from dataclasses import dataclass

from . import config
from .bm25_index import BM25Index
from .llm import rewrite_query
from .store import LibraryStore
from .vector_index import vector_search


@dataclass
class SearchHit:
    """一条检索结果：父块全文 + 完整出处 + 命中方式。"""
    doc_id: int
    section_id: int
    number: str
    title: str
    source: str
    locator: str
    text: str
    score: float
    matched_by: str  # "bm25" / "vector" / "both"
    doc_title: str = ""


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """RRF 倒数排名融合：只看名次不看原始分，score = Σ 1/(k+rank)。"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


def hybrid_search(question: str, db_path=config.DEFAULT_DB, top_k: int = 5,
                  use_llm: bool = True, use_rerank: bool = True,
                  doc_id: int | None = None) -> list[SearchHit]:
    """混合检索主入口：返回 top_k 个父块（小节），含出处与命中方式。"""
    store = LibraryStore(db_path)
    try:
        bm25 = BM25Index(store)
        # 1) 查询改写（断网自动回退原问题）
        kw = rewrite_query(question) if use_llm else {"zh": question, "en": ""}
        # 2) BM25 路：原问题 + 中文关键词 + 英文关键词各查一次
        bm25_rankings, bm25_ids = [], set()
        for q in (question, kw["zh"], kw["en"]):
            if q.strip():
                ranking = [cid for cid, _ in bm25.search(q, 30)]
                bm25_rankings.append(ranking)
                bm25_ids.update(ranking)
        # 3) 向量路：原问题语义检索
        vec_ranking = [cid for cid, _ in vector_search(question, 30, doc_id)]
        # 4) RRF 融合
        fused = rrf_fuse(bm25_rankings + [vec_ranking])
        # 5) 子块 → 父块映射与去重（保留最佳名次）
        chunk_map = {r["chunk_id"]: r["section_id"] for r in store.conn.execute(
            "SELECT chunk_id, section_id FROM chunks")}
        sec_rows = {r["section_id"]: r for r in store.conn.execute(
            "SELECT s.*, d.title AS doc_title FROM sections s JOIN documents d ON s.doc_id=d.doc_id")}
        best: dict[int, tuple[float, str]] = {}
        for cid, score in fused:
            sid = chunk_map.get(cid)
            if sid is None:
                continue
            row = sec_rows[sid]
            if doc_id is not None and row["doc_id"] != doc_id:
                continue
            matched = "both" if cid in bm25_ids and cid in set(vec_ranking) else (
                "bm25" if cid in bm25_ids else "vector")
            if sid not in best:
                best[sid] = (score, matched)
            if len(best) >= 30:
                break
        # 6) 组装父块全文（多 part 拼接）
        hits: list[SearchHit] = []
        for sid, (score, matched) in best.items():
            row = sec_rows[sid]
            parts = store.get_section(row["doc_id"], row["number"])
            text = "\n".join(p["text"] for p in parts if p["title"] == row["title"])
            hits.append(SearchHit(row["doc_id"], sid, row["number"], row["title"],
                                  row["source"], row["locator"], text, score,
                                  matched, row["doc_title"]))
        # 7) 本地重排（失败自动降级为 RRF 序）
        if use_rerank and hits:
            from .rerank import rerank_scores
            scores = rerank_scores(question, [h.text[:1500] for h in hits])
            if scores is not None:
                hits = [h for _, h in sorted(zip(scores, hits), key=lambda x: -x[0])]
        return hits[:top_k]
    finally:
        store.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_retrieval.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/toolbook/retrieval.py tests/test_retrieval.py
git commit -m "feat: hybrid retrieval (BM25 + vector + RRF + parent dedup)"
```

---

### Task 5: 本地重排 rerank.py（限时安装 + 降级测试）

**Files:**
- Create: `src/toolbook/rerank.py`, `tests/test_rerank.py`
- Modify: 无（retrieval 已延迟引用）

**Interfaces:**
- Produces: `rerank_scores(question: str, texts: list[str]) -> list[float] | None`（模型不可用/被关闭返回 None，调用方回退 RRF 序）。环境变量 `TOOLBOOK_RERANK=off` 关闭；`TOOLBOOK_RERANK_DEVICE` 选设备（默认 cpu）。

- [ ] **Step 1: 写失败测试（只测降级路径，不加载真模型）**

```python
# tests/test_rerank.py
"""重排模块离线单测：开关与加载失败降级，不下载/加载真模型。"""
import toolbook.rerank as rr


def test_rerank_off_switch(monkeypatch):
    monkeypatch.setenv("TOOLBOOK_RERANK", "off")
    assert rr.rerank_scores("问题", ["文本"]) is None


def test_rerank_load_failure_degrades(monkeypatch):
    # 模拟 sentence-transformers 不可用：必须返回 None 而不是抛异常
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "sentence_transformers":
            raise ImportError("no torch")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(rr, "_model", None)
    monkeypatch.setattr(rr, "_failed", False)
    assert rr.rerank_scores("问题", ["文本"]) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --no-sync pytest tests/test_rerank.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 rerank.py**

```python
"""本地重排器：bge-reranker-v2-m3 交叉编码器对 (问题, 候选) 逐对精打分。

默认 CPU（D10 方案B），与 MinerU 零显存冲突；懒加载，加载失败永久降级为 None。
模型下载走 hf-mirror（国内网络），首次约 2GB。
"""
import os

from . import config

_model = None
_failed = False


def rerank_scores(question: str, texts: list[str]) -> list[float] | None:
    """返回每个候选的相关度分；关闭/不可用时返回 None（调用方回退 RRF 序）。"""
    global _model, _failed
    if os.environ.get("TOOLBOOK_RERANK", "").lower() == "off" or _failed:
        return None
    if not texts:
        return []
    if _model is None:
        try:
            # 国内网络优先走 HF 镜像下载模型
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(config.RERANK_MODEL,
                                  device=config.RERANK_DEVICE, max_length=512)
        except Exception:
            _failed = True
            return None
    return [float(s) for s in _model.predict([(question, t) for t in texts])]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --no-sync pytest tests/test_rerank.py -v`
Expected: 2 passed

- [ ] **Step 5: 真模型限时验证（依赖 Task 1 后台安装结果）**

> 执行记录：hf-mirror 下载停滞（64MB 后卡死），改用 ModelScope `snapshot_download('BAAI/bge-reranker-v2-m3', local_dir='data/models/bge-reranker-v2-m3')`；rerank.py 优先从该本地目录离线加载（config.RERANK_MODEL_DIR），不存在时回退 HF 镜像在线加载。

若 sentence-transformers 已装好：
Run: `uv run --no-sync python -c "from toolbook.rerank import rerank_scores; print(rerank_scores('采样定理', ['采样定理给出恢复条件', '傅里叶变换分解频率']))"`
Expected: 两个分数，第一个更高（首次下载模型约 2GB，限时 30 分钟；超时/失败则记录降级，M2 先以 RRF 序交付，rerank 赛后补——符合"砍增强项保主干"）。

- [ ] **Step 6: Commit**

```bash
git add src/toolbook/rerank.py tests/test_rerank.py pyproject.toml uv.lock
git commit -m "feat: local bge-reranker-v2-m3 with graceful degradation (CPU default)"
```

---

### Task 6: CLI 扩展 + M2 演示验收

**Files:**
- Modify: `src/toolbook/cli.py`（+index/search 子命令；补文件级中文说明与新块中文注释）
- Create: `scripts/demo_m2.py`

**Interfaces:**
- Consumes: `build_vector_index`、`hybrid_search`、`LibraryStore.get_section`
- Produces: CLI `python -m toolbook.cli index [--force]`；`search QUESTION [--doc N] [-k N] [--no-llm] [--no-rerank]`；`uv run python scripts/demo_m2.py` 一键演示。

- [ ] **Step 1: 扩展 cli.py**

在现有 argparse 结构中追加（文件开头补中文 docstring """ToolBook 资源库命令行入口：导入、索引、章节树、直查与混合检索。"""）：

```python
    # --- M2 新增：向量索引与混合检索 ---
    p_idx = sub.add_parser("index", help="建立/重建向量索引（调用 bge-m3）")
    p_idx.add_argument("--force", action="store_true", help="强制重建")
    p_search = sub.add_parser("search", help="混合检索（BM25+向量+RRF+重排）")
    p_search.add_argument("question")
    p_search.add_argument("--doc", type=int, default=None, help="限定文档 ID")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument("--no-llm", action="store_true", help="跳过 LLM 查询改写")
    p_search.add_argument("--no-rerank", action="store_true", help="跳过本地重排")
```

main 分支追加：

```python
    if args.cmd == "index":
        from .vector_index import build_vector_index
        n = build_vector_index(args.db, force=args.force)
        print(f"向量索引完成：{n} 条")
        return
    if args.cmd == "search":
        from .retrieval import hybrid_search
        hits = hybrid_search(args.question, args.db, top_k=args.k,
                             use_llm=not args.no_llm, use_rerank=not args.no_rerank,
                             doc_id=args.doc)
        if not hits:
            print("未命中（资源库可能未覆盖该问题）")
            return
        for h in hits:
            badge = "" if h.source == "original" else " [系统编号]"
            print(f"《{h.doc_title}》 {h.number} {h.title}{badge}  <{h.locator}>  "
                  f"score={h.score:.4f} via={h.matched_by}")
            print(f"  {h.text[:150]}...")
        return
```

- [ ] **Step 2: 写 demo_m2.py**

```python
# scripts/demo_m2.py
"""M2 演示：建向量索引 → 关键词/语义/跨语言三类查询 → 章节号直查对照。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.config import DEFAULT_DB
from toolbook.retrieval import hybrid_search
from toolbook.store import LibraryStore
from toolbook.vector_index import build_vector_index

QUERIES = [
    ("关键词", "奈奎斯特 采样 混叠"),
    ("语义", "怎样从离散样本无失真地恢复连续信号"),
    ("跨语言", "What is the Nyquist sampling criterion and aliasing?"),
]


def main():
    n = build_vector_index()
    print(f"向量索引：{n} 条子块")
    for label, q in QUERIES:
        print(f"\n=== [{label}] {q} ===")
        hits = hybrid_search(q, top_k=3)
        for h in hits:
            badge = "" if h.source == "original" else " [系统编号]"
            print(f"  《{h.doc_title}》 {h.number} {h.title}{badge}  <{h.locator}>  "
                  f"score={h.score:.4f} via={h.matched_by}")
    # 章节号直查旁路对照
    store = LibraryStore(DEFAULT_DB)
    docs = store.list_documents()
    if docs:
        rows = store.get_section(docs[0]["doc_id"], "3.1")
        if rows:
            print(f"\n=== 章节号直查 3.1 ===\n  {rows[0]['title']}  <{rows[0]['locator']}>")
    store.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 全量离线回归**

Run: `uv run --no-sync pytest -q`
Expected: 全部 passed（M1 29 + M2 新增约 13）。

- [ ] **Step 4: 真实 API 验收（M2 验收标准）**

Run: `uv run python scripts/demo_m2.py`（首次建索引约 551 块 × bge-m3，几分钟）
Expected: 三类查询均命中 ISAC 教材相关章节（采样相关 → 第3章 3.1 附近；人工核对章节号合理性）；直查 3.1 返回原书标题。
再验 CLI：`uv run python -m toolbook.cli search "卷积 两径信道" --no-rerank`（若 rerank 未就绪）。

- [ ] **Step 5: Commit + push**

```bash
git add src/toolbook/cli.py scripts/demo_m2.py
git commit -m "feat: M2 demo - hybrid search CLI and three-query-type walkthrough"
git push
```

---

### Task 7: 收尾（记忆更新 + 计划书状态）

- [ ] **Step 1: 更新项目记忆**：M2 完成状态、rerank 是否就绪、默认对话模型 DeepSeek-V3.2、索引规模。
- [ ] **Step 2: 更新计划书状态行**（v0.5，M2 完成）。
- [ ] **Step 3: 最终回归 + push**：`uv run --no-sync pytest -q` 全过；`git push`。

## Self-Review 结论

- 规格覆盖：D7 双路+RRF+旁路→Task 2/3/4/6；D8 bge-m3 配置驱动→Task 1；D9 Chroma 元数据→Task 3；D10 本地重排+CPU+降级→Task 5；双语改写→Task 1/4；M2 验收→Task 6。
- 离线可测：全部单测 monkeypatch 假向量/假 LLM，不触网；真实 API 只在冒烟与 demo 步骤。
- 类型一致性：SearchHit 字段、rrf_fuse/hybrid_search/rerank_scores 签名、BM25Index/vector_search 返回 (chunk_id, score) 已跨任务核对。
- 已知留白：embedding 查询缓存与断网演练（M5）、核验（M3）、rerank 若限时失败按止损后置。