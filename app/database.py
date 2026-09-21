"""SQLite 持久层：校验案例的保存 / 加载 / 列表 / 删除。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get(
    "DIMLAB_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "data", "cases.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    expression  TEXT NOT NULL,
    variables   TEXT NOT NULL DEFAULT '{}',   -- {name: {value, unit}}
    tags        TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        variables = json.loads(row["variables"])
    except json.JSONDecodeError:
        variables = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "expression": row["expression"],
        "variables": variables,
        "tags": [t for t in row["tags"].split(",") if t],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_cases(q: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect() as conn:
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM cases WHERE name LIKE ? OR expression LIKE ?"
                " OR description LIKE ? ORDER BY updated_at DESC",
                (like, like, like)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cases ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_case(case_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ?",
                           (case_id,)).fetchone()
    return _row_to_dict(row) if row else None


def create_case(data: Dict[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO cases (name, description, expression, variables,"
            " tags, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (data["name"], data.get("description", ""),
             data["expression"],
             json.dumps(data.get("variables", {}), ensure_ascii=False),
             ",".join(data.get("tags", [])), now, now))
        case_id = cur.lastrowid
    return get_case(case_id)


def update_case(case_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = int(time.time())
    fields, params = [], []
    for key in ("name", "description", "expression", "tags"):
        if key in data:
            if key == "tags":
                fields.append("tags = ?")
                params.append(",".join(data[key]))
            else:
                fields.append(f"{key} = ?")
                params.append(data[key])
    if "variables" in data:
        fields.append("variables = ?")
        params.append(json.dumps(data["variables"], ensure_ascii=False))
    if not fields:
        return get_case(case_id)
    fields.append("updated_at = ?")
    params.append(now)
    params.append(case_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE cases SET {', '.join(fields)} WHERE id = ?", params)
        if cur.rowcount == 0:
            return None
    return get_case(case_id)


def delete_case(case_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        return cur.rowcount > 0
