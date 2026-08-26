"""Tests for mid-review file purging: PATCH /sessions/:id, /rescan flags, /purge."""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from quart import Quart

from auditview.api.files import bp as files_bp
from auditview.api.notes import bp as notes_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.core.reconciler import reconcile_file
from auditview.core.scanner import _base_spec, scan_folder
from auditview.core.watcher import WatcherService
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None

SECRET = "AKIAIOSFODNN7EXAMPLE_super_secret"


class _RealScanWatcher:
    """Exercises the real scan/cache path so exclusion changes actually bite."""

    def __init__(self, root_path):
        import threading
        self._lock = threading.Lock()
        self._scan_cache = {}
        self._scan_gen = {}
        self._session_specs = {}
        self._root_path = root_path
        self.events = []

    get_scan = WatcherService.get_scan
    invalidate_scan = WatcherService.invalidate_scan
    _bump_scan_gen = WatcherService._bump_scan_gen

    def broadcast_to_session(self, session_id, event):
        self.events.append((session_id, event))

    def broadcast_all(self, *a, **kw):
        pass


@asynccontextmanager
async def _test_app():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        db_path = os.path.join(tmpdir, ".auditview.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmpdir
        app.watcher = _RealScanWatcher(tmpdir)
        for bp in (sessions_bp, files_bp, notes_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmpdir, db_path


def _write(tmpdir, rel, text):
    full = os.path.join(tmpdir, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)
    return full


async def _mk_session(client, **kw):
    resp = await client.post("/api/sessions", json={"label": "s", **kw})
    return (await resp.get_json())["id"]


# =============================================================================
# PATCH /api/sessions/:id
# =============================================================================

@pytest.mark.asyncio
async def test_patch_updates_exclusion_patterns_and_rescan_drops_file():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "keep.py", "a = 1\n")
        _write(tmpdir, "junk.log", "noise\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            files = await (await client.post(f"/api/sessions/{sid}/rescan")).get_json()
            assert {f["rel_path"] for f in files} >= {"keep.py", "junk.log"}

            resp = await client.patch(f"/api/sessions/{sid}", json={"exclusion_patterns": "*.log"})
            assert resp.status_code == 200
            assert (await resp.get_json())["exclusion_patterns"] == "*.log"

            files = await (await client.post(f"/api/sessions/{sid}/rescan?force=1")).get_json()
            paths = {f["rel_path"] for f in files}
            assert "junk.log" not in paths
            assert "keep.py" in paths


@pytest.mark.asyncio
async def test_patch_rejects_unparseable_pattern():
    """A bad pattern in the DB would raise on every later scan with no way back."""
    async with _test_app() as (app, tmpdir, _):
        async with app.test_client() as client:
            sid = await _mk_session(client)
            resp = await client.patch(f"/api/sessions/{sid}", json={"exclusion_patterns": "trail\\"})
            assert resp.status_code == 400
            resp = await client.get("/api/sessions")
            assert (await resp.get_json())[0]["exclusion_patterns"] == ""
            assert (await client.post(f"/api/sessions/{sid}/rescan?force=1")).status_code == 200


@pytest.mark.asyncio
async def test_patch_validation_and_404():
    async with _test_app() as (app, tmpdir, _):
        async with app.test_client() as client:
            sid = await _mk_session(client)
            assert (await client.patch(f"/api/sessions/{sid}", json={})).status_code == 400
            assert (await client.patch(f"/api/sessions/{sid}", json={"label": "  "})).status_code == 400
            assert (await client.patch(f"/api/sessions/{sid}", json={"exclusion_patterns": 5})).status_code == 400
            assert (await client.patch("/api/sessions/999", json={"label": "x"})).status_code == 404
            resp = await client.patch(f"/api/sessions/{sid}", json={"label": "renamed"})
            assert (await resp.get_json())["label"] == "renamed"


# =============================================================================
# POST /api/sessions/:id/purge
# =============================================================================

@pytest.mark.asyncio
async def test_purge_hard_deletes_notes_and_scrubs_db():
    async with _test_app() as (app, tmpdir, db_path):
        _write(tmpdir, "secrets.env", f"token = {SECRET}\n")
        _write(tmpdir, "keep.py", "a = 1\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            resp = await client.post(f"/api/sessions/{sid}/notes", json={
                "file_path": "secrets.env", "start_line": 1, "end_line": 1, "content": "leaked cred",
            })
            assert resp.status_code == 201

            with open(db_path, "rb") as f:
                assert SECRET.encode() in f.read(), "precondition: snapshot_text should hold the line"

            resp = await client.post(f"/api/sessions/{sid}/purge", json={"path": "secrets.env"})
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["purged_paths"] == ["secrets.env"]
            assert body["purged_notes"] == 1
            assert body["vacuumed"] is True
            assert "/secrets.env" in body["exclusion_patterns"]
            assert {f["rel_path"] for f in body["files"]} == {"keep.py"}

        async with open_db(db_path) as conn:
            cur = await conn.execute("SELECT COUNT(*) c FROM notes WHERE file_path = 'secrets.env'")
            assert (await cur.fetchone())["c"] == 0

        with open(db_path, "rb") as f:
            assert SECRET.encode() not in f.read(), "VACUUM did not reclaim the freed pages"
        wal = db_path + "-wal"
        if os.path.exists(wal):
            with open(wal, "rb") as f:
                assert SECRET.encode() not in f.read()


@pytest.mark.asyncio
async def test_purge_survives_rescan():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "secrets.env", "token = x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            await client.post(f"/api/sessions/{sid}/purge", json={"path": "secrets.env"})
            for qs in ("", "?force=1"):
                files = await (await client.post(f"/api/sessions/{sid}/rescan{qs}")).get_json()
                assert "secrets.env" not in {f["rel_path"] for f in files}, f"came back on rescan{qs}"


@pytest.mark.asyncio
async def test_purge_directory_subtree():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "vendor/a.js", "1\n")
        _write(tmpdir, "vendor/deep/b.js", "2\n")
        _write(tmpdir, "vendorish/c.js", "3\n")
        _write(tmpdir, "src/vendor/d.js", "4\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            body = await (await client.post(f"/api/sessions/{sid}/purge", json={"path": "vendor"})).get_json()
            assert body["purged_paths"] == ["vendor/a.js", "vendor/deep/b.js"]
            assert {f["rel_path"] for f in body["files"]} == {"vendorish/c.js", "src/vendor/d.js"}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["a[1].c", "a*b.c", "we?rd.c", "hash#tag.c", "!bang.c"])
async def test_purge_escapes_pattern_metacharacters(name):
    """The appended pattern must match exactly the purged path and nothing else."""
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, name, "x\n")
        _write(tmpdir, "aXb.c", "x\n")
        _write(tmpdir, "a1.c", "x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            resp = await client.post(f"/api/sessions/{sid}/purge", json={"path": name})
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["purged_paths"] == [name]

            spec = _base_spec(body["exclusion_patterns"])
            assert spec.match_file(name)
            assert not spec.match_file("aXb.c")
            assert not spec.match_file("a1.c")
            remaining = set(scan_folder(tmpdir, body["exclusion_patterns"]))
            assert name not in remaining
            assert {"aXb.c", "a1.c"} <= remaining


@pytest.mark.asyncio
async def test_purge_rejects_paths_that_cannot_be_expressed_as_a_pattern():
    async with _test_app() as (app, tmpdir, _):
        async with app.test_client() as client:
            sid = await _mk_session(client)
            for bad in ["a\nb.txt", "a\rb.txt", "trail.txt ", " lead.txt", "", "/", ".", ".."]:
                resp = await client.post(f"/api/sessions/{sid}/purge", json={"path": bad})
                assert resp.status_code == 400, f"{bad!r} was accepted"
            resp = await client.post(f"/api/sessions/{sid}/purge", json={"path": "../escape.txt"})
            assert resp.status_code == 400
            assert (await client.post(f"/api/sessions/{sid}/purge", json={})).status_code == 400
            assert (await client.post("/api/sessions/999/purge", json={"path": "a"})).status_code == 404


@pytest.mark.asyncio
async def test_purge_untracked_path_still_records_the_pattern():
    async with _test_app() as (app, tmpdir, _):
        async with app.test_client() as client:
            sid = await _mk_session(client)
            resp = await client.post(f"/api/sessions/{sid}/purge", json={"path": "not/here.txt"})
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["purged_paths"] == []
            assert "/not/here.txt" in body["exclusion_patterns"]


@pytest.mark.asyncio
async def test_purge_is_idempotent():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "a.txt", "x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            first = await (await client.post(f"/api/sessions/{sid}/purge", json={"path": "a.txt"})).get_json()
            second = await (await client.post(f"/api/sessions/{sid}/purge", json={"path": "a.txt"})).get_json()
            assert first["exclusion_patterns"] == second["exclusion_patterns"]
            assert second["purged_paths"] == []


@pytest.mark.asyncio
async def test_purge_sweeps_row_resurrected_by_the_watcher():
    """reconcile_file's UPSERT can re-create a files row after the delete."""
    async with _test_app() as (app, tmpdir, db_path):
        _write(tmpdir, "secrets.env", "token = x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            async with open_db(db_path) as conn:
                await conn.execute("DELETE FROM files WHERE session_id = ? AND rel_path = ?", (sid, "secrets.env"))
                await reconcile_file(conn, sid, "secrets.env", tmpdir)
                cur = await conn.execute("SELECT COUNT(*) c FROM files WHERE rel_path = 'secrets.env'")
                assert (await cur.fetchone())["c"] == 1, "precondition: UPSERT resurrects the row"

            body = await (await client.post(f"/api/sessions/{sid}/purge", json={"path": "secrets.env"})).get_json()
            assert {f["rel_path"] for f in body["files"]} == set()
        async with open_db(db_path) as conn:
            cur = await conn.execute("SELECT COUNT(*) c FROM files WHERE rel_path = 'secrets.env'")
            assert (await cur.fetchone())["c"] == 0


@pytest.mark.asyncio
async def test_purge_broadcasts_file_changed_only():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "a.txt", "x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            await client.post(f"/api/sessions/{sid}/notes", json={
                "file_path": "a.txt", "start_line": 1, "end_line": 1, "content": "n",
            })
            app.watcher.events.clear()
            await client.post(f"/api/sessions/{sid}/purge", json={"path": "a.txt"})
            events = [e for _sid, e in app.watcher.events]
            assert {"type": "file_changed", "rel_path": "a.txt"} in events
            # annotation_changed is deliberately not sent: its consumers dispatch
            # on a per-note kind/action/id payload a purge cannot supply.
            assert not any(e["type"] == "annotation_changed" for e in events)


# =============================================================================
# rescan flags
# =============================================================================

@pytest.mark.asyncio
async def test_rescan_force_picks_up_gitignore_edits():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "keep.py", "a = 1\n")
        _write(tmpdir, "build/out.o", "x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            files = await (await client.post(f"/api/sessions/{sid}/rescan")).get_json()
            assert "build/out.o" in {f["rel_path"] for f in files}

            _write(tmpdir, ".gitignore", "build/\n")
            cached = await (await client.post(f"/api/sessions/{sid}/rescan")).get_json()
            assert "build/out.o" in {f["rel_path"] for f in cached}, "cache should hide the edit"

            forced = await (await client.post(f"/api/sessions/{sid}/rescan?force=1")).get_json()
            assert "build/out.o" not in {f["rel_path"] for f in forced}


@pytest.mark.asyncio
async def test_rescan_returns_a_bare_array_whatever_the_flags():
    async with _test_app() as (app, tmpdir, _):
        _write(tmpdir, "a.txt", "x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            for qs in ("", "?force=1", "?purge=1", "?force=1&purge=1"):
                body = await (await client.post(f"/api/sessions/{sid}/rescan{qs}")).get_json()
                assert isinstance(body, list), f"rescan{qs} broke the array contract"


@pytest.mark.asyncio
async def test_rescan_purge_only_hard_deletes_excluded_not_merely_missing():
    """A file that vanished from disk keeps recoverable notes; an excluded one does not."""
    async with _test_app() as (app, tmpdir, db_path):
        _write(tmpdir, "gone.py", "a = 1\n")
        _write(tmpdir, "junk.log", "noise\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            for path in ("gone.py", "junk.log"):
                await client.post(f"/api/sessions/{sid}/notes", json={
                    "file_path": path, "start_line": 1, "end_line": 1, "content": "n",
                })

            os.remove(os.path.join(tmpdir, "gone.py"))
            await client.patch(f"/api/sessions/{sid}", json={"exclusion_patterns": "*.log"})
            resp = await client.post(f"/api/sessions/{sid}/rescan?purge=1")
            assert resp.status_code == 200

        async with open_db(db_path) as conn:
            cur = await conn.execute("SELECT file_path, is_orphaned FROM notes")
            rows = [(r["file_path"], r["is_orphaned"]) for r in await cur.fetchall()]
        assert rows == [("gone.py", 1)], f"expected only the missing file's note to survive, got {rows}"


@pytest.mark.asyncio
async def test_plain_rescan_orphans_rather_than_deletes():
    async with _test_app() as (app, tmpdir, db_path):
        _write(tmpdir, "junk.log", "noise\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            await client.post(f"/api/sessions/{sid}/notes", json={
                "file_path": "junk.log", "start_line": 1, "end_line": 1, "content": "n",
            })
            await client.patch(f"/api/sessions/{sid}", json={"exclusion_patterns": "*.log"})
            await client.post(f"/api/sessions/{sid}/rescan?force=1")

        async with open_db(db_path) as conn:
            cur = await conn.execute("SELECT is_orphaned FROM notes WHERE file_path = 'junk.log'")
            row = await cur.fetchone()
        assert row is not None and row["is_orphaned"] == 1


@pytest.mark.asyncio
async def test_write_paths_cannot_resurrect_a_purged_file():
    """The file is still on disk, so a stale client could otherwise mark it back in."""
    from auditview.api.lines import bp as lines_bp

    async with _test_app() as (app, tmpdir, db_path):
        app.register_blueprint(lines_bp, url_prefix="/api")
        _write(tmpdir, "secrets.env", "token = x\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")
            await client.post(f"/api/sessions/{sid}/purge", json={"path": "secrets.env"})

            resp = await client.post(f"/api/sessions/{sid}/notes", json={
                "file_path": "secrets.env", "start_line": 1, "end_line": 1, "content": "n",
            })
            assert resp.status_code == 409

            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "secrets.env", "reviewed": True,
                "lines": [{"line_no": 1, "line_hash": "x", "context_hash": "y"}],
            })
            assert resp.status_code == 409

        async with open_db(db_path) as conn:
            cur = await conn.execute("SELECT COUNT(*) c FROM files WHERE rel_path = 'secrets.env'")
            assert (await cur.fetchone())["c"] == 0
            cur = await conn.execute("SELECT COUNT(*) c FROM notes WHERE file_path = 'secrets.env'")
            assert (await cur.fetchone())["c"] == 0


@pytest.mark.asyncio
async def test_create_session_rejects_unparseable_pattern():
    """Same permanent-500 hazard as PATCH: validate before it reaches the table."""
    async with _test_app() as (app, tmpdir, _):
        async with app.test_client() as client:
            resp = await client.post("/api/sessions", json={"label": "s", "exclusion_patterns": "oops\\"})
            assert resp.status_code == 400
            assert (await client.get("/api/sessions")).status_code == 200
