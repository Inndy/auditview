try:
    import apsw
    _HAS_APSW = True
except ImportError:
    _HAS_APSW = False

_MAX_CHECKPOINTS = 1000


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
            "INSERT INTO checkpoints (session_id, label, changeset_blob) VALUES (?, ?, ?)",
            (self._session_id, label, blob),
        )
        cur.execute(
            """DELETE FROM checkpoints WHERE session_id = ? AND id NOT IN (
                SELECT id FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT ?
            )""",
            (self._session_id, self._session_id, _MAX_CHECKPOINTS),
        )

    def revert(self, checkpoint_id):
        if not self.supports_checkpoints():
            raise RuntimeError("Checkpoints not supported: apsw not available")

        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT changeset_blob FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Checkpoint {checkpoint_id} not found")

        blob = row[0]
        inverted = apsw.Changeset.invert(blob)

        raw_conn = object.__getattribute__(self._conn, '_conn') if hasattr(self._conn, '_conn') else self._conn

        def conflict_handler(conflict_type, item):
            return apsw.SQLITE_CHANGESET_OMIT

        apsw.Changeset.apply(inverted, raw_conn, conflict=conflict_handler)
