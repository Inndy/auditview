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


class _ScanSuperseded(Exception):
    """Raised into waiters whose scan was invalidated mid-flight; they retry."""


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

    def on_moved(self, event):
        # inotify pairs IN_MOVED_FROM/IN_MOVED_TO into a single move event when
        # both ends are inside the watched tree, so an atomic save (write temp,
        # rename over the target) never reaches on_created/on_modified. Both
        # ends need processing: the source disappeared, the destination has new
        # content. Directory moves come with per-child sub-move events, and the
        # directory paths themselves resolve to no files rows, which just
        # invalidates the scan.
        self._svc._handle_change(event.src_path)
        self._svc._handle_change(event.dest_path)


class WatcherService:
    def __init__(self, db_path, root_path):
        self._db_path = db_path
        self._root_path = root_path
        self._observer = Observer()
        self._handler = _Handler(self)
        self._lock = threading.Lock()
        self._clients = {}
        self._scan_cache = {}
        self._scan_gen = {}
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

    def broadcast_all(self, event, *, drain_first=False):
        with self._lock:
            for sid, clients in self._clients.items():
                for q in list(clients):
                    if drain_first:
                        while not q.empty():
                            try:
                                q.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(
                            "watcher: dropping broadcast_all event for session %s (queue full, type=%s)",
                            sid, event.get("type"),
                        )

    def broadcast_to_session(self, session_id, event):
        with self._lock:
            for q in list(self._clients.get(session_id, [])):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "watcher: dropping event for session %s (queue full, type=%s)",
                        session_id, event.get("type"),
                    )

    async def get_scan(self, session_id, root_path, exclusion_patterns):
        patterns_str = exclusion_patterns or ""
        spec = _base_spec(patterns_str)
        loop = asyncio.get_running_loop()

        while True:
            with self._lock:
                self._session_specs[session_id] = (root_path, spec)
                gen = self._scan_gen.get(session_id, 0)
                cached = self._scan_cache.get(session_id)
                if cached is None:
                    # We win the race: plant a Future so concurrent callers wait on us.
                    fut = loop.create_future()
                    self._scan_cache[session_id] = fut
                    owner = True
                else:
                    fut = None
                    owner = False

            if not owner:
                if isinstance(cached, asyncio.Future):
                    try:
                        return await asyncio.shield(cached)
                    except _ScanSuperseded:
                        continue
                return cached

            try:
                result = await loop.run_in_executor(
                    None, scan_folder, root_path, patterns_str
                )
            except BaseException as exc:
                # BaseException so CancelledError doesn't leave a pending Future
                # cached forever — later callers would await it indefinitely.
                with self._lock:
                    if self._scan_cache.get(session_id) is fut:
                        self._scan_cache[session_id] = None
                if not fut.done():
                    fut.set_exception(exc if isinstance(exc, Exception) else asyncio.CancelledError())
                raise

            # A scan that straddled an invalidate_scan() saw pre-invalidation
            # state. Publishing it would undo the invalidation, and every caller
            # awaiting our Future would act on the stale list — which for a purge
            # means re-inserting the file that was just removed. Rescan instead.
            with self._lock:
                superseded = self._scan_gen.get(session_id, 0) != gen
                if not superseded:
                    self._scan_cache[session_id] = result
                elif self._scan_cache.get(session_id) is fut:
                    self._scan_cache[session_id] = None
            if not superseded:
                fut.set_result(result)
                return result
            if not fut.done():
                fut.set_exception(_ScanSuperseded())

    def invalidate_scan(self, session_id, spec=None):
        """Drop the cached scan for a session and retire any in-flight one.

        `spec` re-registers the session's filter for the watchdog thread; pass it
        whenever exclusion_patterns just changed, so _handle_change stops matching
        against the superseded one before the next scan lands.
        """
        with self._lock:
            self._bump_scan_gen(session_id)
            if spec is not None:
                root, _old = self._session_specs.get(session_id, (self._root_path, None))
                self._session_specs[session_id] = (root, spec)

    def _bump_scan_gen(self, session_id):
        """Invalidate a session's scan. Caller must hold _lock."""
        self._scan_cache[session_id] = None
        self._scan_gen[session_id] = self._scan_gen.get(session_id, 0) + 1

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
        try:
            loop.call_soon_threadsafe(self._enqueue_path, abs_path)
        except RuntimeError:
            # Loop closed between our check and the call — happens during
            # shutdown when watchdog threads still hold pending events.
            pass

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
                # Only an appearance is worth announcing. A path that is already
                # gone and never had a files row cannot have changed any
                # client's view, and an atomic save produces two of those (the
                # temp file's create, then the move's source side) for every one
                # real new file. The cached scan is invalidated either way.
                exists = os.path.exists(abs_path)
                bumped = []
                # Under one lock hold: _lock is not reentrant, so this uses the
                # caller-locked _bump_scan_gen rather than invalidate_scan().
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
                        self._bump_scan_gen(r["id"])
                        if exists:
                            bumped.append(r["id"])

                # A path with no files row that survived the session's spec is
                # one the next scan will adopt - usually a file just created.
                # Invalidating the cache is not enough on its own: no client
                # rescans until it is told to, so without this a new file stayed
                # invisible until some unrelated tracked file changed and
                # broadcast on its behalf, which is why it appeared only
                # sometimes. rel_path is None, the same "the tracked set moved"
                # signal a forced rescan sends; FileTree rescans off it and
                # CodeViewer ignores it. Outside the lock above -
                # broadcast_to_session takes the same non-reentrant _lock.
                for sid in bumped:
                    self.broadcast_to_session(
                        sid, {"type": "file_changed", "rel_path": None}
                    )
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
                        continue

                self.invalidate_scan(sid)
                self.broadcast_to_session(sid, {"type": "file_changed", "rel_path": rel_path})
