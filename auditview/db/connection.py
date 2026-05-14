try:
    import apsw
    _HAS_APSW = True
except ImportError:
    _HAS_APSW = False


class _APSWWrapper:
    def __init__(self, conn):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_is_apsw', True)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_conn'), name)

    def __setattr__(self, name, value):
        if name in ('_conn', '_is_apsw'):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, '_conn'), name, value)

    def cursor(self):
        return object.__getattribute__(self, '_conn').cursor()

    def execute(self, sql, *args):
        return object.__getattribute__(self, '_conn').execute(sql, *args)

    def last_insert_rowid(self):
        return object.__getattribute__(self, '_conn').last_insert_rowid()

    def begin(self):
        self.execute("BEGIN")

    def commit(self):
        self.execute("COMMIT")

    def rollback(self):
        self.execute("ROLLBACK")

    def close(self):
        return object.__getattribute__(self, '_conn').close()


class _SQLite3Wrapper:
    def __init__(self, conn):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_is_apsw', False)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_conn'), name)

    def __setattr__(self, name, value):
        if name in ('_conn', '_is_apsw'):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, '_conn'), name, value)

    def cursor(self):
        return object.__getattribute__(self, '_conn').cursor()

    def execute(self, sql, *args):
        return object.__getattribute__(self, '_conn').execute(sql, *args)

    def begin(self):
        self.execute("BEGIN")

    def commit(self):
        self.execute("COMMIT")

    def rollback(self):
        self.execute("ROLLBACK")

    def close(self):
        return object.__getattribute__(self, '_conn').close()


def open_db(path):
    if _HAS_APSW:
        raw_conn = apsw.Connection(str(path))
        raw_conn.setbusytimeout(5000)
        conn = _APSWWrapper(raw_conn)
    else:
        import sqlite3
        raw_conn = sqlite3.connect(str(path), isolation_level=None)
        raw_conn.row_factory = sqlite3.Row
        conn = _SQLite3Wrapper(raw_conn)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")

    return conn
