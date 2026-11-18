"""答案草稿生成离线单测：JSON 解析、资料不足回退、替代查询降级。"""
import toolbook.answering as aw
import toolbook.llm as llm
from toolbook.retrieval import SearchHit


def _hit():
    # 构造最小 SearchHit 供生成测试
    return SearchHit(1, 1, "3.1", "采样", "original", "p21", "采样频率必须大于最高频率的两倍。", 0.5, "both", "书")


def test_generate_draft_parses_sentences(monkeypatch):
    # markdown 包裹的 JSON 应被解析；提示词必须带编号资料与出处
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return '```json\n{"insufficient": false, "sentences": [{"text": "采样频率必须大于最高频率的两倍。", "type": "excerpt", "ref": 0}]}\n```'

    monkeypatch.setattr(aw.llm, "chat", fake_chat)
    draft = aw.generate_draft("采样定理？", [_hit()])
    assert draft[0]["type"] == "excerpt" and draft[0]["ref"] == 0
    assert "[0]" in captured["prompt"] and "3.1" in captured["prompt"]


def test_generate_draft_insufficient(monkeypatch):
    # LLM 判定资料不足：返回空草稿（触发重检索/拒答）
    monkeypatch.setattr(aw.llm, "chat", lambda *a, **k: '{"insufficient": true, "sentences": []}')
    assert aw.generate_draft("超纲问题", [_hit()]) == []


def test_generate_draft_failure_and_empty(monkeypatch):
    # 调用失败或无检索结果：返回空草稿而不是抛异常
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(aw.llm, "chat", boom)
    assert aw.generate_draft("问题", [_hit()]) == []
    assert aw.generate_draft("问题", []) == []


def test_alternative_query_fallback(monkeypatch):
    # 替代查询：失败回退原问题；成功去掉首尾空白
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(llm, "chat", boom)
    assert llm.alternative_query("原问题", ["原问题"]) == "原问题"
    monkeypatch.setattr(llm, "chat", lambda *a, **k: " 新关键词 串 ")
    assert llm.alternative_query("原问题", ["原问题"]) == "新关键词 串"


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