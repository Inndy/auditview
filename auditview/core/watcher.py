import os
import queue
import threading

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from auditview.db.connection import open_db
from auditview.core.reconciler import reconcile_file
from auditview.core.scanner import scan_folder

_CLIENT_QUEUE_SIZE = 128


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher_service):
        self._svc = watcher_service

    def on_modified(self, event):
        if not event.is_directory:
            self._svc._handle_change(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._svc._handle_change(event.src_path)


_DEBOUNCE_DELAY = 0.3  # seconds


class WatcherService:
    def __init__(self, db_path, root_path):
        self._db_path = db_path
        self._root_path = root_path
        self._observer = Observer()
        self._handler = _Handler(self)
        self._lock = threading.Lock()
        self._clients = {}
        self._scan_cache = {}  # session_id → list[str] | None (None = invalid)
        self._debounce_timers = {}  # abs_path → Timer
        self._conn = None

    def start(self):
        self._conn = open_db(self._db_path)
        self._observer.schedule(self._handler, self._root_path, recursive=True)
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join()
        with self._lock:
            for t in self._debounce_timers.values():
                t.cancel()
            self._debounce_timers.clear()
        if self._conn:
            self._conn.close()
            self._conn = None

    def register_client(self, session_id):
        q = queue.Queue(maxsize=_CLIENT_QUEUE_SIZE)
        with self._lock:
            if session_id not in self._clients:
                self._clients[session_id] = []
            self._clients[session_id].append(q)
        return q

    def unregister_client(self, session_id, q):
        with self._lock:
            if session_id in self._clients:
                try:
                    self._clients[session_id].remove(q)
                except ValueError:
                    pass

    def get_scan(self, session_id, root_path, exclusion_patterns):
        with self._lock:
            cached = self._scan_cache.get(session_id)
        if cached is not None:
            return cached
        result = scan_folder(root_path, exclusion_patterns)
        with self._lock:
            self._scan_cache[session_id] = result
        return result

    def _handle_change(self, abs_path):
        with self._lock:
            existing = self._debounce_timers.pop(abs_path, None)
            if existing:
                existing.cancel()
            t = threading.Timer(_DEBOUNCE_DELAY, self._process_change, args=(abs_path,))
            self._debounce_timers[abs_path] = t
        t.start()

    def _process_change(self, abs_path):
        with self._lock:
            self._debounce_timers.pop(abs_path, None)
        if not abs_path.startswith(self._root_path):
            return
        rel_path = os.path.relpath(abs_path, self._root_path).replace(os.sep, "/")

        conn = self._conn
        is_apsw = getattr(conn, '_is_apsw', False)
        cur = conn.cursor()

        rows = cur.execute(
            "SELECT DISTINCT f.session_id, s.root_path "
            "FROM files f JOIN sessions s ON s.id = f.session_id "
            "WHERE f.rel_path = ?",
            (rel_path,),
        ).fetchall()

        if not rows:
            # New file not yet tracked — invalidate scan cache for any session
            # whose root contains this path so list_files picks it up.
            session_rows = cur.execute("SELECT id, root_path FROM sessions").fetchall()
            with self._lock:
                for r in session_rows:
                    sid = r[0] if is_apsw else r["id"]
                    root = r[1] if is_apsw else r["root_path"]
                    if abs_path.startswith(root + os.sep) or abs_path.startswith(root + "/"):
                        self._scan_cache[sid] = None
            return

        for row in rows:
            sid = row[0] if is_apsw else row["session_id"]
            sess_root = row[1] if is_apsw else row["root_path"]
            try:
                reconcile_file(conn, sid, rel_path, sess_root)
            except Exception:
                pass

            event = {"type": "file_changed", "rel_path": rel_path}
            with self._lock:
                self._scan_cache[sid] = None
                for q in list(self._clients.get(sid, [])):
                    try:
                        q.put_nowait(event)
                    except queue.Full:
                        pass
