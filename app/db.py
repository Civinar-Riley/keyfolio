"""SQLite 初始化与访问。单用户场景，WAL 模式，每次操作独立短连接。"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_conn: sqlite3.Connection | None = None
_db_path: str = ""

SCHEMA_VERSION = 1

# 迁移脚本按序执行：MIGRATIONS[i] 把库从版本 i 升到 i+1
MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS channels (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        type        TEXT NOT NULL DEFAULT 'openai',
        base_url    TEXT NOT NULL,
        console_url TEXT NOT NULL DEFAULT '',
        grp         TEXT NOT NULL DEFAULT '',
        notes       TEXT NOT NULL DEFAULT '',
        enabled     INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS keys (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id         INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
        name               TEXT NOT NULL,
        value_enc          TEXT NOT NULL,
        notes              TEXT NOT NULL DEFAULT '',
        enabled            INTEGER NOT NULL DEFAULT 1,
        balance            REAL,
        currency           TEXT NOT NULL DEFAULT '',
        expires_at         TEXT NOT NULL DEFAULT '',
        balance_updated_at TEXT NOT NULL DEFAULT '',
        last_check         TEXT NOT NULL DEFAULT '',
        last_check_msg     TEXT NOT NULL DEFAULT '',
        created_at         TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS models (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
        model_id   TEXT NOT NULL,
        mtype      TEXT NOT NULL DEFAULT 'chat',
        notes      TEXT NOT NULL DEFAULT '',
        enabled    INTEGER NOT NULL DEFAULT 1,
        fetched_at TEXT NOT NULL DEFAULT '',
        UNIQUE(channel_id, model_id)
    );
    CREATE TABLE IF NOT EXISTS balance_records (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        key_id      INTEGER NOT NULL REFERENCES keys(id) ON DELETE CASCADE,
        balance     REAL NOT NULL,
        currency    TEXT NOT NULL DEFAULT '',
        expires_at  TEXT NOT NULL DEFAULT '',
        recorded_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS templates (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        client_type   TEXT NOT NULL DEFAULT '',
        json_template TEXT NOT NULL,
        builtin       INTEGER NOT NULL DEFAULT 0
    );
    """,
}


def init(db_path: Path) -> None:
    global _db_path
    _db_path = str(db_path)
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        version = _schema_version(conn)
        for target in range(version, SCHEMA_VERSION):
            sql = MIGRATIONS.get(target + 1)
            if sql is None:
                continue
            conn.executescript(sql)
            _set_meta(conn, "schema_version", target + 1)


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
    ).fetchone()
    if row is None:
        return 0
    value = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
    return int(value[0]) if value else 0


def _set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return row[0]


def set_setting(key: str, value) -> None:
    with get_conn() as conn:
        _set_meta(conn, key, value)


def delete_setting(key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))


def now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
