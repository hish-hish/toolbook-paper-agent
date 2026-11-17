import argparse
import sys

from .config import DEFAULT_DB
from .importer import import_file
from .store import LibraryStore


def main(argv=None):
    ap = argparse.ArgumentParser(prog="toolbook", description="ToolBook 资源库管理")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import", help="导入 docx/epub/pdf")
    p_imp.add_argument("files", nargs="+")
    sub.add_parser("list", help="列出已导入文档")
    p_tree = sub.add_parser("tree", help="显示章节树")
    p_tree.add_argument("doc_id", type=int)
    p_show = sub.add_parser("show", help="按章节号直查原文")
    p_show.add_argument("doc_id", type=int)
    p_show.add_argument("number")
    args = ap.parse_args(argv)

    if args.cmd == "import":
        for f in args.files:
            r = import_file(f, args.db)
            if r.skipped:
                print(f"[跳过] 《{r.title}》已导入（doc_id={r.doc_id}，哈希相同）")
            else:
                print(f"[导入] 《{r.title}》 doc_id={r.doc_id} 章节行={r.sections} 子块={r.chunks}")
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