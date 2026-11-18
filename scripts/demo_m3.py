"""M3 演示：归纳问答 / 原文摘录 / 超纲拒答 三场景，展示核验徽章与出处目录。"""
import sys
from pathlib import Path

# 允许直接以脚本方式运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.agent import ask

# 三个验收场景：归纳（LLM核验）/ 摘录（机械核验）/ 超纲（拒答路径）
SCENES = [
    ("归纳问答", "循环前缀为什么能消除符号间干扰？"),
    ("原文摘录", "请摘录原文中关于采样定理条件的原话。"),
    ("超纲拒答", "量子引力理论的重整化方法有哪些？"),
]


def main():
    """逐场景跑 ask()，打印核验徽章句与出处目录（拒答场景打印已尝试查询）。"""
    for label, q in SCENES:
        print(f"\n=== [{label}] {q} ===")
        r = ask(q)
        if r.refused:
            print(f"  [拒答] {r.message}；已尝试：{r.searched}")
            continue
        for s in r.sentences:
            mark = "机械✓" if s.badge == "mechanical" else "LLM✓"
            print(f"  [{mark}][{s.ref}] {s.text}")
        for i, src in enumerate(r.sources):
            badge = "" if src.source == "original" else " [系统编号]"
            title = src.title.removeprefix(src.number).strip() or src.title
            print(f"  出处[{i}] 《{src.doc_title}》 {src.number} {title}{badge} <{src.locator}>")


if __name__ == "__main__":
    main()