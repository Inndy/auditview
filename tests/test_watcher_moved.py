"""An atomic save (write temp + rename) must reconcile like an in-place write.

inotify pairs IN_MOVED_FROM/IN_MOVED_TO into one move event when both ends sit
inside the watched tree, so watchdog delivers on_moved and never
on_created/on_modified. A handler that ignores it leaves reviewed_lines and
countable_lines frozen at the pre-edit values -- a fully reviewed file keeps
reporting 100% after being edited.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from auditview.core.hashing import context_hash, line_hash
from auditview.core.progress import file_progress
from auditview.core.reconciler import ensure_snapshot
from auditview.core.watcher import WatcherService, _Handler
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None

_LINES = ["alpha = 1", "beta = 2", "gamma = 3", "delta = 4"]


class _StubEvent:
    def __init__(self, src_path, dest_path, is_directory=False):
        self.src_path = src_path
        self.dest_path = dest_path
        self.is_directory = is_directory


class _RecordingService:
    def __init__(self):
        self.seen = []

    def _handle_change(self, abs_path):
        self.seen.append(abs_path)


def test_on_moved_dispatches_both_ends():
    svc = _RecordingService()
    _Handler(svc).on_moved(_StubEvent("/root/a.py.tmp", "/root/a.py"))
    assert svc.seen == ["/root/a.py.tmp", "/root/a.py"]


async def _seed(db_path, root, rel):
    async with open_db(db_path) as conn:
        await run_migrations(conn)
        await conn.execute(
            "INSERT INTO sessions (label, root_path) VALUES ('t', ?)", (root,)
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path) VALUES (1, ?)", (rel,)
        )
        for i, content in enumerate(_LINES):
            prev = _LINES[i - 1] if i > 0 else ""
            nxt = _LINES[i + 1] if i < len(_LINES) - 1 else ""
            await conn.execute(
                "INSERT INTO reviewed_lines "
                "(session_id, file_path, line_hash, context_hash, line_no) "
                "VALUES (1, ?, ?, ?, ?)",
                (rel, line_hash(content), context_hash(prev, content, nxt), i + 1),
            )
        await ensure_snapshot(conn, 1, rel, root)
        progress = (await file_progress(conn, 1))[0]
    assert progress["coverage"] == 1.0


async def _await_countable(db_path, expected, timeout=10.0):
    deadline = 0.0
    while deadline < timeout:
        async with open_db(db_path) as conn:
            progress = (await file_progress(conn, 1))[0]
        if progress["countable_lines"] == expected:
            return progress
        await asyncio.sleep(0.2)
        deadline += 0.2
    return progress


@pytest.mark.asyncio
async def test_atomic_rename_save_reconciles_coverage():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        rel = "a.py"
        target = os.path.join(tmpdir, rel)
        with open(target, "w") as fh:
            fh.write("\n".join(_LINES))

        await _seed(db_path, tmpdir, rel)

        watcher = WatcherService(db_path, tmpdir)
        watcher.start(asyncio.get_running_loop())
        worker = asyncio.create_task(watcher.run_worker())
        try:
            await asyncio.sleep(0.5)  # let the observer thread arm its watch

            staging = os.path.join(tmpdir, "a.py.new")
            with open(staging, "w") as fh:
                fh.write("\n".join([*_LINES, "epsilon = 5", "zeta = 6"]))
            os.replace(staging, target)

            progress = await _await_countable(db_path, 6)
        finally:
            watcher.stop()
            worker.cancel()

        assert progress["countable_lines"] == 6
        assert progress["coverage"] < 1.0
        assert progress["status"] == "partial"
