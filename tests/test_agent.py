"""LangGraph 编排离线单测：用假检索/假生成/假核验验证三条路径（成功/重试/拒答）。"""
import pytest

import toolbook.agent as ag
from toolbook.models import VerifiedSentence
from toolbook.retrieval import SearchHit


def _hit():
    # 构造最小 SearchHit 供图测试
    return SearchHit(1, 1, "3.1", "采样", "original", "p21", "原文内容", 0.5, "both", "书")


@pytest.fixture
def patch_nodes(monkeypatch):
    # 默认假节点：检索返回 1 个 hit，生成 1 句草稿，替代查询可预测
    monkeypatch.setattr(ag, "hybrid_search", lambda q, **k: [_hit()])
    monkeypatch.setattr(ag, "generate_draft", lambda q, hits, ctx="", hist="": [{"text": "原文内容", "type": "excerpt", "ref": 0}])
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
    # 前两次核验空、第三次通过：retries=2，共尝试 3 个查询
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
    # 检索始终为空：不生成、走重试→拒答
    patch_nodes.setattr(ag, "hybrid_search", lambda q, **k: [])
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [])
    r = ag.ask("超纲问题？")
    assert r.refused


def test_ask_with_paper_contextualizes_query(patch_nodes):
    # 带论文提问：初始查询用上下文化关键词，生成节点收到论文背景
    from toolbook.models import PaperInfo
    seen = {}

    def fake_search(q, **k):
        seen.setdefault("queries", []).append(q)
        return [_hit()]

    def fake_gen(q, hits, ctx="", hist=""):
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

    def fake_search(q, **k):
        seen["q"] = q
        return [_hit()]

    patch_nodes.setattr(ag, "hybrid_search", fake_search)
    patch_nodes.setattr(ag, "verify_draft", lambda draft, hits: [VerifiedSentence("原文内容", "excerpt", 0, "mechanical", "原文内容")])
    r = ag.ask("采样定理？")
    assert not r.refused and seen["q"] == "采样定理？"


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