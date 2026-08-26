"""Regression tests for the P1 bug fixes.

Covers: session existence guards (#56, #62), OSError → JSON responses (#59, #64),
ensure_snapshot atomicity (#43), and WatcherService reliability fixes (#41, #44, #47).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from unittest import mock

import pytest
from quart import Quart

from auditview.api.config import bp as config_bp
from auditview.api.events import bp as events_bp
from auditview.api.files import bp as files_bp
from auditview.api.issues import bp as issues_bp
from auditview.api.notes import bp as notes_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.core.watcher import WatcherService
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations


class _StubWatcher:
    def broadcast_to_session(self, *a): pass
    def broadcast_all(self, *a, **kw): pass
    async def get_scan(self, *a): return []
    def invalidate_scan(self, *a, **kw): pass


@asynccontextmanager
async def _test_app():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmpdir
        app.watcher = _StubWatcher()
        for bp in (sessions_bp, files_bp, notes_bp, issues_bp, events_bp, config_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmpdir, db_path


async def _create_session(client, label="t"):
    resp = await client.post("/api/sessions", json={"label": label})
    assert resp.status_code == 201
    return (await resp.get_json())["id"]


def _write_file(root, rel, lines):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Session existence guards (#56, #62)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_issues_unknown_session_returns_404():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/9999/issues")
            assert resp.status_code == 404
            body = await resp.get_json()
            assert "error" in body


@pytest.mark.asyncio
async def test_list_issue_notes_unknown_session_returns_404():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/9999/issues/1/notes")
            assert resp.status_code == 404
            body = await resp.get_json()
            assert "error" in body


@pytest.mark.asyncio
async def test_update_issue_unknown_session_returns_404_not_issue_not_found():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            sid = await _create_session(client)
            # Create an issue under the real session
            r = await client.post(
                f"/api/sessions/{sid}/issues",
                json={"title": "t", "severity": "P2"},
            )
            issue_id = (await r.get_json())["id"]

            # PATCH with a wrong session_id — must get "session not found", not "issue not found"
            resp = await client.patch(
                f"/api/sessions/9999/issues/{issue_id}",
                json={"title": "new title"},
            )
            assert resp.status_code == 404
            body = await resp.get_json()
            assert body.get("error") == "session not found"


# ---------------------------------------------------------------------------
# OSError → JSON error responses (#59, #64)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_note_oserror_returns_json_500():
    async with _test_app() as (app, tmpdir, _db):
        fpath = _write_file(tmpdir, "src.py", ["x = 1", "y = 2"])
        async with app.test_client() as client:
            sid = await _create_session(client)
            with mock.patch("auditview.api.notes.read_file_lines", side_effect=OSError("no perms")):
                resp = await client.post(
                    f"/api/sessions/{sid}/notes",
                    json={
                        "file_path": "src.py",
                        "start_line": 1,
                        "end_line": 1,
                        "content": "note",
                    },
                )
            assert resp.status_code == 500
            body = await resp.get_json()
            assert body is not None and "error" in body


@pytest.mark.asyncio
async def test_get_file_oserror_returns_json_500():
    async with _test_app() as (app, tmpdir, db_path):
        fpath = _write_file(tmpdir, "src.py", ["x = 1"])
        real_mtime = os.path.getmtime(fpath)
        async with app.test_client() as client:
            sid = await _create_session(client)
            # Insert the file row with matching mtime so reconcile_file is skipped
            async with open_db(db_path) as conn:
                await conn.execute(
                    "INSERT INTO files (session_id, rel_path, last_mtime) VALUES (?, ?, ?)",
                    (sid, "src.py", real_mtime),
                )
            with mock.patch("auditview.api.files.read_file_lines", side_effect=OSError("no perms")):
                resp = await client.get(f"/api/sessions/{sid}/files/src.py")
            assert resp.status_code == 500
            body = await resp.get_json()
            assert body is not None and "error" in body


# ---------------------------------------------------------------------------
# ensure_snapshot atomicity: failed snapshot rolls back the note INSERT (#43)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_note_rolled_back_when_ensure_snapshot_raises():
    async with _test_app() as (app, tmpdir, db_path):
        _write_file(tmpdir, "src.py", ["x = 1", "y = 2"])
        async with app.test_client() as client:
            sid = await _create_session(client)
            with mock.patch(
                "auditview.api.notes.ensure_snapshot",
                side_effect=RuntimeError("simulated snapshot failure"),
            ):
                resp = await client.post(
                    f"/api/sessions/{sid}/notes",
                    json={
                        "file_path": "src.py",
                        "start_line": 1,
                        "end_line": 1,
                        "content": "note",
                    },
                )
            assert resp.status_code == 500
            # The note must NOT have been committed
            async with open_db(db_path) as conn:
                cur = await conn.execute(
                    "SELECT COUNT(*) AS n FROM notes WHERE session_id = ?", (sid,)
                )
                row = await cur.fetchone()
            assert row["n"] == 0, "note INSERT should have been rolled back"


# ---------------------------------------------------------------------------
# WatcherService: broadcast_all drain_first guarantees shutdown delivery (#41)
# ---------------------------------------------------------------------------

def _make_watcher():
    svc = object.__new__(WatcherService)
    svc._lock = threading.Lock()
    svc._clients = {}
    return svc


def test_broadcast_all_drain_first_delivers_on_full_queue():
    svc = _make_watcher()
    q = asyncio.Queue(maxsize=3)
    svc._clients[1] = [q]

    for i in range(3):
        q.put_nowait({"type": "fill", "i": i})
    assert q.full()

    svc.broadcast_all({"type": "shutdown"}, drain_first=True)

    assert not q.empty()
    item = q.get_nowait()
    assert item == {"type": "shutdown"}
    assert q.empty()


def test_broadcast_all_without_drain_drops_on_full_queue():
    svc = _make_watcher()
    q = asyncio.Queue(maxsize=2)
    svc._clients[1] = [q]
    q.put_nowait({"type": "a"})
    q.put_nowait({"type": "b"})

    svc.broadcast_all({"type": "should_drop"})  # queue full, no drain

    assert q.qsize() == 2
    assert q.get_nowait()["type"] == "a"
    assert q.get_nowait()["type"] == "b"


# ---------------------------------------------------------------------------
# WatcherService: broadcast_all fans out to all sessions (#44)
# ---------------------------------------------------------------------------

def test_broadcast_all_reaches_all_sessions():
    svc = _make_watcher()
    q1, q2 = asyncio.Queue(maxsize=4), asyncio.Queue(maxsize=4)
    svc._clients[1] = [q1]
    svc._clients[2] = [q2]

    svc.broadcast_all({"type": "shutdown"})

    assert q1.get_nowait() == {"type": "shutdown"}
    assert q2.get_nowait() == {"type": "shutdown"}


# ---------------------------------------------------------------------------
# WatcherService: get_scan concurrent calls run scan_folder only once (#47)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_scan_concurrent_calls_scan_once():
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = object.__new__(WatcherService)
        svc._lock = threading.Lock()
        svc._scan_cache = {}
        svc._scan_gen = {}
        svc._session_specs = {}

        call_count = 0

        def counting_scan(root_path, patterns):
            nonlocal call_count
            call_count += 1
            return ["a.py", "b.py"]

        with mock.patch("auditview.core.watcher.scan_folder", counting_scan):
            results = await asyncio.gather(
                svc.get_scan(42, tmpdir, ""),
                svc.get_scan(42, tmpdir, ""),
                svc.get_scan(42, tmpdir, ""),
            )

        assert call_count == 1, f"scan_folder ran {call_count} times, expected 1"
        assert all(r == ["a.py", "b.py"] for r in results)
