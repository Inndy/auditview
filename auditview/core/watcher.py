import os
import queue
import threading

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from auditview.db.connection import open_db
from auditview.core.reconciler import reconcile_file

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


class WatcherService:
    def __init__(self, db_path, root_path):
        self._db_path = db_path
        self._root_path = root_path
        self._observer = Observer()
        self._handler = _Handler(self)
        self._lock = threading.Lock()
        self._clients = {}
        self._conn = None

    def start(self):
        self._conn = open_db(self._db_path)
        self._observer.schedule(self._handler, self._root_path, recursive=True)
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join()
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

    def _handle_change(self, abs_path):
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

        for row in rows:
            sid = row[0] if is_apsw else row["session_id"]
            sess_root = row[1] if is_apsw else row["root_path"]
            try:
                reconcile_file(conn, sid, rel_path, sess_root)
            except Exception:
                pass

            event = {"type": "file_changed", "rel_path": rel_path}
            with self._lock:
                for q in list(self._clients.get(sid, [])):
                    try:
                        q.put_nowait(event)
                    except queue.Full:
                        pass
