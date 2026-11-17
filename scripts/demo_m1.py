"""M1 演示：三格式导入 → 章节树 → 章节号直查 → 幂等复导入。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from make_demo_books import make_all

from toolbook.config import DATA_DIR
from toolbook.importer import import_file
from toolbook.store import LibraryStore


def main():
    db = DATA_DIR / "demo_m1.db"
    if db.exists():
        db.unlink()
    books = make_all(DATA_DIR / "demo_books")
    for b in books:
        r = import_file(b, db)
        print(f"[导入] 《{r.title}》 doc_id={r.doc_id} 章节行={r.sections} 子块={r.chunks}")
    store = LibraryStore(db)
    for d in store.list_documents():
        print(f"\n=== 《{d['title']}》 章节树 ===")
        for s in store.get_tree(d["doc_id"]):
            badge = "" if s["source"] == "original" else " [系统编号]"
            print(f"{'  ' * (s['level'] - 1)}{s['number']} {s['title']}{badge}  <{s['locator']}>")
    doc_id = store.list_documents()[0]["doc_id"]
    rows = store.get_section(doc_id, "1.1")
    print(f"\n=== 章节号直查 doc {doc_id} / 1.1 ===")
    print(rows[0]["text"][:200] if rows else "未命中")
    store.close()
    print("\n=== 幂等性：重复导入同一文件 ===")
    r = import_file(books[0], db)
    print(f"skipped={r.skipped}（应为 True）")


if __name__ == "__main__":
    main()