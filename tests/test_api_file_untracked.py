"""GET /files/:path must say *why* a file has no state, in a form clients can act on.

The old 404 said "call list_files first", but GET /files has been read-only
since the split of listing from rescanning -- following that advice changed
nothing, and the nvim client followed exactly that advice. The two cases behind
one status code are now separated by `reason`: "untracked" (POST /rescan adopts
it) and "excluded" (no rescan ever will).
"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from unittest import mock

import pytest
from quart import Quart

from auditview.api.files import bp as files_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

# The real scan/cache path, so exclusion patterns and the untracked/excluded
# split actually bite. Shared with the purge tests rather than re-stubbed here.
from tests.test_api_purge import _RealScanWatcher

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


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
        for bp in (sessions_bp, files_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmpdir


def _write(tmpdir, rel, text):
    full = os.path.join(tmpdir, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


async def _mk_session(client, **kw):
    resp = await client.post("/api/sessions", json={"label": "s", **kw})
    return (await resp.get_json())["id"]


@pytest.mark.asyncio
async def test_file_created_since_last_scan_reports_untracked():
    async with _test_app() as (app, tmpdir):
        _write(tmpdir, "old.py", "a = 1\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")

            _write(tmpdir, "new.py", "b = 2\n")
            resp = await client.get(f"/api/sessions/{sid}/files/new.py")
            assert resp.status_code == 404
            body = await resp.get_json()
            assert body["reason"] == "untracked"
            assert "rescan" in body["error"]

            # And the advice works, unlike the message it replaced.
            await client.post(f"/api/sessions/{sid}/rescan?force=1")
            assert (await client.get(f"/api/sessions/{sid}/files/new.py")).status_code == 200


@pytest.mark.asyncio
async def test_excluded_file_reports_excluded():
    async with _test_app() as (app, tmpdir):
        _write(tmpdir, "junk.log", "noise\n")
        async with app.test_client() as client:
            sid = await _mk_session(client, exclusion_patterns="*.log")
            await client.post(f"/api/sessions/{sid}/rescan")

            resp = await client.get(f"/api/sessions/{sid}/files/junk.log")
            assert resp.status_code == 404
            body = await resp.get_json()
            assert body["reason"] == "excluded"

            # A rescan cannot help, so the client must not retry on this reason.
            await client.post(f"/api/sessions/{sid}/rescan?force=1")
            assert (await client.get(f"/api/sessions/{sid}/files/junk.log")).status_code == 404


@pytest.mark.asyncio
async def test_gitignored_file_reports_excluded():
    async with _test_app() as (app, tmpdir):
        _write(tmpdir, ".gitignore", "*.log\n")
        _write(tmpdir, "junk.log", "noise\n")
        async with app.test_client() as client:
            sid = await _mk_session(client)
            await client.post(f"/api/sessions/{sid}/rescan")

            resp = await client.get(f"/api/sessions/{sid}/files/junk.log")
            assert resp.status_code == 404
            assert (await resp.get_json())["reason"] == "excluded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "payload", "reason"),
    [
        ("large.py", b"x" * ((1 << 20) + 1), "large"),
        ("binary.py", b"prefix\x00payload", "binary"),
    ],
)
async def test_rescan_does_not_read_unreviewable_files(name, payload, reason):
    async with _test_app() as (app, tmpdir):
        full = os.path.join(tmpdir, name)
        with open(full, "wb") as fh:
            fh.write(payload)

        async with app.test_client() as client:
            sid = await _mk_session(client)
            with mock.patch(
                "auditview.api.files.read_file_lines",
                side_effect=AssertionError("rescan must not read this file"),
            ):
                body = await (await client.post(f"/api/sessions/{sid}/rescan")).get_json()
            file_state = next(item for item in body if item["rel_path"] == name)
            assert file_state["status"] == "unreviewable"
            assert file_state["countable_lines"] == 0

            blocked = await client.get(f"/api/sessions/{sid}/files/{name}")
            assert blocked.status_code == 422
            assert (await blocked.get_json())["reason"] == reason



@pytest.mark.asyncio
async def test_missing_file_and_session_are_unchanged():
    """The other two 404s carry no reason and must keep their shapes."""
    async with _test_app() as (app, tmpdir):
        async with app.test_client() as client:
            sid = await _mk_session(client)
            resp = await client.get(f"/api/sessions/{sid}/files/nope.py")
            assert resp.status_code == 404
            assert (await resp.get_json()) == {"error": "File not found"}

            resp = await client.get(f"/api/sessions/{sid + 99}/files/nope.py")
            assert resp.status_code == 404
            assert (await resp.get_json()) == {"error": "Session not found"}
