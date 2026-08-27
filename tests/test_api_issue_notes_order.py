"""Attached notes must come back in insertion order, not index order.

created_at is only second-granular, so a burst of inserts ties on it. Walkthrough
issues (an agent attaching one note per step of a code flow) depend on the id
tiebreak to preserve reading order.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from quart import Quart

from auditview.api.issues import bp as issues_bp
from auditview.api.notes import bp as notes_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


class _StubWatcher:
    def broadcast_to_session(self, *a): pass
    def broadcast_all(self, *a, **kw): pass
    async def get_scan(self, *a): return []
    def invalidate_scan(self, *a, **kw): pass


@asynccontextmanager
async def _test_app():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        db_path = os.path.join(tmpdir, ".auditview.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmpdir
        app.watcher = _StubWatcher()
        for bp in (sessions_bp, notes_bp, issues_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmpdir


@pytest.mark.asyncio
async def test_issue_notes_keep_insertion_order():
    async with _test_app() as (app, tmpdir):
        client = app.test_client()
        sid = (await (await client.post(
            "/api/sessions", json={"label": "s", "root_path": tmpdir}
        )).get_json())["id"]

        # Names chosen so alphabetical file_path order is the reverse of the
        # order the steps are attached in.
        steps = [("zebra.py", "step 1"), ("mango.py", "step 2"), ("apple.py", "step 3")]
        for rel, _ in steps:
            with open(os.path.join(tmpdir, rel), "w") as f:
                f.write("one\ntwo\nthree\n")

        issue_id = (await (await client.post(
            f"/api/sessions/{sid}/issues",
            json={"title": "[flow] walkthrough", "severity": "P2", "source": "agents:explain"},
        )).get_json())["id"]

        for rel, content in steps:
            resp = await client.post(
                f"/api/sessions/{sid}/notes",
                json={"file_path": rel, "start_line": 1, "end_line": 2,
                      "content": content, "issue_id": issue_id},
            )
            assert resp.status_code == 201

        resp = await client.get(f"/api/sessions/{sid}/issues/{issue_id}/notes")
        assert resp.status_code == 200
        rows = await resp.get_json()
        assert [r["content"] for r in rows] == ["step 1", "step 2", "step 3"]
        assert all(r["snapshot_text"] == "one\ntwo" for r in rows)
