"""学习指引模块离线单测：模型构造、LLM 复核/推荐解析、编号校验与降级，不触网。"""
import toolbook.study as study
from toolbook.models import AnswerResult, StudyGuide, StudySection
from toolbook.retrieval import SearchHit


def test_study_section_defaults():
    # 命中节默认无内容简介；推荐节才填 summary
    s = StudySection("书", "3.1", "采样", "p21", "original")
    assert s.summary == ""


def test_study_guide_defaults():
    # 空学习指引：命中节与推荐节都为空列表
    g = StudyGuide()
    assert g.matched == [] and g.recommended == []


def test_answer_result_has_stats_and_study():
    # AnswerResult 新增统计与学习指引字段，默认空（向后兼容旧构造）
    r = AnswerResult([], [])
    assert r.stats == {} and r.study is None


def _hit(number="3.1", title="采样", doc_id=1, sid=1):
    # 构造最小 SearchHit 供学习指引测试
    return SearchHit(doc_id, sid, number, title, "original", "p21", "原文内容", 0.5, "both", "书")


class _FakeStore:
    # 假资源库：get_tree 返回预设目录行，避免触真实数据库
    rows = []

    def __init__(self, db_path):
        pass

    def get_tree(self, doc_id):
        return self.rows

    def close(self):
        pass


def test_pick_sections_parses(monkeypatch):
    # LLM 复核/推荐 JSON 解析为 keep/recommend 节号列表
    monkeypatch.setattr(study.llm, "chat", lambda *a, **k: '{"keep": ["3.1"], "recommend": ["3.2", "9.9"]}')
    out = study._pick_sections("q", [_hit()], [{"number": "3.1", "title": "采样"}])
    assert out == {"keep": ["3.1"], "recommend": ["3.2", "9.9"]}


def test_pick_sections_fallback_none(monkeypatch):
    # 调用失败返回 None（由上层降级为仅展示命中节）
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(study.llm, "chat", boom)
    assert study._pick_sections("q", [_hit()], []) is None


def test_pick_sections_normalizes_number_echo(monkeypatch):
    # LLM 把"节号+标题"整行回显时，只取节号本身（标题已含节号导致重复）
    monkeypatch.setattr(study.llm, "chat", lambda *a, **k:
                        '{"keep": ["3.1 3.1 采样不等于随意少取一些点"], "recommend": ["3 第三章 采样", "3.2 3.2 两径信道"]}')
    out = study._pick_sections("q", [_hit()], [{"number": "3.1", "title": "3.1 采样"}])
    assert out == {"keep": ["3.1"], "recommend": ["3", "3.2"]}


def test_summarize_sections_parses(monkeypatch):
    # 推荐节内容简介解析为 {节号: 简介}
    monkeypatch.setattr(study.llm, "chat", lambda *a, **k: '{"3.2": "讲混叠"}')
    out = study._summarize_sections("q", [{"number": "3.2", "title": "混叠", "text": "..."}])
    assert out == {"3.2": "讲混叠"}


def test_summarize_sections_fallback_empty(monkeypatch):
    # 简介调用失败返回空字典（推荐节仍展示，只是无简介）
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(study.llm, "chat", boom)
    assert study._summarize_sections("q", []) == {}


def test_build_study_guide_validates_and_summarizes(monkeypatch):
    # 推荐编号校验：编造的 9.9 剔除、已命中的 3.1 排除，仅保留真实且未命中的 3.2 并附简介
    _FakeStore.rows = [
        {"doc_id": 1, "number": "3.1", "title": "采样", "locator": "p21", "source": "original", "text": "采样原文"},
        {"doc_id": 1, "number": "3.2", "title": "混叠", "locator": "p22", "source": "original", "text": "混叠原文"},
        {"doc_id": 1, "number": "5.1", "title": "波形", "locator": "p25", "source": "original", "text": "波形原文"},
    ]
    monkeypatch.setattr(study, "LibraryStore", _FakeStore)
    monkeypatch.setattr(study, "_pick_sections",
                        lambda q, h, c: {"keep": ["3.1"], "recommend": ["3.2", "9.9", "3.1"]})
    monkeypatch.setattr(study, "_summarize_sections", lambda q, secs: {"3.2": "讲混叠现象"})
    g = study.build_study_guide("采样定理？", [_hit()])
    assert [s.number for s in g.matched] == ["3.1"]
    assert [s.number for s in g.recommended] == ["3.2"]
    assert g.recommended[0].summary == "讲混叠现象"
    assert g.recommended[0].locator == "p22" and g.recommended[0].doc_title == "书"


def test_build_study_guide_fallback_keeps_all_hits(monkeypatch):
    # LLM 复核失败降级：命中节全保留、不给推荐（宁缺勿错）
    _FakeStore.rows = [{"doc_id": 1, "number": "3.1", "title": "采样",
                        "locator": "p21", "source": "original", "text": "x"}]
    monkeypatch.setattr(study, "LibraryStore", _FakeStore)
    monkeypatch.setattr(study, "_pick_sections", lambda q, h, c: None)
    g = study.build_study_guide("q", [_hit()])
    assert [s.number for s in g.matched] == ["3.1"] and g.recommended == []


def test_build_study_guide_empty_hits():
    # 无命中：返回空学习指引，不触数据库
    g = study.build_study_guide("q", [])
    assert g.matched == [] and g.recommended == []