"""SQLite storage: connection handling, schema and seed data."""

import sqlite3
import time
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content_html TEXT NOT NULL DEFAULT '',
    owner_id TEXT NOT NULL REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 1,
    source_filename TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES users(id)
);

-- Access grants. The owner is not stored here; ownership lives on documents.owner_id.
CREATE TABLE IF NOT EXISTS document_access (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    granted_by TEXT NOT NULL REFERENCES users(id),
    granted_at TEXT NOT NULL,
    PRIMARY KEY (document_id, user_id)
);

-- One current handoff per document. It records who is responsible for the next
-- action. It never changes documents.owner_id or document_access.
CREATE TABLE IF NOT EXISTS handoffs (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    contributor_id TEXT REFERENCES users(id),
    instruction TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('draft', 'awaiting', 'returned')),
    return_note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS handoff_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id);
CREATE INDEX IF NOT EXISTS idx_access_user ON document_access(user_id);
CREATE INDEX IF NOT EXISTS idx_events_doc ON handoff_events(document_id, id);
"""

SEED_USERS = [
    ("alex", "Alex Morgan", "alex@relay.test", "Account lead"),
    ("sam", "Sam Rivera", "sam@relay.test", "Operations"),
    ("jordan", "Jordan Lee", "jordan@relay.test", "Finance"),
]

SEED_DOC_ID = "demo-delivery-proposal"
SEED_DOC_HTML = (
    "<h1>Northwind delivery proposal</h1>"
    "<p>This proposal covers the first quarter rollout for Northwind's three regional "
    "warehouses. It is a draft for internal review before it goes to the customer.</p>"
    "<h2>Delivery dates</h2>"
    "<ul><li><p>Week 1: kickoff call and site survey in Leeds.</p></li>"
    "<li><p>Week 3: equipment delivered to Leeds and York.</p></li>"
    "<li><p>Week 5: Hull goes live, followed by a two week support period.</p></li></ul>"
    "<h2>Pricing</h2>"
    "<p>The quoted price is <strong>£48,500</strong> for installation and training. "
    "Support after week 7 is billed <em>monthly</em> at the standard rate.</p>"
    "<ol><li><p>Confirm the delivery dates with the warehouse managers.</p></li>"
    "<li><p>Check the support rate against the current rate card.</p></li></ol>"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    # The timeout makes a second writer wait for the lock instead of failing at once.
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path: str, seed: bool = True) -> None:
    """Create tables and seed data. Several server workers may call this at the
    same moment on a new database, so each step waits for the lock or retries."""
    conn = connect(path)
    try:
        for attempt in range(20):
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                break
            except sqlite3.OperationalError:
                if attempt == 19:
                    raise
                time.sleep(0.1)
        conn.executescript(SCHEMA)
        if seed:
            conn.execute("BEGIN IMMEDIATE")
            seed_demo(conn)
            conn.commit()
    finally:
        conn.close()


def seed_demo(conn: sqlite3.Connection, reset: bool = False) -> None:
    """Insert the seeded users and one demo document. Safe to run repeatedly."""
    if reset:
        for table in ("handoff_events", "handoffs", "document_access", "documents", "users"):
            conn.execute(f"DELETE FROM {table}")
    for user in SEED_USERS:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, email, title) VALUES (?, ?, ?, ?)", user
        )
    if conn.execute("SELECT 1 FROM documents WHERE id = ?", (SEED_DOC_ID,)).fetchone():
        return
    ts = now_iso()
    conn.execute(
        "INSERT INTO documents (id, title, content_html, owner_id, created_at, updated_at, updated_by)"
        " VALUES (?, ?, ?, 'alex', ?, ?, 'alex')",
        (SEED_DOC_ID, "Northwind delivery proposal", SEED_DOC_HTML, ts, ts),
    )
    conn.execute(
        "INSERT INTO document_access (document_id, user_id, granted_by, granted_at)"
        " VALUES (?, 'sam', 'alex', ?)",
        (SEED_DOC_ID, ts),
    )
    conn.execute(
        "INSERT INTO handoffs (document_id, contributor_id, instruction, status, updated_at, updated_by)"
        " VALUES (?, 'sam', 'Check the delivery dates.', 'awaiting', ?, 'alex')",
        (SEED_DOC_ID, ts),
    )
    conn.executemany(
        "INSERT INTO handoff_events (document_id, actor_id, action, detail, created_at)"
        " VALUES (?, 'alex', ?, ?, ?)",
        [
            (SEED_DOC_ID, "shared", "Sam Rivera", ts),
            (SEED_DOC_ID, "sent", "to Sam Rivera: Check the delivery dates.", ts),
        ],
    )
