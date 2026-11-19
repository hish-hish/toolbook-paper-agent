"""资源库清理脚本（一次性触库运行器）：剔除前言/目录/参考文献/自测等非知识节。

只动 system 系统编号节，原书正式章节与知识附录（推导/术语表/符号地图）一律保留。
流程：备份 library.db → 分类器选拟删节（子节随父 FK 级联删）→ 重建向量索引清残留 → 打印实删数。
判定逻辑在 structure.is_non_content_section（已离线单测）；本脚本只运行，不另单测。
用法：PYTHONIOENCODING=utf-8 uv run --no-sync python scripts/clean_library.py
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 允许脚本直接运行（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from toolbook import config
from toolbook.store import LibraryStore
from toolbook.structure import is_non_content_section
from toolbook.vector_index import build_vector_index


def main():
    db = config.DEFAULT_DB
    # 1. 备份数据库（可逆：恢复 .bak + 重建索引即可还原）
    backup = db.parent / (db.name + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(db, backup)
    print(f"已备份 → {backup}")

    store = LibraryStore(db)
    total_removed = 0
    try:
        # 2. 逐本书选拟删节并删除（分类器只判 system；子节随父级联清）
        for d in store.list_documents():
            doc_id = d["doc_id"]
            rows = store.get_tree(doc_id)
            before = len(rows)
            removable = [r["section_id"] for r in rows
                         if is_non_content_section(r["number"], r["title"], r["source"])]
            store.delete_sections(removable)
            after = len(store.get_tree(doc_id))
            removed = before - after
            total_removed += removed
            print(f"《{d['title']}》：{before} → {after} 节（实删 {removed}，含级联子节）")
    finally:
        store.close()

    # 3. 重建向量索引：清掉 Chroma 里已删块的残留向量，保持与库一致（bge-m3 免费）
    print("重建向量索引中（清残留向量，约数分钟）…")
    n = build_vector_index(db, force=True)
    print(f"向量索引重建完成：{n} 条。两本书共删除 {total_removed} 节。")


if __name__ == "__main__":
    main()