"""LLM 兜底章节识别离线单测：标题原文锚定、无结构切分、导入接线。"""
import toolbook.llm as llm
from toolbook.models import Block
from toolbook.structure import build_tree


def test_propose_titles_filters_fabricated(monkeypatch):
    # LLM 提议的标题必须在原文一字不差出现，编造的被过滤
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '["采样定理", "编造的标题"]')
    titles = llm.propose_titles("本章讲采样定理。后面是卷积。")
    assert titles == ["采样定理"]


def test_propose_titles_failure(monkeypatch):
    # 断网/异常：返回空列表（回退规则兜底）
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(llm, "chat", boom)
    assert llm.propose_titles("文本") == []


def test_build_tree_llm_fallback_splits():
    # 无标题文档：proposer 给出两个可定位标题 → 切成系统编号节（前言保留）
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
    assert any(n.number == "0" for n in roots)


def test_build_tree_fallback_fabricated_titles():
    # 标题都锚不住 → 回退 M1 单节兜底
    blocks = [Block("正文一。", "paragraph", 0, "p1"), Block("正文二。", "paragraph", 0, "p2")]
    roots = build_tree(blocks, "书", title_proposer=lambda t: ["不存在标题"])
    assert len(roots) == 1 and roots[0].number == "1"


def test_import_file_llm_fallback(tmp_path, monkeypatch):
    # 无标题 DOCX 导入：默认启用 LLM 兜底（打桩），产出多个系统编号节
    from docx import Document

    from toolbook.importer import import_file
    from toolbook.store import LibraryStore
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '["甲部分", "乙部分"]')
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