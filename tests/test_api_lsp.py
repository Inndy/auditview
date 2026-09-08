"""Tests for the LSP layer: result hygiene, and the routes' contract.

Every case in `TestPartitionTargets` corresponds to something a real language
server was observed doing during the spike (see `scripts/lsp-spike/README.md`),
not to a hypothetical. The route tests use a stub service so they never spawn a
subprocess -- the real servers are exercised by the spike scripts instead.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from quart import Quart

from auditview.api.lsp import bp as lsp_bp, partition_targets
from auditview.core.lsp import (LspError, LspService, resolve_root, uri_to_path,
                                _flatten_locations)
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations


def _tmp_root():
    return "/dev/shm" if os.path.isdir("/dev/shm") else None


def _loc(path, line=0, character=0):
    return {"uri": f"file://{path}", "line": line, "character": character}


class TestPartitionTargets:
    def test_percent_encoded_uri_is_decoded(self):
        """Observed: `typescript%405.9.3` for a `typescript@5.9.3` directory.

        Without the decode, containment checks compare the wrong string.
        """
        locs = [_loc("/tools/typescript%405.9.3/lib/lib.es5.d.ts", 1549)]
        in_root, out_of_root = partition_targets(locs, "/repo", "")
        assert in_root == []
        assert out_of_root[0]["path"] == "/tools/typescript@5.9.3/lib/lib.es5.d.ts"

    def test_duplicate_locations_are_collapsed(self):
        """Observed: the Options-API template case returned one location twice."""
        locs = [_loc("/repo/a.js", 50), _loc("/repo/a.js", 50)]
        in_root, _ = partition_targets(locs, "/repo", "")
        assert in_root == [{"file_path": "a.js", "line": 51, "character": 0}]

    def test_same_file_different_position_is_not_a_duplicate(self):
        locs = [_loc("/repo/a.js", 50), _loc("/repo/a.js", 50, 7)]
        in_root, _ = partition_targets(locs, "/repo", "")
        assert len(in_root) == 2

    def test_non_file_uri_is_dropped(self):
        """Volar can return virtual documents; nothing can open them."""
        locs = [{"uri": "volar-embedded://x/Counter.vue.ts", "line": 3, "character": 1}]
        assert partition_targets(locs, "/repo", "") == ([], [])

    def test_in_root_and_out_of_root_are_separated_not_interleaved(self):
        """Observed: a real target alongside five hits in TypeScript's own libs."""
        locs = [
            _loc("/repo/ui/src/api/files.js", 14, 22),
            _loc("/tools/typescript/lib/lib.es2018.promise.d.ts", 21),
            _loc("/tools/typescript/lib/lib.es5.d.ts", 1549),
        ]
        in_root, out_of_root = partition_targets(locs, "/repo", "")
        assert [t["file_path"] for t in in_root] == ["ui/src/api/files.js"]
        assert len(out_of_root) == 2

    def test_excluded_in_root_paths_are_dropped(self):
        """Observed: basedpyright returned six refs inside `build/lib/...`."""
        locs = [_loc("/repo/auditview/api/util.py", 3),
                _loc("/repo/build/lib/auditview/api/util.py", 3)]
        in_root, _ = partition_targets(locs, "/repo", "build/\n")
        assert [t["file_path"] for t in in_root] == ["auditview/api/util.py"]

    def test_exclusion_does_not_touch_out_of_root(self):
        locs = [_loc("/elsewhere/build/lib/x.py", 1)]
        _, out_of_root = partition_targets(locs, "/repo", "build/\n")
        assert len(out_of_root) == 1

    def test_line_is_converted_to_1_based_and_character_is_not(self):
        """LSP is 0-based; auditview line numbers are 1-based. `character` stays
        0-based UTF-16 code units, exactly as the browser computed it."""
        in_root, _ = partition_targets([_loc("/repo/a.js", 0, 0)], "/repo", "")
        assert in_root[0]["line"] == 1
        assert in_root[0]["character"] == 0

    def test_empty_input(self):
        assert partition_targets([], "/repo", "") == ([], [])


class TestCoreHelpers:
    def test_uri_to_path_rejects_non_file_scheme(self):
        assert uri_to_path("volar-embedded://a/b") is None
        assert uri_to_path("untitled:x") is None

    def test_flatten_accepts_location_locationlink_and_null(self):
        assert _flatten_locations(None) == []
        assert _flatten_locations({"uri": "file:///a",
                                   "range": {"start": {"line": 2, "character": 1}}}) == [
            {"uri": "file:///a", "line": 2, "character": 1}]
        assert _flatten_locations([{"targetUri": "file:///b",
                                    "targetSelectionRange": {"start": {"line": 4, "character": 0}}}]) == [
            {"uri": "file:///b", "line": 4, "character": 0}]

    def test_flatten_skips_malformed_entries(self):
        assert _flatten_locations([{"nope": 1}, "junk", None]) == []

    def test_spec_routing_by_extension(self):
        svc = LspService("/repo")
        assert svc.spec_for("ui/src/App.vue")["name"] == "vtsls"
        assert svc.spec_for("ui/src/api/files.js")["name"] == "vtsls"
        assert svc.spec_for("auditview/app.py")["name"] == "basedpyright"
        assert svc.spec_for("cmd/main.go")["name"] == "gopls"
        assert svc.spec_for("README.md") is None

    def test_resolve_root_stops_at_session_root(self, tmp_path):
        (tmp_path / "ui").mkdir()
        (tmp_path / "ui" / "package.json").write_text("{}")
        (tmp_path / "ui" / "src").mkdir()
        target = tmp_path / "ui" / "src" / "App.vue"
        target.write_text("")
        assert resolve_root(str(target), str(tmp_path), ["package.json"]) == \
            str((tmp_path / "ui").resolve())

    def test_resolve_root_falls_back_to_session_root(self, tmp_path):
        (tmp_path / "a").mkdir()
        target = tmp_path / "a" / "x.py"
        target.write_text("")
        assert resolve_root(str(target), str(tmp_path), ["pyproject.toml"]) == \
            str(tmp_path.resolve())

    def test_preview_allowlist_is_per_session_and_exact(self):
        svc = LspService("/repo")
        svc.remember_previewable(1, ["/etc/passwd"])
        assert svc.is_previewable(1, "/etc/passwd")
        assert not svc.is_previewable(1, "/etc/shadow")
        assert not svc.is_previewable(2, "/etc/passwd")

    def test_preview_allowlist_is_bounded(self):
        svc = LspService("/repo")
        svc.remember_previewable(1, [f"/x/{i}" for i in range(1500)])
        assert len(svc._previewable[1]) <= 1024
        # The most recent survive; the oldest are evicted.
        assert svc.is_previewable(1, "/x/1499")
        assert not svc.is_previewable(1, "/x/0")


class _StubLsp:
    """Stands in for LspService so no subprocess is ever spawned."""

    def __init__(self, locations=None, error=None, provider="stub"):
        self._locations = locations or []
        self._error = error
        self._provider = provider
        self.previewable = set()

    def spec_for(self, rel_path):
        if rel_path.endswith(".md"):
            return None
        return {"name": self._provider}

    async def definition(self, root_path, rel_path, line, character):
        if self._error:
            raise LspError(self._error)
        return self._locations

    def remember_previewable(self, session_id, paths):
        self.previewable.update(os.path.realpath(p) for p in paths)

    def is_previewable(self, session_id, path):
        return os.path.realpath(path) in self.previewable

    def status(self):
        return [{"name": self._provider, "available": True, "instances": []}]


@asynccontextmanager
async def _test_app(lsp=None):
    with tempfile.TemporaryDirectory(dir=_tmp_root()) as tmp:
        db_path = os.path.join(tmp, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path, exclusion_patterns) "
                "VALUES (1, 'test', ?, '')", (tmp,))
        app = Quart(__name__)
        app.config["DB_PATH"] = db_path
        app.config["ROOT_PATH"] = tmp
        app.lsp = lsp
        app.register_blueprint(lsp_bp, url_prefix="/api")
        yield app, tmp


async def _post(client, body):
    return await client.post("/api/sessions/1/lsp/definition", json=body)


@pytest.mark.asyncio
async def test_definition_unknown_session_is_404():
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await app.test_client().post("/api/sessions/999/lsp/definition",
                                        json={"file_path": "a.py", "line": 1, "character": 0})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_definition_rejects_path_escaping_root():
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await _post(app.test_client(),
                        {"file_path": "../../etc/passwd", "line": 1, "character": 0})
        assert r.status_code == 400
        assert (await r.get_json())["error"] == "Invalid path"


@pytest.mark.asyncio
async def test_definition_validates_position():
    async with _test_app(_StubLsp()) as (app, tmp):
        open(os.path.join(tmp, "a.py"), "w").close()
        client = app.test_client()
        assert (await _post(client, {"file_path": "a.py"})).status_code == 400
        assert (await _post(client, {"file_path": "a.py", "line": "1",
                                     "character": 0})).status_code == 400
        # 0 is not a valid 1-based line.
        assert (await _post(client, {"file_path": "a.py", "line": 0,
                                     "character": 0})).status_code == 400


@pytest.mark.asyncio
async def test_definition_missing_file_is_404():
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await _post(app.test_client(),
                        {"file_path": "nope.py", "line": 1, "character": 0})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_definition_reports_no_provider_without_failing():
    """An unsupported language is information, not an error: the UI should be
    able to say "no server for .md" rather than render a failure."""
    async with _test_app(_StubLsp()) as (app, tmp):
        open(os.path.join(tmp, "a.md"), "w").close()
        r = await _post(app.test_client(),
                        {"file_path": "a.md", "line": 1, "character": 0})
        assert r.status_code == 200
        body = await r.get_json()
        assert body["provider"] is None
        assert body["reason"] == "no_provider"
        assert body["in_root"] == [] and body["out_of_root"] == []


@pytest.mark.asyncio
async def test_definition_reports_disabled_when_lsp_is_off():
    async with _test_app(None) as (app, tmp):
        open(os.path.join(tmp, "a.py"), "w").close()
        r = await _post(app.test_client(),
                        {"file_path": "a.py", "line": 1, "character": 0})
        assert r.status_code == 200
        assert (await r.get_json())["reason"] == "disabled"


@pytest.mark.asyncio
async def test_definition_returns_targets_and_arms_preview():
    async with _test_app(_StubLsp()) as (app, tmp):
        target = os.path.join(tmp, "b.py")
        open(os.path.join(tmp, "a.py"), "w").close()
        open(target, "w").close()
        app.lsp = _StubLsp(locations=[
            {"uri": f"file://{target}", "line": 3, "character": 0},
            {"uri": "file:///outside/lib.pyi", "line": 9, "character": 2},
        ])
        r = await _post(app.test_client(),
                        {"file_path": "a.py", "line": 1, "character": 0})
        assert r.status_code == 200
        body = await r.get_json()
        assert body["in_root"] == [{"file_path": "b.py", "line": 4, "character": 0}]
        assert body["out_of_root"] == [
            {"path": "/outside/lib.pyi", "line": 10, "character": 2}]
        # Returning an out-of-root target is what makes it previewable.
        assert app.lsp.is_previewable(1, "/outside/lib.pyi")


@pytest.mark.asyncio
async def test_definition_server_failure_is_503():
    async with _test_app(_StubLsp(error="gopls: timed out")) as (app, tmp):
        open(os.path.join(tmp, "a.py"), "w").close()
        r = await _post(app.test_client(),
                        {"file_path": "a.py", "line": 1, "character": 0})
        assert r.status_code == 503
        assert "timed out" in (await r.get_json())["error"]


@pytest.mark.asyncio
async def test_preview_refuses_a_path_not_in_the_allowlist():
    """The endpoint reads outside the session root, so without the allowlist it
    would be an arbitrary-file reader -- and auditview ships no auth."""
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await app.test_client().get(
            "/api/sessions/1/lsp/preview?path=/etc/passwd")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_serves_an_allowlisted_path_without_review_state():
    async with _test_app(_StubLsp()) as (app, tmp):
        external = os.path.join(tmp, "outside.txt")
        with open(external, "w") as fh:
            fh.write("one\ntwo\nthree\n")
        app.lsp.remember_previewable(1, [external])
        r = await app.test_client().get(
            f"/api/sessions/1/lsp/preview?path={external}&line=2")
        assert r.status_code == 200
        body = await r.get_json()
        assert body["reviewable"] is False
        assert [line["content"] for line in body["lines"]] == ["one", "two", "three"]
        # An out-of-root file must never carry anything that could put it into
        # the coverage ledger.
        for line in body["lines"]:
            assert set(line) == {"line_no", "content"}
        assert "is_reviewed" not in body and "line_hash" not in body


@pytest.mark.asyncio
async def test_preview_requires_a_path():
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await app.test_client().get("/api/sessions/1/lsp/preview")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_status_reports_disabled_and_enabled():
    async with _test_app(None) as (app, tmp):
        r = await app.test_client().get("/api/sessions/1/lsp/status")
        assert (await r.get_json()) == {"enabled": False, "servers": []}
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await app.test_client().get("/api/sessions/1/lsp/status")
        body = await r.get_json()
        assert body["enabled"] is True and body["servers"][0]["name"] == "stub"


@pytest.mark.asyncio
async def test_status_unknown_session_is_404():
    async with _test_app(_StubLsp()) as (app, tmp):
        r = await app.test_client().get("/api/sessions/999/lsp/status")
        assert r.status_code == 404
