import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rfp_history.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            upload_time TEXT NOT NULL,
            file_size INTEGER,
            text_length INTEGER,
            rfp_result TEXT,
            toc TEXT,
            sections TEXT,
            matrix TEXT,
            research TEXT,
            checklist TEXT,
            memos TEXT
        )
    """)
    # memos 컬럼 없는 기존 DB 대응
    try:
        conn.execute("ALTER TABLE uploads ADD COLUMN memos TEXT")
        conn.commit()
    except Exception:
        pass
    return conn


def save_record(filename, file_size, text_length):
    c = _conn()
    cur = c.execute(
        "INSERT INTO uploads (filename, upload_time, file_size, text_length) VALUES (?, ?, ?, ?)",
        (filename, datetime.now().strftime("%Y-%m-%d %H:%M"), file_size, text_length),
    )
    rid = cur.lastrowid
    c.commit()
    c.close()
    return rid


def update_record(rid, **kw):
    c = _conn()
    for k, v in kw.items():
        if k in ("rfp_result", "toc", "sections", "matrix", "research", "checklist", "memos"):
            c.execute(
                f"UPDATE uploads SET {k} = ? WHERE id = ?",
                (json.dumps(v, ensure_ascii=False) if v is not None else None, rid),
            )
    c.commit()
    c.close()


def list_records(limit=20):
    c = _conn()
    rows = c.execute(
        "SELECT id, filename, upload_time, file_size FROM uploads ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def load_record(rid):
    c = _conn()
    row = c.execute("SELECT * FROM uploads WHERE id = ?", (rid,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    for k in ("rfp_result", "toc", "sections", "matrix", "research", "checklist", "memos"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


def delete_record(rid):
    c = _conn()
    c.execute("DELETE FROM uploads WHERE id = ?", (rid,))
    c.commit()
    c.close()
