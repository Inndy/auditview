"""Tests for auditview/core/* — hashing, coverage, io_utils, scanner, reconciler."""
from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import asynccontextmanager
from unittest import mock

import pytest

from auditview.core.coverage import is_countable_line
from auditview.core.hashing import context_hash, line_hash
from auditview.core.io_utils import file_is_large, is_binary_file, read_file_lines
from auditview.core.reconciler import (
    _build_context_index,
    _has_migration_state,
    build_line_map,
    ensure_snapshot,
    reconcile_file,
)
from auditview.core.scanner import scan_folder
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


@asynccontextmanager
async def _test_db(root=None):
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        root_dir = root or tmpdir
        db_path = os.path.join(tmpdir, "test.db")
        async with open_db(db_path) as conn:
            await run_migrations(conn)
            await conn.execute(
                "INSERT INTO sessions (id, label, root_path) VALUES (1, 'test', ?)",
                (root_dir,),
            )
            yield conn, root_dir


# =============================================================================
# hashing.py
# =============================================================================

def test_line_hash_returns_sha256():
    assert line_hash("hello") == hashlib.sha256(b"hello").hexdigest()


def test_line_hash_empty():
    assert line_hash("") == hashlib.sha256(b"").hexdigest()


def test_line_hash_deterministic():
    assert line_hash("abc") == line_hash("abc")


def test_line_hash_different_inputs():
    assert line_hash("a") != line_hash("b")


def test_context_hash_basic():
    expected = hashlib.sha256("prev\ncurr\nnext".encode()).hexdigest()
    assert context_hash("prev", "curr", "next") == expected


def test_context_hash_empty_neighbors():
    expected = hashlib.sha256("\nline\n".encode()).hexdigest()
    assert context_hash("", "line", "") == expected


def test_context_hash_order_matters():
    assert context_hash("a", "b", "c") != context_hash("c", "b", "a")


def test_context_hash_deterministic():
    assert context_hash("x", "y", "z") == context_hash("x", "y", "z")


# =============================================================================
# coverage.py — is_countable_line
# =============================================================================

def test_blank_line_not_countable():
    assert not is_countable_line("", ".py")


def test_whitespace_only_not_countable():
    assert not is_countable_line("   \t  ", ".py")


def test_python_comment_not_countable():
    assert not is_countable_line("# a comment", ".py")


def test_python_indented_comment_not_countable():
    assert not is_countable_line("    # indented", ".py")


def test_python_code_countable():
    assert is_countable_line("x = 1", ".py")


def test_c_line_comment_not_countable():
    assert not is_countable_line("// comment", ".c")
    assert not is_countable_line("    // comment", ".cpp")


def test_c_block_comment_continuation_not_countable():
    assert not is_countable_line(" * continuation", ".c")
    assert not is_countable_line("  * @param x", ".java")


def test_c_code_countable():
    assert is_countable_line("int x = 0;", ".c")
    assert is_countable_line("func foo() {", ".go")


def test_js_ts_tsx_jsx():
    for ext in (".js", ".ts", ".tsx", ".jsx"):
        assert not is_countable_line("// comment", ext)
        assert is_countable_line("const x = 1;", ext)


def test_unknown_ext_always_countable():
    assert is_countable_line("anything", ".xyz")
    assert is_countable_line("// looks like comment", ".md")


# =============================================================================
# io_utils.py
# =============================================================================

def test_is_binary_file_detects_null_byte(tmp_path):
    f = tmp_path / "binary.bin"
    f.write_bytes(b"hello\x00world")
    assert is_binary_file(str(f))


def test_is_binary_file_text_file(tmp_path):
    f = tmp_path / "text.txt"
    f.write_text("hello world\n")
    assert not is_binary_file(str(f))


def test_file_is_large_over_limit(tmp_path):
    f = tmp_path / "large.bin"
    f.write_bytes(b"x" * (1 << 20 + 1))
    assert file_is_large(str(f))


def test_file_is_large_under_limit(tmp_path):
    f = tmp_path / "small.txt"
    f.write_text("tiny")
    assert not file_is_large(str(f))


@pytest.mark.asyncio
async def test_read_file_lines(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("line1\nline2\nline3")
    lines = await read_file_lines(str(f))
    assert lines == ["line1", "line2", "line3"]


@pytest.mark.asyncio
async def test_read_file_lines_empty(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    lines = await read_file_lines(str(f))
    assert lines == []


# =============================================================================
# scanner.py — scan_folder
# =============================================================================

def test_scan_folder_basic(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.js").write_text("var x = 1;")
    result = scan_folder(str(tmp_path))
    assert "a.py" in result
    assert "b.js" in result


def test_scan_folder_sorted(tmp_path):
    (tmp_path / "z.py").write_text("x")
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "m.py").write_text("x")
    result = scan_folder(str(tmp_path))
    assert result == sorted(result)


def test_scan_folder_excludes_pycache(tmp_path):
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "cached.pyc").write_text("compiled")
    (tmp_path / "app.py").write_text("x = 1")
    result = scan_folder(str(tmp_path))
    assert not any("__pycache__" in p for p in result)
    assert "app.py" in result


def test_scan_folder_excludes_node_modules(tmp_path):
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "pkg.js").write_text("module = {}")
    (tmp_path / "index.js").write_text("require('pkg')")
    result = scan_folder(str(tmp_path))
    assert not any("node_modules" in p for p in result)
    assert "index.js" in result


def test_scan_folder_excludes_venv(tmp_path):
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "activate").write_text("export VIRTUAL_ENV=...")
    result = scan_folder(str(tmp_path))
    assert not any(".venv" in p for p in result)


def test_scan_folder_respects_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n")
    (tmp_path / "app.log").write_text("log data")
    (tmp_path / "app.py").write_text("x = 1")
    result = scan_folder(str(tmp_path))
    assert "app.py" in result
    assert "app.log" not in result


def test_scan_folder_gitignore_comment_ignored(tmp_path):
    (tmp_path / ".gitignore").write_text("# just a comment\n*.log\n")
    (tmp_path / "app.log").write_text("log data")
    result = scan_folder(str(tmp_path))
    assert "app.log" not in result


def test_scan_folder_gitignore_blank_line_ignored(tmp_path):
    (tmp_path / ".gitignore").write_text("\n\n*.log\n")
    (tmp_path / "app.log").write_text("log data")
    result = scan_folder(str(tmp_path))
    assert "app.log" not in result


def test_scan_folder_gitignore_oserror_is_silent(tmp_path):
    (tmp_path / "app.py").write_text("x = 1")
    # No .gitignore — _load_gitignore_patterns silently catches OSError
    result = scan_folder(str(tmp_path))
    assert "app.py" in result


def test_scan_folder_exclusion_patterns(tmp_path):
    (tmp_path / "secret.txt").write_text("secret")
    (tmp_path / "public.txt").write_text("public")
    result = scan_folder(str(tmp_path), "secret.txt")
    assert "public.txt" in result
    assert "secret.txt" not in result


def test_scan_folder_exclusion_patterns_comment(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    result = scan_folder(str(tmp_path), "# just a comment\n")
    assert "a.txt" in result


def test_scan_folder_subdir_gitignore(tmp_path):
    subdir = tmp_path / "pkg"
    subdir.mkdir()
    (subdir / ".gitignore").write_text("*.tmp\n")
    (subdir / "scratch.tmp").write_text("temp")
    (subdir / "main.py").write_text("x = 1")
    result = scan_folder(str(tmp_path))
    assert "pkg/main.py" in result
    assert "pkg/scratch.tmp" not in result


def test_scan_folder_symlink_outside_root(tmp_path):
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "file.txt").write_text("outside content")
    link = tmp_path / "link.txt"
    link.symlink_to(outside / "file.txt")
    result = scan_folder(str(tmp_path))
    assert "link.txt" not in result
    outside.rmdir() if not list(outside.iterdir()) else None


def test_scan_folder_empty(tmp_path):
    assert scan_folder(str(tmp_path)) == []


# =============================================================================
# reconciler.py — pure functions
# =============================================================================

def test_build_line_map_identical_files():
    old = ["a", "b", "c"]
    line_map, block_margins = build_line_map(old, old)
    assert line_map == {0: 0, 1: 1, 2: 2}
    assert block_margins[1] == (1, 1)


def test_build_line_map_insertion():
    old = ["a", "b", "c"]
    new = ["a", "X", "b", "c"]
    line_map, _ = build_line_map(old, new)
    assert line_map[0] == 0
    assert line_map[1] == 2
    assert line_map[2] == 3


def test_build_line_map_deletion():
    old = ["a", "b", "c"]
    new = ["a", "c"]
    line_map, _ = build_line_map(old, new)
    assert line_map[0] == 0
    assert 1 not in line_map
    assert line_map[2] == 1


def test_build_line_map_completely_different():
    old = ["a", "b", "c"]
    new = ["x", "y", "z"]
    line_map, _ = build_line_map(old, new)
    assert line_map == {}


def test_build_line_map_block_margins():
    old = ["a", "b", "c", "d", "e"]
    new = ["a", "b", "c", "d", "e"]
    _, block_margins = build_line_map(old, new)
    assert block_margins[0] == (0, 4)
    assert block_margins[2] == (2, 2)
    assert block_margins[4] == (4, 0)


def test_build_context_index_basic():
    lines = ["alpha", "beta", "gamma"]
    hashes = [line_hash(l) for l in lines]
    index, counts = _build_context_index(lines, hashes)

    key_beta = (line_hash("beta"), context_hash("alpha", "beta", "gamma"))
    assert index[key_beta] == 2
    assert counts[key_beta] == 1


def test_build_context_index_first_and_last_use_empty_neighbors():
    lines = ["only"]
    hashes = [line_hash("only")]
    index, counts = _build_context_index(lines, hashes)
    key = (line_hash("only"), context_hash("", "only", ""))
    assert index[key] == 1


def test_build_context_index_duplicate_with_different_context():
    lines = ["a", "x", "b", "x", "c"]
    hashes = [line_hash(l) for l in lines]
    index, counts = _build_context_index(lines, hashes)
    key1 = (line_hash("x"), context_hash("a", "x", "b"))
    key2 = (line_hash("x"), context_hash("b", "x", "c"))
    assert counts[key1] == 1
    assert counts[key2] == 1


def test_build_context_index_truly_duplicate_key():
    # With 5 identical lines, the middle three (i=1,2,3) all have
    # context_hash("x","x","x"), producing a count of 3 for that key.
    lines = ["x", "x", "x", "x", "x"]
    hashes = [line_hash("x")] * 5
    index, counts = _build_context_index(lines, hashes)
    key = (line_hash("x"), context_hash("x", "x", "x"))
    assert counts[key] == 3


# =============================================================================
# reconciler.py — DB-dependent functions
# =============================================================================

@pytest.mark.asyncio
async def test_has_migration_state_empty():
    async with _test_db() as (conn, root):
        result = await _has_migration_state(conn, 1, "foo.py")
        assert result is False


@pytest.mark.asyncio
async def test_has_migration_state_with_reviewed_line():
    async with _test_db() as (conn, root):
        lh = line_hash("line content")
        ch = context_hash("", "line content", "")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, 'foo.py', 1, ?, ?)",
            (lh, ch),
        )
        result = await _has_migration_state(conn, 1, "foo.py")
        assert result is True


@pytest.mark.asyncio
async def test_has_migration_state_with_live_note():
    async with _test_db() as (conn, root):
        lh = line_hash("line")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, 'foo.py', 1, 1, ?, ?, 'snap', 'note body', 0)",
            (lh, lh),
        )
        result = await _has_migration_state(conn, 1, "foo.py")
        assert result is True


@pytest.mark.asyncio
async def test_has_migration_state_orphaned_note_not_counted():
    async with _test_db() as (conn, root):
        lh = line_hash("line")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, 'foo.py', 1, 1, ?, ?, 'snap', 'note body', 1)",
            (lh, lh),
        )
        result = await _has_migration_state(conn, 1, "foo.py")
        assert result is False


@pytest.mark.asyncio
async def test_ensure_snapshot_creates_entry(tmp_path):
    filepath = "hello.py"
    full = tmp_path / filepath
    full.write_text("line1\nline2\nline3")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        await ensure_snapshot(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT prev_line_hashes, countable_lines FROM files "
            "WHERE session_id = 1 AND rel_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row["prev_line_hashes"] is not None
        hashes = row["prev_line_hashes"].split("\n")
        assert len(hashes) == 3
        assert hashes[0] == line_hash("line1")


@pytest.mark.asyncio
async def test_ensure_snapshot_skips_if_already_set(tmp_path):
    filepath = "hello.py"
    full = tmp_path / filepath
    full.write_text("line1\nline2")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        existing_hash = "preset_hash_value"
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, existing_hash),
        )
        await ensure_snapshot(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT prev_line_hashes FROM files WHERE session_id = 1 AND rel_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row["prev_line_hashes"] == existing_hash


@pytest.mark.asyncio
async def test_ensure_snapshot_missing_file_is_silent(tmp_path):
    async with _test_db(root=str(tmp_path)) as (conn, root):
        await ensure_snapshot(conn, 1, "nonexistent.py", root)
        cur = await conn.execute(
            "SELECT * FROM files WHERE session_id = 1 AND rel_path = 'nonexistent.py'"
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_no_state_updates_mtime(tmp_path):
    filepath = "app.py"
    (tmp_path / filepath).write_text("x = 1\n")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT last_mtime, prev_line_hashes FROM files "
            "WHERE session_id = 1 AND rel_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row["last_mtime"] is not None
        assert row["prev_line_hashes"] is None


@pytest.mark.asyncio
async def test_reconcile_file_deleted_clears_marks(tmp_path):
    filepath = "app.py"
    full = tmp_path / filepath
    full.write_text("line1\nline2\nline3")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, "\n".join(line_hash(l) for l in ["line1", "line2", "line3"])),
        )

        full.unlink()
        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT * FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        assert await cur.fetchone() is None
        cur = await conn.execute(
            "SELECT * FROM files WHERE session_id = 1 AND rel_path = ?", (filepath,)
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_deleted_orphans_notes(tmp_path):
    filepath = "app.py"
    full = tmp_path / filepath
    full.write_text("line1\nline2\nline3")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line1")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, ?, 1, 2, ?, ?, 'snap', 'body', 0)",
            (filepath, lh, lh),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, "\n".join(line_hash(l) for l in ["line1", "line2", "line3"])),
        )

        full.unlink()
        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT is_orphaned FROM notes WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row["is_orphaned"] == 1


@pytest.mark.asyncio
async def test_reconcile_file_unchanged_hashes_skips_migration(tmp_path):
    filepath = "app.py"
    lines = ["line1", "line2", "line3"]
    (tmp_path / filepath).write_text("\n".join(lines))
    phashes = "\n".join(line_hash(l) for l in lines)

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT line_no FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row["line_no"] == 2


@pytest.mark.asyncio
async def test_reconcile_file_migrates_mark_on_line_shift(tmp_path):
    filepath = "app.py"
    old_lines = ["line1", "line2", "line3"]
    new_lines = ["inserted", "line1", "line2", "line3"]
    phashes = "\n".join(line_hash(l) for l in old_lines)

    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT line_no, line_hash FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row["line_no"] == 3  # shifted from 2 to 3


@pytest.mark.asyncio
async def test_reconcile_file_drops_mark_when_line_deleted(tmp_path):
    filepath = "app.py"
    old_lines = ["line1", "line2", "line3"]
    new_lines = ["line1", "line3"]
    phashes = "\n".join(line_hash(l) for l in old_lines)

    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT * FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_no_snapshot_uses_context_hash_fallback(tmp_path):
    filepath = "app.py"
    lines = ["line1", "line2", "line3"]
    (tmp_path / filepath).write_text("\n".join(lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        # No files row — forces fallback path (old_line_hashes = None)
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, NULL)",
            (filepath,),
        )

        await reconcile_file(conn, 1, filepath, root)

        # Mark should still be there since content/context matches
        cur = await conn.execute(
            "SELECT line_no FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row is not None


@pytest.mark.asyncio
async def test_reconcile_file_note_migrates_on_line_shift(tmp_path):
    filepath = "app.py"
    old_lines = ["line1", "line2", "line3"]
    new_lines = ["new_top", "line1", "line2", "line3"]
    phashes = "\n".join(line_hash(l) for l in old_lines)

    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        sh = line_hash("line1")
        eh = line_hash("line2")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, ?, 1, 2, ?, ?, 'snap', 'body', 0)",
            (filepath, sh, eh),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT start_line, end_line, is_orphaned FROM notes WHERE session_id = 1",
        )
        row = await cur.fetchone()
        assert row["is_orphaned"] == 0
        assert row["start_line"] == 2
        assert row["end_line"] == 3


@pytest.mark.asyncio
async def test_reconcile_file_note_orphaned_when_lines_deleted(tmp_path):
    filepath = "app.py"
    old_lines = ["line1", "line2", "line3"]
    new_lines = ["line1", "line3"]
    phashes = "\n".join(line_hash(l) for l in old_lines)

    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        sh = line_hash("line2")
        eh = line_hash("line3")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, ?, 2, 3, ?, ?, 'snap', 'body', 0)",
            (filepath, sh, eh),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT is_orphaned FROM notes WHERE session_id = 1",
        )
        row = await cur.fetchone()
        assert row["is_orphaned"] == 1


# =============================================================================
# reconciler.py — additional branch coverage
# =============================================================================

@pytest.mark.asyncio
async def test_reconcile_file_drops_mark_on_context_mismatch(tmp_path):
    """Line 115-117: context_hash at mapped position differs from stored hash."""
    filepath = "app.py"
    old_lines = ["line1", "line2", "line3"]
    new_lines = ["line1", "line2", "CHANGED"]  # line2 maps to pos 2 but context differs
    phashes = "\n".join(line_hash(l) for l in old_lines)
    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT * FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_fallback_drops_mark_when_content_missing(tmp_path):
    """Line 130-132: no snapshot fallback, mark's (lh, ch) not in new file."""
    filepath = "app.py"
    (tmp_path / filepath).write_text("completely_different_content")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("original_line")
        ch = context_hash("", "original_line", "")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 1, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, NULL)",
            (filepath,),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT * FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_fallback_drops_mark_on_ambiguous_context(tmp_path):
    """Line 133-139: fallback, same (lh, ch) key appears more than once → drop."""
    filepath = "app.py"
    # 5 identical lines so the middle 3 share context_hash("x","x","x")
    lines = ["x", "x", "x", "x", "x"]
    (tmp_path / filepath).write_text("\n".join(lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("x")
        ch = context_hash("x", "x", "x")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, NULL)",
            (filepath,),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT * FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_fallback_updates_mark_position(tmp_path):
    """Line 141: fallback, mark's key found at different line_no → position updated."""
    filepath = "app.py"
    old_lines = ["line1", "line2"]
    new_lines = ["inserted", "line1", "line2"]
    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line1")
        # In new file, "line1" is at index 1, context_hash("inserted","line1","line2")
        ch = context_hash("inserted", "line1", "line2")
        # Store mark at old position (line 1) with the new context_hash to simulate
        # a case where there's no snapshot but the stored ch matches new file
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 1, ?, ?)",
            (filepath, lh, ch),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, NULL)",
            (filepath,),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT line_no FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row["line_no"] == 2  # migrated from line 1 to line 2


@pytest.mark.asyncio
async def test_reconcile_file_no_files_row_uses_context_fallback(tmp_path):
    """Line 349: has_state=True but no files row → old_line_hashes=None → fallback."""
    filepath = "app.py"
    lines = ["line1", "line2", "line3"]
    (tmp_path / filepath).write_text("\n".join(lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("line2")
        ch = context_hash("line1", "line2", "line3")
        await conn.execute(
            "INSERT INTO reviewed_lines (session_id, file_path, line_no, line_hash, context_hash) "
            "VALUES (1, ?, 2, ?, ?)",
            (filepath, lh, ch),
        )
        # No files row at all

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT line_no FROM reviewed_lines WHERE session_id = 1 AND file_path = ?",
            (filepath,),
        )
        row = await cur.fetchone()
        assert row is not None


@pytest.mark.asyncio
async def test_reconcile_file_oserror_returns_silently(tmp_path):
    """Lines 308-310: OSError reading the file logs and returns without modifying DB."""
    filepath = "app.py"
    (tmp_path / filepath).write_text("line1")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        with mock.patch(
            "auditview.core.reconciler.read_file_lines",
            side_effect=OSError("permission denied"),
        ):
            await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT * FROM files WHERE session_id = 1 AND rel_path = ?", (filepath,)
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_reconcile_file_note_orphaned_on_snapshot_hash_mismatch(tmp_path):
    """Lines 209-210: note's start_hash doesn't match the new file at the mapped position."""
    filepath = "app.py"
    old_snapshot_lines = ["line1", "line2", "line3"]
    # File changed (line3 → CHANGED), forcing SequenceMatcher to run.
    # line1 and line2 still map, but note's start_hash is wrong for line1.
    new_lines = ["line1", "line2", "CHANGED"]
    phashes = "\n".join(line_hash(l) for l in old_snapshot_lines)
    (tmp_path / filepath).write_text("\n".join(new_lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        # start_hash intentionally wrong — doesn't match hash("line1")
        wrong_sh = line_hash("NOT_line1")
        real_eh = line_hash("line2")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, ?, 1, 2, ?, ?, 'snap', 'body', 0)",
            (filepath, wrong_sh, real_eh),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, ?)",
            (filepath, phashes),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT is_orphaned FROM notes WHERE session_id = 1",
        )
        row = await cur.fetchone()
        assert row["is_orphaned"] == 1


@pytest.mark.asyncio
async def test_reconcile_file_note_orphaned_in_fallback_on_hash_mismatch(tmp_path):
    """Lines 232-236: fallback path, note's start_hash doesn't match new file line."""
    filepath = "app.py"
    lines = ["real_line1", "real_line2", "real_line3"]
    (tmp_path / filepath).write_text("\n".join(lines))

    async with _test_db(root=str(tmp_path)) as (conn, root):
        wrong_hash = line_hash("different_content")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, ?, 1, 2, ?, ?, 'snap', 'body', 0)",
            (filepath, wrong_hash, wrong_hash),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, NULL)",
            (filepath,),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT is_orphaned FROM notes WHERE session_id = 1",
        )
        row = await cur.fetchone()
        assert row["is_orphaned"] == 1


@pytest.mark.asyncio
async def test_reconcile_file_note_orphaned_in_fallback_out_of_bounds(tmp_path):
    """Lines 232-236: fallback path, note's start_line exceeds new file length."""
    filepath = "app.py"
    (tmp_path / filepath).write_text("only_one_line")

    async with _test_db(root=str(tmp_path)) as (conn, root):
        lh = line_hash("whatever")
        await conn.execute(
            "INSERT INTO notes (session_id, file_path, start_line, end_line, "
            "start_hash, end_hash, snapshot_text, content, is_orphaned) "
            "VALUES (1, ?, 5, 6, ?, ?, 'snap', 'body', 0)",
            (filepath, lh, lh),
        )
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes) "
            "VALUES (1, ?, 0.0, NULL)",
            (filepath,),
        )

        await reconcile_file(conn, 1, filepath, root)

        cur = await conn.execute(
            "SELECT is_orphaned FROM notes WHERE session_id = 1",
        )
        row = await cur.fetchone()
        assert row["is_orphaned"] == 1


# =============================================================================
# scanner.py — remaining branch coverage
# =============================================================================

def test_scan_folder_prunes_dir_via_active_specs(tmp_path):
    """Lines 103-106: active_specs prune a subdirectory via gitignore."""
    subdir = tmp_path / "build"
    subdir.mkdir()
    sub2 = subdir / "out"
    sub2.mkdir()
    (sub2 / "artifact.js").write_text("built artifact")
    (tmp_path / ".gitignore").write_text("build/\n")
    result = scan_folder(str(tmp_path))
    assert not any("build" in p for p in result)


def test_scan_folder_gitignore_oserror_on_unreadable_file(tmp_path):
    """Lines 38-39: _load_gitignore_patterns OSError when file exists but can't be read."""
    gi = tmp_path / ".gitignore"
    gi.write_text("*.log\n")
    gi.chmod(0o000)
    (tmp_path / "app.log").write_text("log data")
    (tmp_path / "app.py").write_text("x = 1")
    try:
        result = scan_folder(str(tmp_path))
        # gitignore was unreadable, so *.log was not excluded
        assert "app.py" in result
    finally:
        gi.chmod(0o644)
