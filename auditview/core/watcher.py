import asyncio
import logging
import os
import threading

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from auditview.db.connection import open_db
from auditview.core.reconciler import reconcile_file
from auditview.core.scanner import scan_folder, _base_spec

logger = logging.getLogger("auditview")

_CLIENT_QUEUE_SIZE = 128
_DEBOUNCE_DELAY = 0.3
_DEFAULT_FILTER_SPEC = _base_spec("")


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher_service):
        self._svc = watcher_service

    def on_modified(self, event):
        if not event.is_directory:
            self._svc._handle_change(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._svc._handle_change(event.src_path)

    def on_deleted(self, event):
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
        self._scan_cache = {}
        self._session_specs = {}
        self._pending_paths = set()
        self._debounce_handle = None
        self._loop = None
        self._work_queue = None

    def start(self, loop):
        self._loop = loop
        self._work_queue = asyncio.Queue()
        self._observer.schedule(self._handler, self._root_path, recursive=True)
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._cancel_debounce)

    def _cancel_debounce(self):
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None
        self._pending_paths.clear()

    async def run_worker(self):
        while True:
            abs_path = await self._work_queue.get()
            try:
                await self._do_process_change(abs_path)
            except Exception:
                logger.exception("watcher: failed to process change for %s", abs_path)

    def register_client(self, session_id):
        q = asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
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

    def broadcast(self, event):
        with self._lock:
            for clients in self._clients.values():
                for q in list(clients):
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass

    def broadcast_to_session(self, session_id, event):
        with self._lock:
            for q in list(self._clients.get(session_id, [])):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    async def get_scan(self, session_id, root_path, exclusion_patterns):
        patterns_str = exclusion_patterns or ""
        spec = _base_spec(patterns_str)
        with self._lock:
            self._session_specs[session_id] = (root_path, spec)
            cached = self._scan_cache.get(session_id)
        if cached is not None:
            return cached
        result = await asyncio.get_running_loop().run_in_executor(
            None, scan_folder, root_path, exclusion_patterns
        )
        with self._lock:
            self._scan_cache[session_id] = result
        return result

    def _handle_change(self, abs_path):
        # Runs on a watchdog observer thread. Filter against default excludes
        # here so bursts of writes to .git/, node_modules/, __pycache__/, etc.
        # never reach the asyncio loop or the DB.
        if not abs_path.startswith(self._root_path + os.sep) and abs_path != self._root_path:
            return
        rel_path = os.path.relpath(abs_path, self._root_path).replace(os.sep, "/")
        if _DEFAULT_FILTER_SPEC.match_file(rel_path):
            return

        # Drop paths excluded by every session that would otherwise cover them.
        # Sessions appear here only after get_scan has cached their spec; if none
        # are known yet we conservatively let the event through.
        with self._lock:
            specs = list(self._session_specs.values())
        if specs:
            covered = False
            kept = False
            for sess_root, spec in specs:
                if abs_path != sess_root and not abs_path.startswith(sess_root + os.sep):
                    continue
                covered = True
                sess_rel = os.path.relpath(abs_path, sess_root).replace(os.sep, "/")
                if not spec.match_file(sess_rel):
                    kept = True
                    break
            if covered and not kept:
                return

        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._enqueue_path, abs_path)

    def _enqueue_path(self, abs_path):
        # Runs on the asyncio loop. Coalesce repeated events for the same path
        # into a single set, and run one shared debounce timer instead of one
        # threading.Timer per path.
        self._pending_paths.add(abs_path)
        if self._debounce_handle is None:
            self._debounce_handle = self._loop.call_later(
                _DEBOUNCE_DELAY, self._flush_pending
            )

    def _flush_pending(self):
        self._debounce_handle = None
        paths = self._pending_paths
        self._pending_paths = set()
        for p in paths:
            self._work_queue.put_nowait(p)

    async def _do_process_change(self, abs_path):
        if not abs_path.startswith(self._root_path + os.sep):
            return
        rel_path = os.path.relpath(abs_path, self._root_path).replace(os.sep, "/")

        async with open_db(self._db_path) as conn:
            cur = await conn.execute(
                "SELECT DISTINCT f.session_id, s.root_path "
                "FROM files f JOIN sessions s ON s.id = f.session_id "
                "WHERE f.rel_path = ?",
                (rel_path,),
            )
            rows = await cur.fetchall()

            if not rows:
                cur2 = await conn.execute("SELECT id, root_path FROM sessions")
                session_rows = await cur2.fetchall()
                with self._lock:
                    for r in session_rows:
                        sess_root = r["root_path"]
                        if not (abs_path.startswith(sess_root + os.sep) or abs_path.startswith(sess_root + "/")):
                            continue
                        entry = self._session_specs.get(r["id"])
                        if entry is not None:
                            spec_root, spec = entry
                            sess_rel = os.path.relpath(abs_path, spec_root).replace(os.sep, "/")
                            if spec.match_file(sess_rel):
                                continue
                        self._scan_cache[r["id"]] = None
                return

            file_deleted = not os.path.isfile(abs_path)
            for row in rows:
                sid = row["session_id"]
                sess_root = row["root_path"]
                if file_deleted:
                    try:
                        await conn.execute("BEGIN")
                        await conn.execute(
                            "UPDATE notes SET is_orphaned = 1 WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
                            (sid, rel_path),
                        )
                        await conn.execute(
                            "DELETE FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
                            (sid, rel_path),
                        )
                        await conn.execute(
                            "DELETE FROM files WHERE session_id = ? AND rel_path = ?",
                            (sid, rel_path),
                        )
                        await conn.execute("COMMIT")
                    except Exception:
                        await conn.execute("ROLLBACK")
                        logger.exception(
                            "watcher: failed to clean up deleted file %s (session %s)",
                            rel_path, sid,
                        )
                else:
                    try:
                        await reconcile_file(conn, sid, rel_path, sess_root)
                    except Exception:
                        logger.exception(
                            "watcher: reconcile_file failed for %s (session %s)",
                            rel_path, sid,
                        )

                with self._lock:
                    self._scan_cache[sid] = None
                self.broadcast_to_session(sid, {"type": "file_changed", "rel_path": rel_path})
