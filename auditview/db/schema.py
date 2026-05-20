import aiosqlite

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
    countable_lines INTEGER DEFAULT NULL,
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
    UNIQUE(session_id, file_path, line_hash, context_hash, line_no)
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

CREATE INDEX IF NOT EXISTS idx_files_session
    ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_reviewed_lines_session_file
    ON reviewed_lines(session_id, file_path);
CREATE INDEX IF NOT EXISTS idx_notes_session_file
    ON notes(session_id, file_path);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'P2',
    status TEXT NOT NULL DEFAULT 'open',
    source TEXT DEFAULT NULL,
    closed_by TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

_MIGRATIONS = [
    "ALTER TABLE files ADD COLUMN prev_line_hashes TEXT DEFAULT NULL",
    "ALTER TABLE files ADD COLUMN countable_lines INTEGER DEFAULT NULL",
    "CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviewed_lines_session_file ON reviewed_lines(session_id, file_path)",
    "CREATE INDEX IF NOT EXISTS idx_notes_session_file ON notes(session_id, file_path)",
    "CREATE TABLE IF NOT EXISTS app_config (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id), title TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'P2', status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))",
    "ALTER TABLE notes ADD COLUMN issue_id INTEGER REFERENCES issues(id)",
    "ALTER TABLE issues ADD COLUMN description TEXT NOT NULL DEFAULT ''",
    # Widen reviewed_lines UNIQUE to include line_no so two visible lines that
    # happen to share (line_hash, context_hash) each get their own row.
    (
        "CREATE TABLE IF NOT EXISTS reviewed_lines_new ("
        "id INTEGER PRIMARY KEY, "
        "session_id INTEGER NOT NULL, "
        "file_path TEXT NOT NULL, "
        "line_hash TEXT NOT NULL, "
        "context_hash TEXT NOT NULL, "
        "line_no INTEGER NOT NULL, "
        "reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), "
        "UNIQUE(session_id, file_path, line_hash, context_hash, line_no))",
        "INSERT INTO reviewed_lines_new "
        "(id, session_id, file_path, line_hash, context_hash, line_no, reviewed_at) "
        "SELECT id, session_id, file_path, line_hash, context_hash, line_no, reviewed_at "
        "FROM reviewed_lines",
        "DROP TABLE reviewed_lines",
        "ALTER TABLE reviewed_lines_new RENAME TO reviewed_lines",
        "CREATE INDEX IF NOT EXISTS idx_reviewed_lines_session_file ON reviewed_lines(session_id, file_path)",
    ),
    "ALTER TABLE issues ADD COLUMN source TEXT DEFAULT NULL",
    "ALTER TABLE issues ADD COLUMN closed_by TEXT DEFAULT NULL",
]

_IDEMPOTENT_ERROR_FRAGMENTS = ("duplicate column name", "already exists")


def _is_idempotent_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(frag in msg for frag in _IDEMPOTENT_ERROR_FRAGMENTS)


async def run_migrations(conn):
    for statement in _DDL.split(';'):
        statement = statement.strip()
        if statement:
            await conn.execute(statement)

    cur = await conn.execute("SELECT MAX(version) AS v FROM schema_version")
    row = await cur.fetchone()
    current = row["v"] if row and row["v"] is not None else 0

    for i in range(current, len(_MIGRATIONS)):
        entry = _MIGRATIONS[i]
        statements = (entry,) if isinstance(entry, str) else tuple(entry)
        await conn.execute("BEGIN")
        try:
            for statement in statements:
                try:
                    await conn.execute(statement)
                except aiosqlite.OperationalError as exc:
                    if not _is_idempotent_error(exc):
                        raise
            await conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (i + 1,)
            )
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
