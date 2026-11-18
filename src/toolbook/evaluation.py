"""评测与消融打分（M5）：命中判定、逐题打分、按配置聚合、消融配置矩阵、续跑选择与报告表格。

全是纯函数、离线可测；live 跑分由 scripts/eval_m5.py 调 ask() 后把结果喂进来。
消融比的是「关掉某检索组件后最终答案成绩掉多少」，配置 E（全开）即完整系统最终成绩。
"""

# 消融配置矩阵：每组对应 ask()/hybrid_search 的开关组合（A 纯BM25 → E 完整系统）
ABLATION_CONFIGS = {
    "A": {"use_bm25": True, "use_vector": False, "use_llm": False, "use_rerank": False},
    "B": {"use_bm25": False, "use_vector": True, "use_llm": False, "use_rerank": False},
    "C": {"use_bm25": True, "use_vector": True, "use_llm": False, "use_rerank": False},
    "D": {"use_bm25": True, "use_vector": True, "use_llm": True, "use_rerank": False},
    "E": {"use_bm25": True, "use_vector": True, "use_llm": True, "use_rerank": True},
}
# 各配置的中文说明（报告表格用）
CONFIG_LABELS = {"A": "纯BM25", "B": "纯向量", "C": "混合RRF", "D": "+双语改写", "E": "完整系统"}


def hit_level(expect: list[str], got: list[str]) -> tuple[bool, bool]:
    """命中判定：strict=章节号完全一致；loose=允许章级前缀（期望 3.1 得到 3 也算宽松命中）。"""
    strict = any(n in expect for n in got)
    loose = any(n == e or e.startswith(n + ".") or n.startswith(e + ".")
                for n in got for e in expect)
    return strict, loose


def score_question(item: dict, refused: bool, got: list[str], retries: int = 0) -> dict:
    """逐题打分：超纲题判拒答是否正确；在库题判严格/宽松命中。返回一行记录。"""
    if item.get("expect_refuse"):
        return {"id": item["id"], "type": "out", "ok": refused, "refused": refused}
    strict, loose = hit_level(item["expect"], got)
    return {"id": item["id"], "type": "in", "strict": strict, "loose": loose,
            "expect": item["expect"], "got": got, "refused": refused, "retries": retries}


def aggregate(rows: list[dict]) -> dict:
    """按配置聚合：在库题数/严格/宽松命中 + 超纲题数/正确拒答。"""
    ins = [r for r in rows if r["type"] == "in"]
    outs = [r for r in rows if r["type"] == "out"]
    return {"in_total": len(ins),
            "strict": sum(r["strict"] for r in ins),
            "loose": sum(r["loose"] for r in ins),
            "out_total": len(outs),
            "refuse_ok": sum(r["ok"] for r in outs)}


def select_configs(requested: list[str] | None, done: list[str]) -> list[str]:
    """选要跑的配置：requested 为空则全部 A–E；续跑时跳过已完成的；一律按矩阵顺序。"""
    order = [c for c in ABLATION_CONFIGS if requested is None or c in requested]
    return [c for c in order if c not in done]


def _pct(n: int, total: int) -> str:
    """命中分数渲染成 n/total (xx%)；total 为 0 时显示 — 避免除零（续跑/部分报告）。"""
    return f"{n}/{total} ({n / total:.0%})" if total else "—"


def format_markdown(report: dict) -> str:
    """把多配置报告渲染成一页对比表（供作品包 docs/评测报告-M5.md）。"""
    lines = ["# M5 评测与消融实验报告", "",
             f"题库：{report.get('n_questions', '?')} 题"
             f"（在库 {report.get('in_total', '?')} + 超纲 {report.get('out_total', '?')}）", "",
             "| 配置 | 说明 | 在库严格命中 | 在库宽松命中 | 超纲正确拒答 |",
             "|---|---|---|---|---|"]
    for cfg in report.get("configs_order", []):
        a = report["configs"][cfg]["summary"]
        lines.append(f"| {cfg} | {CONFIG_LABELS.get(cfg, cfg)} | "
                     f"{_pct(a['strict'], a['in_total'])} | "
                     f"{_pct(a['loose'], a['in_total'])} | "
                     f"{_pct(a['refuse_ok'], a['out_total'])} |")
    lines += ["", "> 消融结论：对比 A→B→C→D→E 的命中率变化，量化每个检索组件的贡献；"
              "E 组（全开）即完整系统最终成绩。核验链全程开启，不做关闭消融。", ""]
    return "\n".join(lines)