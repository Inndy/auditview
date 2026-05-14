_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    root_path TEXT NOT NULL,
    exclusion_patterns TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    rel_path TEXT NOT NULL,
    last_mtime REAL,
    prev_line_hashes TEXT DEFAULT NULL,
    UNIQUE(session_id, rel_path)
);

CREATE TABLE IF NOT EXISTS reviewed_lines (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    line_hash TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(session_id, file_path, line_hash, context_hash)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    start_hash TEXT NOT NULL,
    end_hash TEXT NOT NULL,
    snapshot_text TEXT NOT NULL,
    content TEXT NOT NULL,
    is_todo INTEGER NOT NULL DEFAULT 0,
    is_orphaned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    changeset_blob BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

_MIGRATIONS = [
    "ALTER TABLE files ADD COLUMN prev_line_hashes TEXT DEFAULT NULL",
]


def run_migrations(conn):
    cur = conn.cursor()
    for statement in _DDL.split(';'):
        statement = statement.strip()
        if statement:
            cur.execute(statement)
    for sql in _MIGRATIONS:
        try:
            cur.execute(sql)
        except Exception:
            pass
