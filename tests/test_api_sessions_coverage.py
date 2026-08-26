"""Tests for api/sessions.py and api/coverage.py."""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from quart import Quart

from auditview.api.coverage import bp as coverage_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.core.hashing import context_hash, line_hash
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
        db_path = os.path.join(tmpdir, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmpdir
        app.watcher = _StubWatcher()
        for bp in (sessions_bp, coverage_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmpdir, db_path


# =============================================================================
# api/sessions.py
# =============================================================================

@pytest.mark.asyncio
async def test_list_sessions_empty():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.get("/api/sessions")
            assert resp.status_code == 200
            assert await resp.get_json() == []


@pytest.mark.asyncio
async def test_list_sessions_returns_created():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            await client.post("/api/sessions", json={"label": "alpha"})
            await client.post("/api/sessions", json={"label": "beta"})
            resp = await client.get("/api/sessions")
            assert resp.status_code == 200
            sessions = await resp.get_json()
            assert len(sessions) == 2
            assert sessions[0]["label"] == "alpha"
            assert sessions[1]["label"] == "beta"


@pytest.mark.asyncio
async def test_create_session_empty_label_returns_400():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.post("/api/sessions", json={"label": ""})
            assert resp.status_code == 400
            body = await resp.get_json()
            assert "error" in body


@pytest.mark.asyncio
async def test_create_session_whitespace_label_returns_400():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.post("/api/sessions", json={"label": "   "})
            assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_session_returns_full_row():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.post("/api/sessions", json={"label": "my session"})
            assert resp.status_code == 201
            body = await resp.get_json()
            assert body["label"] == "my session"
            assert "id" in body
            assert "created_at" in body


@pytest.mark.asyncio
async def test_create_session_stores_exclusion_patterns():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.post(
                "/api/sessions",
                json={"label": "s", "exclusion_patterns": "*.tmp\n"},
            )
            assert resp.status_code == 201
            body = await resp.get_json()
            assert body["exclusion_patterns"] == "*.tmp\n"


# =============================================================================
# api/coverage.py
# =============================================================================

@pytest.mark.asyncio
async def test_get_coverage_unknown_session():
    async with _test_app() as (app, *_):
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/9999/coverage")
            assert resp.status_code == 404
            body = await resp.get_json()
            assert "error" in body


@pytest.mark.asyncio
async def test_get_coverage_empty_session():
    async with _test_app() as (app, tmpdir, db_path):
        async with open_db(db_path) as conn:
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path) VALUES (1, 'test', ?)",
                (tmpdir,),
            )
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/1/coverage")
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["total_files"] == 0
            assert body["total_countable_lines"] == 0
            assert body["total_reviewed_lines"] == 0
            assert body["coverage"] == 0.0


@pytest.mark.asyncio
async def test_get_coverage_with_no_reviewed_lines():
    async with _test_app() as (app, tmpdir, db_path):
        async with open_db(db_path) as conn:
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path) VALUES (1, 'test', ?)",
                (tmpdir,),
            )
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
                "VALUES (1, 'a.py', 0.0, 10)"
            )
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
                "VALUES (1, 'b.py', 0.0, 20)"
            )
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/1/coverage")
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["total_files"] == 2
            assert body["total_countable_lines"] == 30
            assert body["total_reviewed_lines"] == 0
            assert body["coverage"] == 0.0


@pytest.mark.asyncio
async def test_get_coverage_with_reviewed_lines():
    async with _test_app() as (app, tmpdir, db_path):
        async with open_db(db_path) as conn:
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path) VALUES (1, 'test', ?)",
                (tmpdir,),
            )
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
                "VALUES (1, 'a.py', 0.0, 4)"
            )
            lh = line_hash("line1")
            ch = context_hash("", "line1", "line2")
            await conn.execute(
                "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
                "VALUES (1, 'a.py', 1, ?, ?)",
                (lh, ch),
            )
            lh2 = line_hash("line2")
            ch2 = context_hash("line1", "line2", "line3")
            await conn.execute(
                "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
                "VALUES (1, 'a.py', 2, ?, ?)",
                (lh2, ch2),
            )
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/1/coverage")
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["total_countable_lines"] == 4
            assert body["total_reviewed_lines"] == 2
            assert body["coverage"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_get_coverage_clamps_reviewed_to_countable():
    """Reviewed lines can exceed countable (stale rows); result is clamped to 1.0."""
    async with _test_app() as (app, tmpdir, db_path):
        async with open_db(db_path) as conn:
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path) VALUES (1, 'test', ?)",
                (tmpdir,),
            )
            # countable_lines=1 but we insert 3 reviewed rows
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
                "VALUES (1, 'a.py', 0.0, 1)"
            )
            for i, content in enumerate(["x", "y", "z"], 1):
                lh = line_hash(content)
                ch = context_hash("", content, "")
                await conn.execute(
                    "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
                    "VALUES (1, 'a.py', ?, ?, ?)",
                    (i, lh, ch),
                )
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/1/coverage")
            assert resp.status_code == 200
            body = await resp.get_json()
            # MIN(rl_cnt=3, countable=1) = 1; coverage = 1/1 = 1.0
            assert body["total_reviewed_lines"] == 1
            assert body["coverage"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_get_coverage_skips_files_without_countable():
    """Files with countable_lines IS NULL are excluded from totals."""
    async with _test_app() as (app, tmpdir, db_path):
        async with open_db(db_path) as conn:
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path) VALUES (1, 'test', ?)",
                (tmpdir,),
            )
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
                "VALUES (1, 'counted.py', 0.0, 5)"
            )
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
                "VALUES (1, 'unscanned.py', 0.0, NULL)"
            )
        async with app.test_client() as client:
            resp = await client.get("/api/sessions/1/coverage")
            assert resp.status_code == 200
            body = await resp.get_json()
            assert body["total_files"] == 1
            assert body["total_countable_lines"] == 5
