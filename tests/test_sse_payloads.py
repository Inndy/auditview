"""Wire-format regression tests for annotation_changed SSE payloads.

These guard the contract documented in `API.md`: every note create/update
broadcast carries the full new row under `note`, and every issue create/update
broadcast carries the full row under `issue`. Cascade events (issue
create-with-notes, delete-with-notes, severity change) emit one per-note
update event with the affected row rather than the legacy `id: null` cascade.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from quart import Quart

from auditview.api.events import bp as events_bp
from auditview.api.files import bp as files_bp
from auditview.api.issues import bp as issues_bp
from auditview.api.notes import bp as notes_bp
from auditview.api.sessions import bp as sessions_bp
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations


class _StubWatcher:
    def __init__(self):
        self.events: list[tuple[int, dict]] = []

    def broadcast(self, event):
        self.events.append((-1, event))

    def broadcast_to_session(self, session_id, event):
        self.events.append((session_id, event))

    async def get_scan(self, *a):
        return []

    def invalidate_scan(self, *a, **kw):
        pass

    def by_session(self, session_id):
        return [e for sid, e in self.events if sid == session_id]


@asynccontextmanager
async def _test_app():
    tmp = tempfile.TemporaryDirectory()
    try:
        db_path = os.path.join(tmp.name, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmp.name
        app.watcher = _StubWatcher()
        for bp in (sessions_bp, files_bp, notes_bp, issues_bp, events_bp):
            app.register_blueprint(bp, url_prefix="/api")
        yield app, tmp.name
    finally:
        tmp.cleanup()


async def _create_session(client, label="t"):
    resp = await client.post("/api/sessions", json={"label": label})
    assert resp.status_code == 201
    return (await resp.get_json())["id"]


def _write_file(root, rel, lines):
    path = os.path.join(root, rel)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


_NOTE_FIELDS = (
    "id", "file_path", "start_line", "end_line", "content",
    "is_todo", "is_orphaned", "snapshot_text", "created_at",
    "issue_id", "issue_severity",
)


def _assert_note_payload(event, *, action, file_path):
    assert event["type"] == "annotation_changed"
    assert event["kind"] == "note"
    assert event["action"] == action
    assert "note" in event, f"expected `note` row in payload, got {event!r}"
    note = event["note"]
    for key in _NOTE_FIELDS:
        assert key in note, f"missing `{key}` in note payload: {note!r}"
    assert note["file_path"] == file_path


@pytest.mark.asyncio
async def test_note_create_broadcast_carries_full_row():
    async with _test_app() as (app, root):
        _write_file(root, "a.py", ["one", "two", "three"])
        client = app.test_client()
        sid = await _create_session(client)
        resp = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 1, "end_line": 2, "content": "hi"},
        )
        assert resp.status_code == 201

        creates = [
            e for e in app.watcher.by_session(sid)
            if e.get("kind") == "note" and e.get("action") == "create"
        ]
        assert len(creates) == 1
        _assert_note_payload(creates[0], action="create", file_path="a.py")
        assert creates[0]["note"]["content"] == "hi"
        assert creates[0]["note"]["issue_id"] is None
        assert creates[0]["note"]["issue_severity"] is None


@pytest.mark.asyncio
async def test_note_update_broadcast_carries_full_row():
    async with _test_app() as (app, root):
        _write_file(root, "a.py", ["one", "two", "three"])
        client = app.test_client()
        sid = await _create_session(client)
        resp = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 1, "end_line": 1, "content": "v1"},
        )
        note_id = (await resp.get_json())["id"]

        app.watcher.events.clear()
        resp = await client.patch(
            f"/api/sessions/{sid}/notes/{note_id}", json={"content": "v2"}
        )
        assert resp.status_code == 200

        updates = [
            e for e in app.watcher.by_session(sid)
            if e.get("kind") == "note" and e.get("action") == "update"
        ]
        assert len(updates) == 1
        _assert_note_payload(updates[0], action="update", file_path="a.py")
        assert updates[0]["note"]["id"] == note_id
        assert updates[0]["note"]["content"] == "v2"


@pytest.mark.asyncio
async def test_note_delete_broadcast_minimal_shape():
    async with _test_app() as (app, root):
        _write_file(root, "a.py", ["one"])
        client = app.test_client()
        sid = await _create_session(client)
        resp = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 1, "end_line": 1, "content": "x"},
        )
        note_id = (await resp.get_json())["id"]

        app.watcher.events.clear()
        resp = await client.delete(f"/api/sessions/{sid}/notes/{note_id}")
        assert resp.status_code == 200

        deletes = [
            e for e in app.watcher.by_session(sid)
            if e.get("kind") == "note" and e.get("action") == "delete"
        ]
        assert len(deletes) == 1
        assert deletes[0]["id"] == note_id
        assert deletes[0]["file_path"] == "a.py"
        assert "note" not in deletes[0]


@pytest.mark.asyncio
async def test_issue_create_with_notes_emits_per_note_update():
    async with _test_app() as (app, root):
        _write_file(root, "a.py", ["one", "two"])
        client = app.test_client()
        sid = await _create_session(client)
        r1 = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 1, "end_line": 1, "content": "n1"},
        )
        r2 = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 2, "end_line": 2, "content": "n2"},
        )
        n1 = (await r1.get_json())["id"]
        n2 = (await r2.get_json())["id"]

        app.watcher.events.clear()
        resp = await client.post(
            f"/api/sessions/{sid}/issues",
            json={"title": "T", "severity": "P0", "note_ids": [n1, n2]},
        )
        assert resp.status_code == 201
        issue_id = (await resp.get_json())["id"]

        events = app.watcher.by_session(sid)
        issue_creates = [e for e in events if e.get("kind") == "issue" and e.get("action") == "create"]
        assert len(issue_creates) == 1
        assert issue_creates[0]["issue"]["id"] == issue_id
        assert issue_creates[0]["issue"]["severity"] == "P0"

        note_updates = [e for e in events if e.get("kind") == "note" and e.get("action") == "update"]
        cascade_ids = {e["note"]["id"] for e in note_updates}
        assert cascade_ids == {n1, n2}
        for e in note_updates:
            assert e["note"]["issue_id"] == issue_id
            assert e["note"]["issue_severity"] == "P0"
        for e in events:
            if e.get("kind") == "note":
                assert e.get("action") == "delete" or "note" in e, (
                    f"legacy id:null cascade leaked: {e!r}"
                )


@pytest.mark.asyncio
async def test_issue_severity_patch_re_emits_attached_notes():
    async with _test_app() as (app, root):
        _write_file(root, "a.py", ["one"])
        client = app.test_client()
        sid = await _create_session(client)
        note_resp = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 1, "end_line": 1, "content": "n"},
        )
        note_id = (await note_resp.get_json())["id"]
        issue_resp = await client.post(
            f"/api/sessions/{sid}/issues",
            json={"title": "T", "severity": "P2", "note_ids": [note_id]},
        )
        issue_id = (await issue_resp.get_json())["id"]

        app.watcher.events.clear()
        resp = await client.patch(
            f"/api/sessions/{sid}/issues/{issue_id}", json={"severity": "P0"}
        )
        assert resp.status_code == 200

        events = app.watcher.by_session(sid)
        issue_updates = [e for e in events if e.get("kind") == "issue" and e.get("action") == "update"]
        assert len(issue_updates) == 1
        assert issue_updates[0]["issue"]["severity"] == "P0"

        note_cascades = [e for e in events if e.get("kind") == "note" and e.get("action") == "update"]
        assert len(note_cascades) == 1
        assert note_cascades[0]["note"]["id"] == note_id
        assert note_cascades[0]["note"]["issue_severity"] == "P0"


@pytest.mark.asyncio
async def test_issue_delete_cascade_emits_per_note_update():
    async with _test_app() as (app, root):
        _write_file(root, "a.py", ["one"])
        client = app.test_client()
        sid = await _create_session(client)
        note_resp = await client.post(
            f"/api/sessions/{sid}/notes",
            json={"file_path": "a.py", "start_line": 1, "end_line": 1, "content": "n"},
        )
        note_id = (await note_resp.get_json())["id"]
        issue_resp = await client.post(
            f"/api/sessions/{sid}/issues",
            json={"title": "T", "severity": "P2", "note_ids": [note_id]},
        )
        issue_id = (await issue_resp.get_json())["id"]

        app.watcher.events.clear()
        resp = await client.delete(f"/api/sessions/{sid}/issues/{issue_id}")
        assert resp.status_code == 200

        events = app.watcher.by_session(sid)
        issue_deletes = [e for e in events if e.get("kind") == "issue" and e.get("action") == "delete"]
        assert len(issue_deletes) == 1
        assert issue_deletes[0]["id"] == issue_id

        note_cascades = [e for e in events if e.get("kind") == "note" and e.get("action") == "update"]
        assert len(note_cascades) == 1
        assert note_cascades[0]["note"]["id"] == note_id
        assert note_cascades[0]["note"]["issue_id"] is None
        assert note_cascades[0]["note"]["issue_severity"] is None
