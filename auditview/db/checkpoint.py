import json

try:
    import apsw
    _HAS_APSW = True
except ImportError:
    _HAS_APSW = False

_MAX_CHECKPOINTS = 50


class CheckpointManager:
    def __init__(self, conn):
        self._conn = conn
        self._session = None
        self._session_id = None
        self._is_apsw = getattr(conn, '_is_apsw', False)

    def supports_checkpoints(self):
        if not self._is_apsw:
            return False
        try:
            _ = apsw.Session
            return True
        except AttributeError:
            return False

    def begin(self, session_id):
        self._session_id = session_id
        if not self.supports_checkpoints():
            return
        raw_conn = object.__getattribute__(self._conn, '_conn') if hasattr(self._conn, '_conn') else self._conn
        self._session = apsw.Session(raw_conn, "main")
        self._session.attach("reviewed_lines")
        self._session.attach("notes")

    def save(self, label):
        if not self.supports_checkpoints() or self._session is None:
            return
        try:
            blob = self._session.changeset()
        except Exception:
            self._session = None
            return

        self._session = None

        if not blob:
            return

        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO checkpoints (session_id, label, changeset_blob, checkpoint_type) VALUES (?, ?, ?, 'changeset')",
            (self._session_id, label, blob),
        )
        cur.execute(
            """DELETE FROM checkpoints WHERE session_id = ? AND id NOT IN (
                SELECT id FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT ?
            )""",
            (self._session_id, self._session_id, _MAX_CHECKPOINTS),
        )

    def save_snapshot(self, session_id, label):
        cur = self._conn.cursor()
        is_apsw = self._is_apsw

        def row_to_dict(r, keys):
            if is_apsw:
                return dict(zip(keys, r))
            return dict(r)

        rl_keys = ["id", "session_id", "file_path", "line_hash", "context_hash", "line_no", "reviewed_at"]
        rl_rows = [
            row_to_dict(r, rl_keys)
            for r in cur.execute(
                "SELECT id, session_id, file_path, line_hash, context_hash, line_no, reviewed_at "
                "FROM reviewed_lines WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        ]

        n_keys = ["id", "session_id", "file_path", "start_line", "end_line", "start_hash", "end_hash",
                  "snapshot_text", "content", "is_todo", "is_orphaned", "created_at"]
        n_rows = [
            row_to_dict(r, n_keys)
            for r in cur.execute(
                "SELECT id, session_id, file_path, start_line, end_line, start_hash, end_hash, "
                "snapshot_text, content, is_todo, is_orphaned, created_at "
                "FROM notes WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        ]

        blob = json.dumps({"reviewed_lines": rl_rows, "notes": n_rows}).encode()
        cur.execute(
            "INSERT INTO checkpoints (session_id, label, changeset_blob, checkpoint_type) VALUES (?, ?, ?, 'snapshot')",
            (session_id, label, blob),
        )
        cur.execute(
            """DELETE FROM checkpoints WHERE session_id = ? AND id NOT IN (
                SELECT id FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT ?
            )""",
            (session_id, session_id, _MAX_CHECKPOINTS),
        )

    def revert(self, checkpoint_id):
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT changeset_blob, checkpoint_type FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Checkpoint {checkpoint_id} not found")

        is_apsw = self._is_apsw
        blob = row[0] if is_apsw else row["changeset_blob"]
        cp_type = row[1] if is_apsw else row["checkpoint_type"]

        if cp_type == "snapshot":
            self._revert_snapshot(checkpoint_id, blob, cur)
            return

        if not self.supports_checkpoints():
            raise RuntimeError("Checkpoints not supported: apsw not available")

        inverted = apsw.Changeset.invert(blob)
        raw_conn = object.__getattribute__(self._conn, '_conn') if hasattr(self._conn, '_conn') else self._conn

        def conflict_handler(conflict_type, item):
            return apsw.SQLITE_CHANGESET_OMIT

        apsw.Changeset.apply(inverted, raw_conn, conflict=conflict_handler)

    def _revert_snapshot(self, checkpoint_id, blob, cur):
        cur2 = self._conn.cursor()
        row = cur2.execute(
            "SELECT session_id FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        session_id = row[0] if self._is_apsw else row["session_id"]

        data = json.loads(blob)
        rl_rows = data["reviewed_lines"]
        n_rows = data["notes"]

        cur2.execute("DELETE FROM reviewed_lines WHERE session_id = ?", (session_id,))
        for r in rl_rows:
            cur2.execute(
                "INSERT OR IGNORE INTO reviewed_lines "
                "(id, session_id, file_path, line_hash, context_hash, line_no, reviewed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["id"], r["session_id"], r["file_path"], r["line_hash"],
                 r["context_hash"], r["line_no"], r["reviewed_at"]),
            )

        cur2.execute("DELETE FROM notes WHERE session_id = ?", (session_id,))
        for n in n_rows:
            cur2.execute(
                "INSERT OR IGNORE INTO notes "
                "(id, session_id, file_path, start_line, end_line, start_hash, end_hash, "
                "snapshot_text, content, is_todo, is_orphaned, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (n["id"], n["session_id"], n["file_path"], n["start_line"], n["end_line"],
                 n["start_hash"], n["end_hash"], n["snapshot_text"], n["content"],
                 n["is_todo"], n["is_orphaned"], n["created_at"]),
            )
