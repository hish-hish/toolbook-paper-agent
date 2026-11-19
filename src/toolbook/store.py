import sqlite3
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  format TEXT NOT NULL,
  file_hash TEXT NOT NULL UNIQUE,
  source_path TEXT,
  imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sections(
  section_id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  number TEXT NOT NULL,
  title TEXT NOT NULL,
  level INTEGER NOT NULL,
  parent_id INTEGER REFERENCES sections(section_id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  locator TEXT,
  part INTEGER NOT NULL DEFAULT 1,
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks(
  chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
  section_id INTEGER NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sections_doc ON sections(doc_id, number);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_id);
"""


class LibraryStore:
    def __init__(self, db_path: Path | str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    @contextmanager
    def transaction(self):
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def find_by_hash(self, file_hash: str):
        return self.conn.execute(
            "SELECT * FROM documents WHERE file_hash=?", (file_hash,)).fetchone()

    def add_document(self, title, fmt, file_hash, source_path) -> int:
        cur = self.conn.execute(
            "INSERT INTO documents(title, format, file_hash, source_path) VALUES(?,?,?,?)",
            (title, fmt, file_hash, str(source_path)))
        return cur.lastrowid

    def insert_section(self, doc_id, parent_id, number, title, level,
                       source, locator, part, text) -> int:
        cur = self.conn.execute(
            "INSERT INTO sections(doc_id, parent_id, number, title, level, source, locator, part, text)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (doc_id, parent_id, number, title, level, source, locator, part, text))
        return cur.lastrowid

    def insert_chunks(self, section_id, texts) -> int:
        self.conn.executemany(
            "INSERT INTO chunks(section_id, seq, text) VALUES(?,?,?)",
            [(section_id, i, t) for i, t in enumerate(texts, 1)])
        return len(texts)

    def get_section(self, doc_id, number):
        return self.conn.execute(
            "SELECT * FROM sections WHERE doc_id=? AND number=? ORDER BY part",
            (doc_id, number)).fetchall()

    def list_documents(self):
        return self.conn.execute("SELECT * FROM documents ORDER BY doc_id").fetchall()

    def get_tree(self, doc_id):
        return self.conn.execute(
            "SELECT * FROM sections WHERE doc_id=? ORDER BY section_id",
            (doc_id,)).fetchall()

    def delete_document(self, doc_id):
        with self.transaction():
            self.conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))

    def delete_sections(self, section_ids):
        """按 section_id 删节：外键级联自动清掉其子节与 chunks；空列表无操作。"""
        ids = list(section_ids)
        if not ids:
            return
        with self.transaction():
            self.conn.executemany(
                "DELETE FROM sections WHERE section_id=?", [(i,) for i in ids])

    def close(self):
        self.conn.close()