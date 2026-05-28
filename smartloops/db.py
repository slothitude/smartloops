"""Smart Loops — SQLite database layer."""

import sqlite3
import os
import json
from datetime import datetime

from config import DB_PATH, DATA_DIR


def _get_conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            path TEXT NOT NULL,
            goal TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created TEXT NOT NULL,
            last_audit TEXT,
            next_wakeup TEXT
        );

        CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            assessment TEXT NOT NULL,
            confidence INTEGER NOT NULL DEFAULT 50,
            risk_level TEXT NOT NULL DEFAULT 'low',
            next_wakeup TEXT,
            wake_reason TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS wake_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            woke_at TEXT NOT NULL,
            reason TEXT,
            action_taken TEXT,
            next_wakeup TEXT
        );
    """)
    conn.commit()
    conn.close()


# --- Projects ---

def add_project(name: str, path: str, goal: str) -> int:
    conn = _get_conn()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "INSERT INTO projects (name, path, goal, status, created) VALUES (?, ?, ?, 'active', ?)",
        (name, path, goal, now),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def get_project(name: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_project_by_path(path: str) -> dict | None:
    """Look up a project by filesystem path."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM projects WHERE path = ?", (path,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_project_by_id(pid: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_projects(status: str | None = None) -> list[dict]:
    conn = _get_conn()
    if status:
        rows = conn.execute("SELECT * FROM projects WHERE status = ? ORDER BY name", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_project(name: str, **kwargs) -> bool:
    if not kwargs:
        return False
    allowed = {"status", "goal", "path", "last_audit", "next_wakeup"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return False
    sets = ", ".join(f"{k} = ?" for k in filtered)
    vals = list(filtered.values()) + [name]
    conn = _get_conn()
    cur = conn.execute(f"UPDATE projects SET {sets} WHERE name = ?", vals)
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


# --- Audits ---

def add_audit(project_id: int, assessment: str, confidence: int, risk_level: str,
              next_wakeup: str | None = None, wake_reason: str | None = None) -> int:
    conn = _get_conn()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "INSERT INTO audits (project_id, timestamp, assessment, confidence, risk_level, next_wakeup, wake_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, now, assessment, confidence, risk_level, next_wakeup, wake_reason),
    )
    # Update project's last_audit
    conn.execute("UPDATE projects SET last_audit = ? WHERE id = ?", (now, project_id))
    if next_wakeup:
        conn.execute("UPDATE projects SET next_wakeup = ? WHERE id = ?", (next_wakeup, project_id))
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def get_latest_audit(project_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM audits WHERE project_id = ? ORDER BY timestamp DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_audit_history(project_id: int, limit: int = 10) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM audits WHERE project_id = ? ORDER BY timestamp DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Wake History ---

def add_wake_record(project_id: int, reason: str | None = None,
                    action_taken: str | None = None, next_wakeup: str | None = None) -> int:
    conn = _get_conn()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "INSERT INTO wake_history (project_id, woke_at, reason, action_taken, next_wakeup) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, now, reason, action_taken, next_wakeup),
    )
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    return wid


def get_wake_history(project_id: int, limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM wake_history WHERE project_id = ? ORDER BY woke_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Init on import
init_db()
