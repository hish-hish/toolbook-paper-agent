"""M2 演示：建向量索引 → 关键词/语义/跨语言三类查询 → 章节号直查对照。"""
import sys
from pathlib import Path

# 允许直接以脚本方式运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolbook.config import DEFAULT_DB
from toolbook.retrieval import hybrid_search
from toolbook.store import LibraryStore
from toolbook.vector_index import build_vector_index

# 三类验收查询：关键词 / 语义改写 / 英文跨语言
QUERIES = [
    ("关键词", "奈奎斯特 采样 混叠"),
    ("语义", "怎样从离散样本无失真地恢复连续信号"),
    ("跨语言", "What is the Nyquist sampling criterion and aliasing?"),
]


def main():
    """建索引并逐类演示检索，最后用章节号直查旁路对照。"""
    n = build_vector_index()
    print(f"向量索引：{n} 条子块")
    for label, q in QUERIES:
        print(f"\n=== [{label}] {q} ===")
        hits = hybrid_search(q, top_k=3)
        for h in hits:
            badge = "" if h.source == "original" else " [系统编号]"
            # 标题自带编号时去掉前缀，避免打印重复
            title = h.title.removeprefix(h.number).strip() or h.title
            print(f"  《{h.doc_title}》 {h.number} {title}{badge}  <{h.locator}>  "
                  f"score={h.score:.4f} via={h.matched_by}")
    # 章节号直查旁路：不走检索，直接 SQLite 取原文
    store = LibraryStore(DEFAULT_DB)
    docs = store.list_documents()
    if docs:
        rows = store.get_section(docs[0]["doc_id"], "3.1")
        if rows:
            print(f"\n=== 章节号直查 3.1 ===\n  {rows[0]['title']}  <{rows[0]['locator']}>")
    store.close()


if __name__ == "__main__":
    main()