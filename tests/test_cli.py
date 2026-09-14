"""Tests for the read-only CLI in auditview/cli.py."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile

import pytest

from auditview import cli
from auditview import __main__ as auditview_main
from auditview.db.connection import open_db, open_db_readonly
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


async def _seed_async(db_path, *, sessions, active=None, files=(), reviewed=()):
    async with open_db(db_path) as conn:
        await run_migrations(conn)
        for label, root in sessions:
            await conn.execute(
                "INSERT INTO sessions (label, root_path) VALUES (?, ?)", (label, root)
            )
        if active is not None:
            await conn.execute(
                "INSERT INTO app_config (key, value) VALUES ('mcp_session_id', ?)",
                (str(active),),
            )
        for session_id, rel_path, countable in files:
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, countable_lines) VALUES (?, ?, ?)",
                (session_id, rel_path, countable),
            )
        for session_id, file_path, line_no in reviewed:
            await conn.execute(
                "INSERT INTO reviewed_lines "
                "(session_id, file_path, line_hash, context_hash, line_no) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, file_path, f"h{line_no}", f"c{line_no}", line_no),
            )


def _seed(db_path, **kw):
    asyncio.run(_seed_async(db_path, **kw))


def _run(capsys, argv, db_path):
    code = cli.run([*argv, "--db", db_path])
    return code, capsys.readouterr()


def test_root_help_lists_server_and_query_commands(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["auditview", "-h"])

    with pytest.raises(SystemExit) as exc_info:
        auditview_main.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "commands:" in output
    assert "serve" in output
    assert auditview_main.SERVE_HELP in output
    for command, help_text in cli.COMMAND_HELP.items():
        assert command in output
        assert help_text in output


def test_existing_directory_is_server_shortcut(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(auditview_main, "serve", lambda argv, **kwargs: calls.append((argv, kwargs)))
    monkeypatch.setattr("sys.argv", ["auditview", str(tmp_path), "--debug"])

    auditview_main.main()

    assert calls == [([str(tmp_path), "--debug"], {})]


def test_explicit_serve_command_has_command_specific_prog(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(auditview_main, "serve", lambda argv, **kwargs: calls.append((argv, kwargs)))
    monkeypatch.setattr("sys.argv", ["auditview", "serve", str(tmp_path)])

    auditview_main.main()

    assert calls == [([str(tmp_path)], {"prog": "auditview serve"})]


def test_server_options_may_precede_directory_shortcut(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(auditview_main, "serve", lambda argv, **kwargs: calls.append((argv, kwargs)))
    monkeypatch.setattr("sys.argv", ["auditview", "--debug", str(tmp_path)])

    auditview_main.main()

    assert calls == [(["--debug", str(tmp_path)], {})]


def test_query_options_may_precede_subcommand(monkeypatch):
    calls = []
    monkeypatch.setattr(auditview_main.cli, "run", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr("sys.argv", ["auditview", "--json", "context"])

    with pytest.raises(SystemExit) as exc_info:
        auditview_main.main()

    assert exc_info.value.code == 0
    assert calls == [["--json", "context"]]


def test_unknown_command_that_is_not_a_directory_prints_help(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["auditview", "sttas"])

    with pytest.raises(SystemExit) as exc_info:
        auditview_main.main()

    assert exc_info.value.code == 2
    output = capsys.readouterr().err
    assert "unknown command or directory: sttas" in output
    assert "commands:" in output
    for command in ("serve", *cli.SUBCOMMANDS):
        assert command in output


@pytest.fixture
def tmpdb():
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        yield os.path.join(tmpdir, "test.db")


def test_context_uses_active_session(tmpdb, capsys):
    _seed(tmpdb, sessions=[("first", "/a"), ("second", "/b")], active=2)
    code, out = _run(capsys, ["context", "--json"], tmpdb)
    assert code == 0
    payload = json.loads(out.out)
    assert payload["session_id"] == 2
    assert payload["label"] == "second"
    assert payload["root_path"] == "/b"
    assert payload["db_path"] == tmpdb


def test_single_session_needs_no_activation(tmpdb, capsys):
    _seed(tmpdb, sessions=[("only", "/a")])
    code, out = _run(capsys, ["context", "--json"], tmpdb)
    assert code == 0
    assert json.loads(out.out)["session_id"] == 1


def test_ambiguous_session_is_an_error(tmpdb, capsys):
    _seed(tmpdb, sessions=[("first", "/a"), ("second", "/b")])
    code, out = _run(capsys, ["context"], tmpdb)
    assert code == 1
    assert "NO ACTIVE SESSION" in out.err


def test_unknown_session_is_an_error(tmpdb, capsys):
    _seed(tmpdb, sessions=[("only", "/a")])
    code, out = _run(capsys, ["--session", "42", "context"], tmpdb)
    assert code == 1
    assert "does not exist" in out.err


def test_stats_reports_coverage(tmpdb, capsys):
    _seed(
        tmpdb,
        sessions=[("only", "/a")],
        files=[(1, "a.py", 10), (1, "b.py", 10)],
        reviewed=[(1, "a.py", n) for n in range(1, 6)],
    )
    code, out = _run(capsys, ["stats", "--json"], tmpdb)
    assert code == 0
    payload = json.loads(out.out)
    assert payload["total_files"] == 2
    assert payload["total_countable_lines"] == 20
    assert payload["total_reviewed_lines"] == 5
    assert payload["coverage"] == pytest.approx(0.25)


def test_files_filters_sorts_and_limits(tmpdb, capsys):
    _seed(
        tmpdb,
        sessions=[("only", "/a")],
        files=[(1, "big.py", 100), (1, "small.py", 10), (1, "done.py", 2)],
        reviewed=[(1, "done.py", 1), (1, "done.py", 2)],
    )
    code, out = _run(capsys, ["files", "--status", "not_viewed", "--sort", "size", "--json"], tmpdb)
    assert code == 0
    rows = json.loads(out.out)
    assert [r["rel_path"] for r in rows] == ["big.py", "small.py"]

    code, out = _run(capsys, ["files", "--sort", "size", "--limit", "1", "--json"], tmpdb)
    assert [r["rel_path"] for r in json.loads(out.out)] == ["big.py"]

    code, out = _run(capsys, ["files", "--status", "reviewed", "--json"], tmpdb)
    assert [r["rel_path"] for r in json.loads(out.out)] == ["done.py"]


def test_global_flags_work_on_either_side_of_the_subcommand(tmpdb, capsys):
    _seed(tmpdb, sessions=[("first", "/a"), ("second", "/b")], active=1)
    before = json.loads(_run(capsys, ["--json", "--session", "2", "context"], tmpdb)[1].out)
    after = json.loads(_run(capsys, ["context", "--json", "--session", "2"], tmpdb)[1].out)
    assert before == after
    assert before["session_id"] == 2


def test_missing_database_is_an_error(capsys, tmp_path):
    code = cli.run(["context", "--db", str(tmp_path / "nope.db")])
    assert code == 1
    assert "database not found" in capsys.readouterr().err


def test_readonly_connection_rejects_writes(tmpdb):
    _seed(tmpdb, sessions=[("only", "/a")])

    async def check():
        async with open_db_readonly(tmpdb) as conn:
            cur = await conn.execute("PRAGMA query_only")
            assert (await cur.fetchone())[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                await conn.execute(
                    "INSERT INTO sessions (label, root_path) VALUES ('nope', '/nope')"
                )

    asyncio.run(check())


def test_cli_does_not_modify_database(tmpdb, capsys):
    _seed(tmpdb, sessions=[("only", "/a")])
    before = open(tmpdb, "rb").read()

    code, out = _run(capsys, ["context", "--json"], tmpdb)

    assert code == 0
    assert json.loads(out.out)["session_id"] == 1
    assert open(tmpdb, "rb").read() == before


def test_cli_reads_database_from_readonly_directory(tmp_path, capsys):
    directory = tmp_path / "snapshot"
    directory.mkdir()
    db_path = directory / "auditview.db"
    _seed(str(db_path), sessions=[("only", "/a")])

    db_path.chmod(0o444)
    directory.chmod(0o555)
    try:
        code, out = _run(capsys, ["context", "--json"], str(db_path))
    finally:
        directory.chmod(0o755)
        db_path.chmod(0o644)

    assert code == 0, out.err
    assert json.loads(out.out)["session_id"] == 1
