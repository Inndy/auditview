"""A root reached through a symlink must still match the observer's own paths.

macOS FSEvents reports realpath'd paths -- a watch on /var/folders/x reports
/private/var/folders/x back -- and on macOS both /tmp and /var *are* symlinks,
which is where tempfile puts its directories. An unresolved root therefore
matched no event at all: the watcher armed, saw every write, and dropped all of
them on the prefix check. That is why test_watcher_moved and
test_watcher_new_file failed natively on macOS while passing in a Linux
container, where tempfile hands out an already-resolved path.

Linux inotify builds its event paths from the watch path it was given, so it
cannot reproduce the divergence through a real observer. These tests drive the
change paths directly with a resolved path against a symlinked root, which pins
the contract on every platform.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from auditview.core.hashing import context_hash, line_hash
from auditview.core.progress import file_progress
from auditview.core.reconciler import ensure_snapshot
from auditview.core.watcher import WatcherService
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None

_LINES = ["alpha = 1", "beta = 2", "gamma = 3", "delta = 4"]


class _Tree:
    """A session root that is a symlink to the directory holding the files."""

    def __init__(self, tmpdir):
        self.real = os.path.join(tmpdir, "repo")
        os.mkdir(self.real)
        self.link = os.path.join(tmpdir, "link")
        os.symlink(self.real, self.link)
        self.db_path = os.path.join(tmpdir, "test.db")
        # What an observer on `link` reports on macOS, and what these tests feed
        # in: the resolved spelling.
        self.resolved = os.path.realpath(self.link)

    def write(self, rel, lines):
        with open(os.path.join(self.real, rel), "w") as fh:
            fh.write("\n".join(lines))

    def event_path(self, rel):
        return os.path.join(self.resolved, rel)


async def _seed(tree, rel=None):
    async with open_db(tree.db_path) as conn:
        await run_migrations(conn)
        # The session records the root as the user spelled it -- unresolved.
        await conn.execute(
            "INSERT INTO sessions (label, root_path, exclusion_patterns) "
            "VALUES ('t', ?, '*.log')",
            (tree.link,),
        )
        if rel is None:
            return
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
        await ensure_snapshot(conn, 1, rel, tree.link)
        assert (await file_progress(conn, 1))[0]["coverage"] == 1.0


def test_root_path_is_resolved():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        tree = _Tree(tmpdir)
        # start() schedules the watch on this, so it decides the spelling every
        # event arrives in.
        assert WatcherService(tree.db_path, tree.link)._root_path == tree.resolved


@pytest.mark.asyncio
async def test_handle_change_accepts_a_resolved_event_path():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        tree = _Tree(tmpdir)
        tree.write("a.py", _LINES)
        await _seed(tree)

        watcher = WatcherService(tree.db_path, tree.link)
        # No observer: these are the calls a watchdog thread would make, and a
        # real one on Linux would also queue events for the writes above.
        watcher._loop = asyncio.get_running_loop()
        watcher._work_queue = asyncio.Queue()
        # Registers the session's spec, so _handle_change filters as in production.
        await watcher.get_scan(1, tree.link, "*.log")

        watcher._handle_change(tree.event_path("a.py"))
        watcher._handle_change(tree.event_path("debug.log"))
        await asyncio.sleep(0.5)  # the shared debounce timer

        queued = []
        while not watcher._work_queue.empty():
            queued.append(watcher._work_queue.get_nowait())
        # The session's own exclusion still applies to the resolved spelling.
        assert queued == [tree.event_path("a.py")]


@pytest.mark.asyncio
async def test_resolved_event_path_reconciles_a_tracked_file():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        tree = _Tree(tmpdir)
        tree.write("a.py", _LINES)
        await _seed(tree, "a.py")

        watcher = WatcherService(tree.db_path, tree.link)
        q = watcher.register_client(1)

        tree.write("a.py", [*_LINES, "epsilon = 5", "zeta = 6"])
        await watcher._do_process_change(tree.event_path("a.py"))

        async with open_db(tree.db_path) as conn:
            progress = (await file_progress(conn, 1))[0]
        assert progress["countable_lines"] == 6
        assert progress["coverage"] < 1.0
        assert progress["status"] == "partial"
        # rel_path stays relative to the root, in the spelling clients know.
        assert q.get_nowait() == {"type": "file_changed", "rel_path": "a.py"}


@pytest.mark.asyncio
async def test_resolved_event_path_announces_an_untracked_new_file():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        tree = _Tree(tmpdir)
        await _seed(tree)

        watcher = WatcherService(tree.db_path, tree.link)
        await watcher.get_scan(1, tree.link, "*.log")
        q = watcher.register_client(1)

        tree.write("new.py", ["value = 1"])
        await watcher._do_process_change(tree.event_path("new.py"))
        assert q.get_nowait() == {"type": "file_changed", "rel_path": None}

        # Excluded by the session's own patterns: invisible, so nothing to say.
        tree.write("debug.log", ["noise"])
        await watcher._do_process_change(tree.event_path("debug.log"))
        assert q.empty()
