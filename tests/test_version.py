"""Tests for the build identity in auditview/__init__.py and GET /api/config."""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from quart import Quart

import auditview
from auditview.api.config import bp as config_bp
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


@asynccontextmanager
async def _test_app():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmpdir
        app.register_blueprint(config_bp, url_prefix="/api")
        yield app


def test_version_string_with_clean_commit(monkeypatch):
    monkeypatch.setattr(auditview, "__version__", "0.1.3")
    monkeypatch.setattr(auditview, "__commit__", "59a7348aa17b5a763610fd9b443d5d90617761ff")
    monkeypatch.setattr(auditview, "__dirty__", False)
    assert auditview.version_string() == "0.1.3 (59a7348)"


def test_version_string_marks_dirty(monkeypatch):
    monkeypatch.setattr(auditview, "__version__", "0.1.3")
    monkeypatch.setattr(auditview, "__commit__", "59a7348aa17b5a763610fd9b443d5d90617761ff")
    monkeypatch.setattr(auditview, "__dirty__", True)
    assert auditview.version_string() == "0.1.3 (59a7348, dirty)"


def test_version_string_without_stamp(monkeypatch):
    """A source tree that was never built carries no commit; report the version alone."""
    monkeypatch.setattr(auditview, "__version__", "0.1.3")
    monkeypatch.setattr(auditview, "__commit__", "")
    monkeypatch.setattr(auditview, "__dirty__", None)
    assert auditview.version_string() == "0.1.3"


def test_dirty_unknown_is_not_reported_as_clean(monkeypatch):
    """DIRTY is None when the build could not ask git -- never claim 'clean'."""
    monkeypatch.setattr(auditview, "__version__", "0.1.3")
    monkeypatch.setattr(auditview, "__commit__", "abcdef1234567890")
    monkeypatch.setattr(auditview, "__dirty__", None)
    assert auditview.version_string() == "0.1.3 (abcdef1)"


@pytest.mark.asyncio
async def test_config_reports_build_identity():
    async with _test_app() as app:
        client = app.test_client()
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = await resp.get_json()

    assert data["version"] == auditview.__version__
    # null rather than "" when the build carried no stamp, so a client can tell
    # "unknown" from a real value without string-emptiness checks.
    assert data["commit"] == (auditview.__commit__ or None)
    # The pre-existing keys must survive: three clients read this endpoint.
    assert set(data) >= {"root_path", "db_path", "mcp_session", "version", "commit"}
