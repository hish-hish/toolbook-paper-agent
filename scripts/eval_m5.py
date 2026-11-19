"""M5 评测与消融跑分：A–E 五组各对 30 题跑完整 ask()，统计在库命中率与超纲拒答率。

纯打分逻辑在 toolbook.evaluation（已离线单测）；本脚本是 live 运行器（调 ask 触网）。
每组跑完即增量落盘，可中断续跑（--resume）；E 组（全开）即完整系统最终成绩。
耗时长（5 组×30 题约 4–5 小时、token约单次5倍），建议后台/过夜执行；脚本不会自动启动。

用法：
  uv run python scripts/eval_m5.py                # 跑全部 A–E
  uv run python scripts/eval_m5.py --configs E    # 只跑完整系统（最终成绩）
  uv run python scripts/eval_m5.py --configs A,C  # 只跑指定子集
  uv run python scripts/eval_m5.py --resume       # 跳过报告里已完成的配置续跑
"""
import argparse
import json
import sys
import time
from pathlib import Path

# 允许直接以脚本方式运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook import evaluation as ev
from toolbook.agent import ask
from toolbook.config import DATA_DIR

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = ROOT / "tests" / "fixtures" / "m5_questions.json"
DEFAULT_OUT = DATA_DIR / "eval" / "m5_report.json"
DEFAULT_MD = ROOT / "docs" / "评测报告-M5.md"


def run_config(cfg: str, flags: dict, items: list, doc_ids: list[int] | None = None) -> dict:
    """对一组配置跑全部题目：逐题 ask→打分→打印进度，返回 {flags, summary, rows}。

    doc_ids 限定只搜某些书（评测锁库，与消融同口径）；默认 None 搜全库。
    """
    rows = []
    for item in items:
        t0 = time.time()
        r = ask(item["question"], doc_ids=doc_ids, **flags)
        got = [s.number for s in r.sources]
        row = ev.score_question(item, r.refused, got, r.retries)
        rows.append(row)
        dt = time.time() - t0
        if item.get("expect_refuse"):
            tag = "✓拒答" if row["ok"] else "✗硬答"
            print(f"  [{cfg}][{item['id']:>2}] 超纲 {tag} ({dt:.0f}s) {item['question']}", flush=True)
        else:
            tag = "✓" if row["loose"] else "✗"
            print(f"  [{cfg}][{item['id']:>2}] 在库 {tag} 期望{item['expect']} 得到{got} ({dt:.0f}s)", flush=True)
    return {"flags": flags, "summary": ev.aggregate(rows), "rows": rows}


def main(argv=None):
    """解析参数→选题库→（续跑读旧报告）→逐组跑分增量落盘→渲染一页对比表。"""
    ap = argparse.ArgumentParser(description="M5 评测与消融跑分")
    ap.add_argument("--configs", default=None, help="逗号分隔子集，如 A,C,E；默认全部 A–E")
    ap.add_argument("--resume", action="store_true", help="跳过报告里已完成的配置续跑")
    ap.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="题库 JSON 路径")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="报告 JSON 落盘路径")
    ap.add_argument("--md", default=str(DEFAULT_MD), help="对比表 Markdown 路径")
    ap.add_argument("--doc-id", type=int, default=None,
                    help="限定只搜某本书（评测锁库，与消融同口径）；默认全库")
    args = ap.parse_args(argv)

    items = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 续跑：读已有报告保留已完成配置；否则从零开始
    report = {}
    if args.resume and out.exists():
        report = json.loads(out.read_text(encoding="utf-8"))
    report.setdefault("n_questions", len(items))
    report.setdefault("in_total", sum(1 for i in items if not i.get("expect_refuse")))
    report.setdefault("out_total", sum(1 for i in items if i.get("expect_refuse")))
    report.setdefault("configs", {})
    report["doc_id_scope"] = args.doc_id  # 记录本次评测锁库范围（None=全库）
    done = list(report["configs"].keys())

    requested = [c.strip().upper() for c in args.configs.split(",")] if args.configs else None
    todo = ev.select_configs(requested, done if args.resume else [])
    if not todo:
        print("没有要跑的配置（都已完成或未匹配）。")
    for cfg in todo:
        print(f"\n=== 配置 {cfg}（{ev.CONFIG_LABELS[cfg]}）{ev.ABLATION_CONFIGS[cfg]} ===", flush=True)
        report["configs"][cfg] = run_config(
            cfg, ev.ABLATION_CONFIGS[cfg], items,
            [args.doc_id] if args.doc_id is not None else None)
        report["configs_order"] = [c for c in ev.ABLATION_CONFIGS if c in report["configs"]]
        # 每组跑完即落盘：中断不丢已完成组
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        s = report["configs"][cfg]["summary"]
        print(f"  小结 {cfg}：在库宽松 {s['loose']}/{s['in_total']}，"
              f"超纲拒答 {s['refuse_ok']}/{s['out_total']}", flush=True)

    # 渲染一页对比表（即使只跑了部分配置也出表）
    if report["configs"]:
        report["configs_order"] = [c for c in ev.ABLATION_CONFIGS if c in report["configs"]]
        md = Path(args.md)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(ev.format_markdown(report), encoding="utf-8")
        print(f"\n报告：{out}\n对比表：{md}")


if __name__ == "__main__":
    main()