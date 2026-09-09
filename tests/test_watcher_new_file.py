"""A file with no `files` row must still announce that the tracked set moved.

_do_process_change()'s "no rows" branch invalidated the cached scan and returned
without broadcasting, so nothing told a client to rescan: a newly created file
stayed invisible until some unrelated *tracked* file happened to change and
broadcast on its behalf -- which is why it showed up only sometimes. In nvim the
same gap surfaced as a 404 when opening the file.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from auditview.core.watcher import WatcherService
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


async def _seed_session(db_path, root, exclusion_patterns=""):
    async with open_db(db_path) as conn:
        await run_migrations(conn)
        await conn.execute(
            "INSERT INTO sessions (label, root_path, exclusion_patterns) "
            "VALUES ('t', ?, ?)",
            (root, exclusion_patterns),
        )


async def _next_event(q, timeout=10.0):
    try:
        return await asyncio.wait_for(q.get(), timeout)
    except asyncio.TimeoutError:
        return None


def _drain(q):
    while not q.empty():
        q.get_nowait()


@pytest.mark.asyncio
async def test_new_untracked_file_broadcasts_and_excluded_one_does_not():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        db_path = os.path.join(tmpdir, ".auditview.db")
        await _seed_session(db_path, tmpdir, exclusion_patterns="*.log")

        watcher = WatcherService(db_path, tmpdir)
        watcher.start(asyncio.get_running_loop())
        worker = asyncio.create_task(watcher.run_worker())
        try:
            # Registers the session's spec, so _handle_change filters as in production.
            await watcher.get_scan(1, tmpdir, "*.log")
            q = watcher.register_client(1)
            await asyncio.sleep(0.5)  # let the observer thread arm its watch

            with open(os.path.join(tmpdir, "new.py"), "w") as fh:
                fh.write("value = 1\n")

            # rel_path is None: the same "the tracked set moved" signal a forced
            # rescan sends, which is what FileTree rescans off.
            assert await _next_event(q) == {"type": "file_changed", "rel_path": None}

            await asyncio.sleep(0.8)
            _drain(q)

            with open(os.path.join(tmpdir, "debug.log"), "w") as fh:
                fh.write("noise\n")
            assert await _next_event(q, timeout=2.0) is None
        finally:
            watcher.stop()
            worker.cancel()
