"""评测与消融打分离线单测：命中判定、逐题打分、聚合、配置矩阵、续跑选择、报告表格。"""
import toolbook.evaluation as ev


def test_hit_level_strict_and_loose():
    # 完全一致=strict+loose；章级前缀（期望3.1得到3）=仅loose；无关=都不命中
    assert ev.hit_level(["3.1"], ["3.1"]) == (True, True)
    assert ev.hit_level(["3.1"], ["3"]) == (False, True)
    assert ev.hit_level(["3.1"], ["8.4"]) == (False, False)


def test_score_question_in_library():
    # 在库题：记录命中、得到节号、重试次数
    item = {"id": 1, "question": "q", "expect": ["3.1"]}
    row = ev.score_question(item, refused=False, got=["3.1", "3.2"], retries=1)
    assert row["type"] == "in" and row["strict"] and row["loose"]
    assert row["got"] == ["3.1", "3.2"] and row["retries"] == 1


def test_score_question_out_of_scope():
    # 超纲题：拒答=ok True，硬答=ok False
    item = {"id": 23, "question": "q", "expect_refuse": True}
    assert ev.score_question(item, refused=True, got=[])["ok"] is True
    assert ev.score_question(item, refused=False, got=["3.1"])["ok"] is False


def test_aggregate_counts():
    # 聚合：在库3题严格1宽松2；超纲2题正确拒答1
    rows = [
        {"type": "in", "strict": True, "loose": True},
        {"type": "in", "strict": False, "loose": True},
        {"type": "in", "strict": False, "loose": False},
        {"type": "out", "ok": True},
        {"type": "out", "ok": False},
    ]
    assert ev.aggregate(rows) == {"in_total": 3, "strict": 1, "loose": 2,
                                  "out_total": 2, "refuse_ok": 1}


def test_ablation_configs_matrix():
    # A 纯BM25（关向量/改写/重排）；E 完整（全开）；C 混合但关改写重排
    assert ev.ABLATION_CONFIGS["A"] == {"use_bm25": True, "use_vector": False,
                                        "use_llm": False, "use_rerank": False}
    assert ev.ABLATION_CONFIGS["E"] == {"use_bm25": True, "use_vector": True,
                                        "use_llm": True, "use_rerank": True}
    assert ev.ABLATION_CONFIGS["C"]["use_llm"] is False
    assert ev.ABLATION_CONFIGS["C"]["use_rerank"] is False


def test_select_configs_order_and_resume():
    # 默认全跑按矩阵序；指定子集也按矩阵序；续跑跳过已完成
    assert ev.select_configs(None, []) == ["A", "B", "C", "D", "E"]
    assert ev.select_configs(["E", "A"], []) == ["A", "E"]
    assert ev.select_configs(None, ["A", "B"]) == ["C", "D", "E"]


def test_format_markdown_table():
    # 报告表格含各配置行与命中分数
    report = {"n_questions": 30, "in_total": 22, "out_total": 8,
              "configs_order": ["A", "E"],
              "configs": {
                  "A": {"summary": {"in_total": 22, "strict": 10, "loose": 12,
                                    "out_total": 8, "refuse_ok": 8}},
                  "E": {"summary": {"in_total": 22, "strict": 18, "loose": 19,
                                    "out_total": 8, "refuse_ok": 8}},
              }}
    md = ev.format_markdown(report)
    assert "| A |" in md and "| E |" in md
    assert "18/22" in md and "8/8" in md