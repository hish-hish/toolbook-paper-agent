"""ToolBook 资源库命令行入口：导入、向量索引、章节树、章节号直查与混合检索。"""
import argparse
import sys

from .config import DEFAULT_DB
from .importer import import_file
from .store import LibraryStore


def main(argv=None):
    """解析子命令并分发：import/list/tree/show（M1）+ index/search（M2）。"""
    ap = argparse.ArgumentParser(prog="toolbook", description="ToolBook 资源库管理")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import", help="导入 docx/epub/pdf")
    p_imp.add_argument("files", nargs="+")
    p_imp.add_argument("--no-llm-fallback", action="store_true", help="禁用无结构文档的 LLM 兜底")
    sub.add_parser("list", help="列出已导入文档")
    p_tree = sub.add_parser("tree", help="显示章节树")
    p_tree.add_argument("doc_id", type=int)
    p_show = sub.add_parser("show", help="按章节号直查原文")
    p_show.add_argument("doc_id", type=int)
    p_show.add_argument("number")
    # --- M2 新增：向量索引与混合检索 ---
    p_idx = sub.add_parser("index", help="建立/重建向量索引（调用 bge-m3）")
    p_idx.add_argument("--force", action="store_true", help="强制重建")
    p_search = sub.add_parser("search", help="混合检索（BM25+向量+RRF+重排）")
    p_search.add_argument("question")
    p_search.add_argument("--doc", type=int, default=None, help="限定文档 ID")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument("--no-llm", action="store_true", help="跳过 LLM 查询改写")
    p_search.add_argument("--no-rerank", action="store_true", help="跳过本地重排")
    args = ap.parse_args(argv)

    if args.cmd == "import":
        for f in args.files:
            r = import_file(f, args.db, llm_fallback=not args.no_llm_fallback)
            if r.skipped:
                print(f"[跳过] 《{r.title}》已导入（doc_id={r.doc_id}，哈希相同）")
            else:
                print(f"[导入] 《{r.title}》 doc_id={r.doc_id} 章节行={r.sections} 子块={r.chunks}")
        return
    if args.cmd == "index":
        # 建/重建向量索引（延迟导入，避免无谓加载 chromadb）
        from .vector_index import build_vector_index
        n = build_vector_index(args.db, force=args.force)
        print(f"向量索引完成：{n} 条")
        return
    if args.cmd == "search":
        # 混合检索：打印出处（书名/章节号/标题/定位）与正文预览
        from .retrieval import hybrid_search
        hits = hybrid_search(args.question, args.db, top_k=args.k,
                             use_llm=not args.no_llm, use_rerank=not args.no_rerank,
                             doc_id=args.doc)
        if not hits:
            print("未命中（资源库可能未覆盖该问题）")
            return
        for h in hits:
            badge = "" if h.source == "original" else " [系统编号]"
            # 标题自带编号时去掉前缀，避免打印重复
            title = h.title.removeprefix(h.number).strip() or h.title
            print(f"《{h.doc_title}》 {h.number} {title}{badge}  <{h.locator}>  "
                  f"score={h.score:.4f} via={h.matched_by}")
            print(f"  {h.text[:150]}...")
        return
    store = LibraryStore(args.db)
    if args.cmd == "list":
        for d in store.list_documents():
            print(f"{d['doc_id']}\t{d['title']}\t{d['format']}\t{d['imported_at']}")
    elif args.cmd == "tree":
        for s in store.get_tree(args.doc_id):
            badge = "" if s["source"] == "original" else " [系统编号]"
            part = f" (part {s['part']})" if s["part"] > 1 else ""
            print(f"{'  ' * (s['level'] - 1)}{s['number']} {s['title']}{badge}{part}  <{s['locator']}>")
    elif args.cmd == "show":
        rows = store.get_section(args.doc_id, args.number)
        if not rows:
            print(f"未找到章节 {args.number}")
            sys.exit(1)
        for r in rows:
            badge = "" if r["source"] == "original" else " [系统编号]"
            print(f"== {r['number']} {r['title']}{badge}  定位:{r['locator']} part:{r['part']} ==")
            print(r["text"])
    store.close()


if __name__ == "__main__":
    main()