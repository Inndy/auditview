"""Tests for api/lines.py — mark/unmark lines endpoint."""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from unittest import mock

import pytest
from quart import Quart

from auditview.api.lines import bp as lines_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.core.hashing import context_hash, line_hash
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


class _StubWatcher:
    def broadcast_to_session(self, *a): pass
    def broadcast_all(self, *a, **kw): pass
    async def get_scan(self, *a): return []


@asynccontextmanager
async def _test_app():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmpdir
        app.watcher = _StubWatcher()
        for bp in (sessions_bp, lines_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmpdir, db_path


def _write_file(root, rel, lines):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


def _line_payload(lines, reviewed=True):
    result = []
    for i, content in enumerate(lines):
        prev = lines[i - 1] if i > 0 else ""
        nxt = lines[i + 1] if i < len(lines) - 1 else ""
        result.append({
            "line_no": i + 1,
            "line_hash": line_hash(content),
            "context_hash": context_hash(prev, content, nxt),
        })
    return result


async def _create_session(client, label="t"):
    resp = await client.post("/api/sessions", json={"label": label})
    assert resp.status_code == 201
    return (await resp.get_json())["id"]


# ---------------------------------------------------------------------------
# Session / path validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_unknown_session_returns_404():
    async with _test_app() as (app, root, _):
        async with app.test_client() as client:
            resp = await client.post("/api/sessions/9999/lines/mark", json={
                "file_path": "x.py", "lines": [], "reviewed": True,
            })
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_missing_fields_returns_400():
    async with _test_app() as (app, root, _):
        async with app.test_client() as client:
            sid = await _create_session(client)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={})
            assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mark_lines_not_array_returns_400():
    async with _test_app() as (app, root, _):
        async with app.test_client() as client:
            sid = await _create_session(client)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "a.py", "lines": "not-a-list", "reviewed": True,
            })
            assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mark_path_traversal_returns_400():
    async with _test_app() as (app, root, _):
        async with app.test_client() as client:
            sid = await _create_session(client)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "../../etc/passwd", "lines": [], "reviewed": True,
            })
            assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mark_nonexistent_file_returns_404():
    async with _test_app() as (app, root, _):
        async with app.test_client() as client:
            sid = await _create_session(client)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "ghost.py", "lines": [], "reviewed": True,
            })
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Marking lines as reviewed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_lines_reviewed_success():
    async with _test_app() as (app, root, db_path):
        file_lines = ["alpha", "beta", "gamma"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            payload = _line_payload(file_lines)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py",
                "lines": payload,
                "reviewed": True,
            })
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["updated"] == 3
            assert len(body["accepted"]) == 3
            assert body["rejected"] == []

        async with open_db(db_path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) AS n FROM reviewed_lines WHERE session_id = ? AND file_path = 'app.py'",
                (sid,),
            )
            row = await cur.fetchone()
            assert row["n"] == 3


@pytest.mark.asyncio
async def test_mark_lines_reviewed_creates_snapshot():
    async with _test_app() as (app, root, db_path):
        file_lines = ["line1", "line2"]
        _write_file(root, "src.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "src.py",
                "lines": _line_payload(file_lines),
                "reviewed": True,
            })

        async with open_db(db_path) as conn:
            cur = await conn.execute(
                "SELECT prev_line_hashes FROM files WHERE session_id = ? AND rel_path = 'src.py'",
                (sid,),
            )
            row = await cur.fetchone()
            assert row is not None
            assert row["prev_line_hashes"] is not None


@pytest.mark.asyncio
async def test_mark_lines_stale_hash_rejected():
    async with _test_app() as (app, root, _):
        file_lines = ["real_content"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            stale_line = {
                "line_no": 1,
                "line_hash": line_hash("wrong_content"),
                "context_hash": context_hash("", "wrong_content", ""),
            }
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py",
                "lines": [stale_line],
                "reviewed": True,
            })
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["updated"] == 0
            assert len(body["rejected"]) == 1
            assert "stale" in body["rejected"][0]["reason"]


@pytest.mark.asyncio
async def test_mark_line_missing_fields_in_entry_rejected():
    async with _test_app() as (app, root, _):
        file_lines = ["content"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py",
                "lines": [{"line_no": 1}],  # missing line_hash and context_hash
                "reviewed": True,
            })
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["updated"] == 0
            assert len(body["rejected"]) == 1
            assert "missing" in body["rejected"][0]["reason"]


# ---------------------------------------------------------------------------
# Unmarking lines
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unmark_lines_removes_reviewed_rows():
    async with _test_app() as (app, root, db_path):
        file_lines = ["x", "y", "z"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            payload = _line_payload(file_lines)

            # Mark first
            await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py", "lines": payload, "reviewed": True,
            })
            # Unmark one
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py", "lines": [payload[1]], "reviewed": False,
            })
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["updated"] == 1

        async with open_db(db_path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) AS n FROM reviewed_lines WHERE session_id = ? AND file_path = 'app.py'",
                (sid,),
            )
            assert (await cur.fetchone())["n"] == 2


@pytest.mark.asyncio
async def test_unmark_nonexistent_row_is_accepted_noop():
    """Unmark of a line not in DB succeeds (DELETE matches nothing, still accepted)."""
    async with _test_app() as (app, root, _):
        file_lines = ["only_line"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            payload = _line_payload(file_lines)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py", "lines": payload, "reviewed": False,
            })
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["updated"] == 1
            assert body["rejected"] == []


@pytest.mark.asyncio
async def test_mark_empty_lines_array_is_ok():
    async with _test_app() as (app, root, _):
        file_lines = ["content"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                "file_path": "app.py", "lines": [], "reviewed": True,
            })
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["updated"] == 0


@pytest.mark.asyncio
async def test_mark_transaction_rollback_on_exception():
    async with _test_app() as (app, root, db_path):
        file_lines = ["line1"]
        _write_file(root, "app.py", file_lines)
        async with app.test_client() as client:
            sid = await _create_session(client)
            with mock.patch(
                "auditview.api.lines.ensure_snapshot",
                side_effect=RuntimeError("db exploded"),
            ):
                try:
                    resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                        "file_path": "app.py",
                        "lines": _line_payload(file_lines),
                        "reviewed": True,
                    })
                    assert resp.status_code == 500
                except RuntimeError:
                    pass  # Quart re-raised; rollback still ran

        # Transaction was rolled back — no rows should be present
        async with open_db(db_path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) AS n FROM reviewed_lines WHERE session_id = ?", (sid,)
            )
            assert (await cur.fetchone())["n"] == 0


@pytest.mark.asyncio
async def test_mark_oserror_reading_file_returns_500():
    async with _test_app() as (app, root, _):
        _write_file(root, "app.py", ["line"])
        async with app.test_client() as client:
            sid = await _create_session(client)
            with mock.patch(
                "auditview.api.lines.read_file_lines",
                side_effect=OSError("permission denied"),
            ):
                resp = await client.post(f"/api/sessions/{sid}/lines/mark", json={
                    "file_path": "app.py",
                    "lines": [],
                    "reviewed": True,
                })
            assert resp.status_code == 500
            body = await resp.get_json()
            assert "error" in body
