"""核验模块离线单测：归一化、机械子串匹配、拆句与两级分流。"""
import toolbook.verify as vf
from toolbook.models import VerifiedSentence
from toolbook.retrieval import SearchHit
from toolbook.verify import mechanical_ok, normalize, split_sentences


def test_normalize_fullwidth_and_space():
    # 全角字母/空格/中英标点统一后应相等
    assert normalize("Ｆｏｕｒｉｅｒ 变换，性质。") == normalize("fourier变换,性质.")


def test_mechanical_ok_exact():
    # 原文摘录一字不差（允许空白差异）应通过
    src = "采样定理指出：采样频率必须大于信号最高频率的两倍。"
    assert mechanical_ok("采样频率必须大于信号最高频率的两倍", src)
    assert mechanical_ok("采样频率 必须大于信号最高频率的两倍", src)


def test_mechanical_rejects_altered():
    # 内容被篡改（两倍→三倍）或空摘录必须拒绝
    src = "采样频率必须大于信号最高频率的两倍。"
    assert not mechanical_ok("采样频率必须大于信号最高频率的三倍", src)
    assert not mechanical_ok("", src)


def test_split_sentences():
    # 按中英文句末标点拆句
    assert split_sentences("第一句。第二句！第三句？") == ["第一句。", "第二句！", "第三句？"]


def _hit(text):
    # 构造最小 SearchHit 供核验测试
    return SearchHit(1, 1, "3.1", "采样", "original", "p21", text, 0.5, "both", "书")


def test_judge_parses_verdict(monkeypatch):
    # LLM 裁判返回的 JSON 应被正确解析
    monkeypatch.setattr(vf.llm, "chat", lambda *a, **k: '{"supported": true, "quote": "两倍"}')
    v = vf.judge_sentence("采样率要大于最高频率两倍", "采样频率必须大于最高频率的两倍。")
    assert v == {"supported": True, "quote": "两倍"}


def test_judge_failure_returns_none(monkeypatch):
    # 断网/异常时裁判返回 None（调用方剔除该句）
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(vf.llm, "chat", boom)
    assert vf.judge_sentence("句", "原文") is None


def test_verify_draft_excerpt_mechanical():
    # 摘录句：一字不差通过，篡改拒绝
    hits = [_hit("采样频率必须大于最高频率的两倍。")]
    draft = [{"text": "采样频率必须大于最高频率的两倍", "type": "excerpt", "ref": 0},
             {"text": "采样频率必须大于最高频率的三倍", "type": "excerpt", "ref": 0}]
    out = vf.verify_draft(draft, hits)
    assert len(out) == 1
    assert out[0].badge == "mechanical" and out[0].kind == "excerpt"


def test_verify_draft_summary_double_anchor(monkeypatch):
    # 归纳句：LLM 支持且 quote 可机械锚回原文才通过
    hits = [_hit("采样频率必须大于最高频率的两倍。")]
    monkeypatch.setattr(vf, "judge_sentence", lambda s, src: {"supported": True, "quote": "两倍"})
    out = vf.verify_draft([{"text": "采样率需超过最高频率两倍", "type": "summary", "ref": 0}], hits)
    assert len(out) == 1 and out[0].badge == "llm"
    # quote 锚不住原文 → 剔除（宁缺勿错）
    monkeypatch.setattr(vf, "judge_sentence", lambda s, src: {"supported": True, "quote": "三倍"})
    assert vf.verify_draft([{"text": "采样率需超过最高频率两倍", "type": "summary", "ref": 0}], hits) == []
    # 裁判失败 → 剔除
    monkeypatch.setattr(vf, "judge_sentence", lambda s, src: None)
    assert vf.verify_draft([{"text": "句", "type": "summary", "ref": 0}], hits) == []


def test_verify_draft_bad_ref_dropped():
    # 引用索引越界的句子直接丢弃
    hits = [_hit("原文")]
    assert vf.verify_draft([{"text": "原文", "type": "excerpt", "ref": 9}], hits) == []