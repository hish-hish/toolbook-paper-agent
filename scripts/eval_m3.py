"""M3 验收评测：20 题（16 在库 + 4 超纲）跑 ask()，统计出处命中与拒答正确率。"""
import json
import sys
from pathlib import Path

# 允许直接以脚本方式运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.agent import ask
from toolbook.config import DATA_DIR

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "m3_questions.json"


def hit_level(item, result):
    """命中判定：strict=章节号完全一致；loose=允许章级前缀（3 对 3.1）。"""
    nums = [s.number for s in result.sources]
    strict = any(n in item["expect"] for n in nums)
    loose = any(n == e or e.startswith(n + ".") or n.startswith(e + ".")
                for n in nums for e in item["expect"])
    return strict, loose


def main():
    """逐题跑问答并汇总：在库题命中率 + 超纲题拒答率，报告落盘 data/eval/。"""
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows, n_strict, n_loose, n_in, n_ref_ok, n_ref = [], 0, 0, 0, 0, 0
    for item in items:
        r = ask(item["question"])
        if item.get("expect_refuse"):
            n_ref += 1
            ok = r.refused
            n_ref_ok += ok
            rows.append({"id": item["id"], "type": "out", "ok": ok, "refused": r.refused})
            print(f"[{item['id']:>2}] 超纲 {'✓拒答' if ok else '✗硬答'}  {item['question']}")
        else:
            n_in += 1
            strict, loose = hit_level(item, r)
            n_strict += strict
            n_loose += loose
            nums = [s.number for s in r.sources]
            rows.append({"id": item["id"], "type": "in", "strict": strict, "loose": loose,
                         "expect": item["expect"], "got": nums, "refused": r.refused,
                         "retries": r.retries})
            print(f"[{item['id']:>2}] 在库 {'✓' if loose else '✗'} 期望{item['expect']} 得到{nums}  {item['question']}")
    report = {"in_total": n_in, "strict": n_strict, "loose": n_loose,
              "out_total": n_ref, "refuse_ok": n_ref_ok, "rows": rows}
    out = DATA_DIR / "eval" / "m3_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n在库 {n_in} 题：严格命中 {n_strict}，宽松命中 {n_loose}（{n_loose/n_in:.0%}）")
    print(f"超纲 {n_ref} 题：正确拒答 {n_ref_ok}（{n_ref_ok/n_ref:.0%}）")
    print(f"报告：{out}")


if __name__ == "__main__":
    main()