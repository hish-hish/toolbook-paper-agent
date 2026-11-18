"""M4 演示：解析 CORE 论文 → 展示目录 → 带论文上下文问两个知识点 → 核验答案附库内出处。"""
import sys
from pathlib import Path

# 允许直接以脚本方式运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.agent import ask
from toolbook.paper import parse_paper

PAPER = Path(__file__).resolve().parents[1] / "data" / "papers" / "CORE_TWC_09101709.pdf"

# 两个与论文主题相关、且资源库覆盖的知识点问题
QUESTIONS = [
    "论文涉及多径接收，匹配滤波怎样产生一个离散样本？",
    "论文用到协方差估计，LMMSE 信道估计的原理是什么？",
]


def main():
    """解析论文并展示目录，逐题跑带论文上下文的问答，打印徽章句与出处。"""
    paper = parse_paper(PAPER)
    print(f"论文：《{paper.title}》（{paper.n_pages} 页，{len(paper.outline)} 条目录）")
    for e in paper.outline[:8]:
        print(f"  {'  ' * (e['level'] - 1)}{e['title']} <p{e['page']}>")
    print(f"摘要：{paper.abstract[:150]}…")
    for q in QUESTIONS:
        print(f"\n=== [论文问答] {q} ===")
        r = ask(q, paper=paper)
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