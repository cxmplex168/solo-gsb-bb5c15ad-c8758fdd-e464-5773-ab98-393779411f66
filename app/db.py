"""SQLite 案例存储：保存 / 读取 / 删除校验案例。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db_path() -> str:
    return os.environ.get("DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.db"
    )


def _get() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = _db_path()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                expression  TEXT NOT NULL DEFAULT '',
                variables   TEXT NOT NULL DEFAULT '{}',
                target_unit TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL
            )
            """
        )
        _conn.commit()
    return _conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "expression": row["expression"],
        "variables": json.loads(row["variables"] or "{}"),
        "target_unit": row["target_unit"],
        "created_at": row["created_at"],
    }


def create_case(name: str, expression: str, variables: dict, target_unit: str) -> int:
    with _lock:
        conn = _get()
        cur = conn.execute(
            "INSERT INTO cases (name, expression, variables, target_unit, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                name,
                expression,
                json.dumps(variables, ensure_ascii=False),
                target_unit,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_cases() -> list[dict]:
    with _lock:
        rows = _get().execute("SELECT * FROM cases ORDER BY id DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_case(case_id: int) -> dict | None:
    with _lock:
        row = _get().execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete_case(case_id: int) -> bool:
    with _lock:
        conn = _get()
        cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        conn.commit()
        return cur.rowcount > 0
