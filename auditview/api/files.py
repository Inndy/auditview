import asyncio
import os
from quart import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.reconciler import reconcile_file
from auditview.core.io_utils import read_file_lines, is_binary_file, file_is_large, unreviewable_reason
from auditview.api.util import get_json_object, safe_path
from auditview.core.progress import file_progress as _build_file_list_response
from auditview.core.scanner import _base_spec, path_excluded, scan_folder
from pathspec.gitignore import GitIgnoreSpecPattern

bp = Blueprint("files", __name__)

_BACKFILL_CONCURRENCY = 16


async def _drop_file_rows(conn, params, purge):
    """Remove files/reviewed_lines rows for (session_id, rel_path) pairs.

    Caller must already hold a transaction. With purge=False the notes are
    orphaned and stay recoverable; with purge=True they are deleted outright,
    which is the only way to get note snapshot_text (raw line content, so
    potentially credentials) out of the database.
    """
    if purge:
        await conn.executemany(
            "DELETE FROM notes WHERE session_id = ? AND file_path = ?", params
        )
    else:
        await conn.executemany(
            "UPDATE notes SET is_orphaned = 1 WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
            params,
        )
    await conn.executemany(
        "DELETE FROM reviewed_lines WHERE session_id = ? AND file_path = ?", params
    )
    await conn.executemany(
        "DELETE FROM files WHERE session_id = ? AND rel_path = ?", params
    )


async def _count_purgeable(conn, session_id, rel_paths):
    if not rel_paths:
        return {"files": 0, "notes": 0, "reviewed_lines": 0}
    placeholders = ",".join("?" * len(rel_paths))
    params = (session_id, *rel_paths)
    counts = {}
    for key, table, col in (
        ("files", "files", "rel_path"),
        ("notes", "notes", "file_path"),
        ("reviewed_lines", "reviewed_lines", "file_path"),
    ):
        cur = await conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE session_id = ? AND {col} IN ({placeholders})",
            params,
        )
        counts[key] = (await cur.fetchone())["c"]
    return counts


async def _vacuum(conn):
    """Reclaim freed pages so deleted note text is not recoverable from the file.

    Order matters. In WAL mode VACUUM writes the rebuilt database *through* the
    WAL, so the main db file still holds the old pages until a checkpoint moves
    them; checkpointing first and vacuuming second leaves the deleted note text
    sitting in the .db file. Vacuum, then truncate the WAL.

    VACUUM cannot run inside a transaction. open_db uses isolation_level=None,
    so there is no implicit one to fight, but callers must have COMMITted.
    """
    try:
        await conn.execute("VACUUM")
        cur = await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        row = await cur.fetchone()
    except Exception:
        current_app.logger.exception(
            "purge: VACUUM failed; rows are deleted but their pages were not reclaimed"
        )
        return False
    # wal_checkpoint reports contention in its result row rather than raising.
    if row is not None and row[0]:
        current_app.logger.warning(
            "purge: wal_checkpoint was busy; deleted pages may remain in the -wal"
        )
        return False
    return True


async def _reconcile_file_table(conn, session_id, root_path, exclusion_patterns, purge=False):
    """Sync the files table with the scanner: insert new, drop stale.

    Returns (rel_paths, purged_paths, changed). purged_paths is non-empty only
    when purge=True, and lists the paths whose notes were hard-deleted. changed
    says whether the tracked set moved at all.
    """
    rel_paths = await current_app.watcher.get_scan(session_id, root_path, exclusion_patterns)
    rel_path_set = set(rel_paths)

    cur = await conn.execute(
        "SELECT rel_path FROM files WHERE session_id = ?", (session_id,)
    )
    existing = {r["rel_path"] for r in await cur.fetchall()}
    stale_paths = existing - rel_path_set
    new_paths = [p for p in rel_paths if p not in existing]

    if not new_paths and not stale_paths:
        return rel_paths, [], False

    # A path is stale either because it is newly excluded or merely because it
    # vanished from disk (a git checkout, a cleaned build dir). Only the former
    # was asked for, so only the former is hard-deleted; a temporarily missing
    # file keeps its notes recoverable.
    if purge and stale_paths:
        spec = _base_spec(exclusion_patterns or "")
        purged_paths = sorted(p for p in stale_paths if spec.match_file(p))
    else:
        purged_paths = []
    orphaned_paths = sorted(stale_paths - set(purged_paths))

    await conn.execute("BEGIN")
    try:
        if new_paths:
            await conn.executemany(
                "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(session_id, p) for p in new_paths],
            )
        if purged_paths:
            await _drop_file_rows(conn, [(session_id, p) for p in purged_paths], True)
        if orphaned_paths:
            await _drop_file_rows(conn, [(session_id, p) for p in orphaned_paths], False)
        await conn.execute("COMMIT")
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    return rel_paths, purged_paths, True


async def _count_one(rel_path, root_path, sem):
    ext = os.path.splitext(rel_path)[1].lower()
    full_path = os.path.join(root_path, rel_path)
    async with sem:
        if not os.path.isfile(full_path):
            return rel_path, None
        try:
            if unreviewable_reason(full_path) is not None:
                return rel_path, None
            lines = await read_file_lines(full_path)
        except OSError:
            return rel_path, None
    return rel_path, sum(1 for l in lines if is_countable_line(l, ext))


async def _backfill_countable(conn, session_id, root_path, rel_paths):
    rel_path_set = set(rel_paths)
    cur = await conn.execute(
        "SELECT rel_path FROM files WHERE session_id = ? AND countable_lines IS NULL",
        (session_id,),
    )
    uncached = [r["rel_path"] for r in await cur.fetchall() if r["rel_path"] in rel_path_set]
    if not uncached:
        return

    sem = asyncio.Semaphore(_BACKFILL_CONCURRENCY)
    results = await asyncio.gather(
        *(_count_one(rp, root_path, sem) for rp in uncached)
    )
    update_rows = [(countable, session_id, rp) for rp, countable in results]

    await conn.execute("BEGIN")
    try:
        await conn.executemany(
            "UPDATE files SET countable_lines = ? WHERE session_id = ? AND rel_path = ?",
            update_rows,
        )
        await conn.execute("COMMIT")
    except Exception:
        await conn.execute("ROLLBACK")
        raise


@bp.route("/sessions/<int:session_id>/files", methods=["GET"])
async def list_files(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        )
        if await cur.fetchone() is None:
            return jsonify({"error": "Session not found"}), 404
        result = await _build_file_list_response(conn, session_id)
    return jsonify(result)


def _flag(name):
    return request.args.get(name, "").lower() in ("1", "true", "yes")


@bp.route("/sessions/<int:session_id>/rescan", methods=["POST"])
async def rescan_session(session_id):
    purge = _flag("purge")
    # A cached scan cannot reflect edits to exclusion_patterns or to any nested
    # .gitignore, so purging implies forcing.
    force = purge or _flag("force")

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
            (session_id,),
        )
        session = await cur.fetchone()
        if session is None:
            return jsonify({"error": "Session not found"}), 404

        root_path = session["root_path"]
        exclusion_patterns = session["exclusion_patterns"]

        if force:
            current_app.watcher.invalidate_scan(
                session_id, spec=_base_spec(exclusion_patterns or "")
            )

        rel_paths, purged, changed = await _reconcile_file_table(
            conn, session_id, root_path, exclusion_patterns, purge=purge
        )
        await _backfill_countable(conn, session_id, root_path, rel_paths)
        result = await _build_file_list_response(conn, session_id)

        if purged:
            await _vacuum(conn)

    # Only forced rescans announce, and only on a real change. FileTree's own SSE
    # handler re-rescans without force, so an unforced rescan must stay silent or
    # every client would drive the next round of broadcasts.
    if force and changed:
        current_app.watcher.broadcast_to_session(
            session_id, {"type": "file_changed", "rel_path": None}
        )


    # Shape is a bare array regardless of query params — ui/src/api/files.js and
    # the nvim client both iterate it directly.
    return jsonify(result)


async def _progress_for_paths(conn, session_id, rel_paths):
    """Per-path reviewed-line / note / todo counts, for paths in rel_paths."""
    if not rel_paths:
        return {}
    wanted = set(rel_paths)
    cur = await conn.execute(
        "SELECT file_path, COUNT(*) AS cnt FROM reviewed_lines "
        "WHERE session_id = ? GROUP BY file_path",
        (session_id,),
    )
    reviewed = {r["file_path"]: r["cnt"] for r in await cur.fetchall() if r["file_path"] in wanted}

    cur = await conn.execute(
        "SELECT file_path, "
        "SUM(CASE WHEN is_todo=0 THEN 1 ELSE 0 END) AS notes_cnt, "
        "SUM(CASE WHEN is_todo=1 THEN 1 ELSE 0 END) AS todos_cnt "
        "FROM notes WHERE session_id = ? GROUP BY file_path",
        (session_id,),
    )
    notes = {
        r["file_path"]: (r["notes_cnt"] or 0, r["todos_cnt"] or 0)
        for r in await cur.fetchall() if r["file_path"] in wanted
    }

    out = {}
    for rel_path in rel_paths:
        n, t = notes.get(rel_path, (0, 0))
        out[rel_path] = {
            "rel_path": rel_path,
            "reviewed_lines": reviewed.get(rel_path, 0),
            "notes_count": n,
            "todos_count": t,
        }
    return out


def _normalize_purge_path(raw):
    """(rel_path, error). Mirrors the validation POST /purge applies."""
    if not isinstance(raw, str):
        return None, "path is required"
    rel_path = raw.strip("/")
    if not rel_path or rel_path in (".", ".."):
        return None, "path is required"
    # exclusion_patterns is newline-separated and each line is stripped before
    # being compiled, so a path carrying a newline would split into two patterns
    # and one carrying edge whitespace could not be expressed at all.
    if any(c in rel_path for c in "\n\r") or rel_path != rel_path.strip():
        return None, "path may not contain newlines or leading/trailing whitespace"
    return rel_path, None


@bp.route("/sessions/<int:session_id>/purge-preview", methods=["POST"])
async def purge_preview(session_id):
    """Dry run: what a purge would hard-delete, and what it would merely orphan.

    Purge is irreversible, so the UI needs to show the damage before asking.
    Nothing here mutates: the candidate scan deliberately bypasses the watcher
    cache rather than seeding it with patterns that may never be saved.
    """
    data = await get_json_object()

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
            (session_id,),
        )
        session = await cur.fetchone()
        if session is None:
            return jsonify({"error": "Session not found"}), 404
        root_path = session["root_path"]

        cur = await conn.execute(
            "SELECT rel_path FROM files WHERE session_id = ?", (session_id,)
        )
        tracked = {r["rel_path"] for r in await cur.fetchall()}

        if "path" in data:
            rel_path, err = _normalize_purge_path(data.get("path"))
            if err:
                return jsonify({"error": err}), 400
            if safe_path(root_path, rel_path) is None:
                return jsonify({"error": "Invalid path"}), 400
            prefix = rel_path + "/"
            purged = sorted(p for p in tracked if p == rel_path or p.startswith(prefix))
            orphaned = []
        else:
            patterns = data.get("exclusion_patterns", session["exclusion_patterns"])
            if not isinstance(patterns, str):
                return jsonify({"error": "exclusion_patterns must be a string"}), 400
            try:
                spec = _base_spec(patterns)
            except Exception as exc:
                return jsonify({"error": f"invalid exclusion pattern: {exc}"}), 400

            loop = asyncio.get_running_loop()
            rel_paths = await loop.run_in_executor(None, scan_folder, root_path, patterns)
            stale = tracked - set(rel_paths)
            purged = sorted(p for p in stale if spec.match_file(p))
            orphaned = sorted(stale - set(purged))

        progress = await _progress_for_paths(conn, session_id, purged)

    files = [progress[p] for p in purged]
    at_risk = [
        f for f in files
        if f["reviewed_lines"] or f["notes_count"] or f["todos_count"]
    ]
    return jsonify({
        "purge_files": files,
        "orphan_paths": orphaned,
        "at_risk_count": len(at_risk),
        "total_reviewed_lines": sum(f["reviewed_lines"] for f in files),
        "total_notes": sum(f["notes_count"] for f in files),
        "total_todos": sum(f["todos_count"] for f in files),
    })


@bp.route("/sessions/<int:session_id>/purge", methods=["POST"])
async def purge_path(session_id):
    data = await get_json_object()
    rel_path, err = _normalize_purge_path(data.get("path"))
    if err:
        return jsonify({"error": err}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
            (session_id,),
        )
        session = await cur.fetchone()
        if session is None:
            return jsonify({"error": "Session not found"}), 404

        root_path = session["root_path"]
        if safe_path(root_path, rel_path) is None:
            return jsonify({"error": "Invalid path"}), 400

        cur = await conn.execute(
            "SELECT rel_path FROM files WHERE session_id = ?", (session_id,)
        )
        prefix = rel_path + "/"
        matched = sorted(
            r["rel_path"] for r in await cur.fetchall()
            if r["rel_path"] == rel_path or r["rel_path"].startswith(prefix)
        )

        pattern = "/" + GitIgnoreSpecPattern.escape(rel_path)
        existing_patterns = session["exclusion_patterns"] or ""
        lines = existing_patterns.splitlines()
        if pattern not in (l.strip() for l in lines):
            lines.append(pattern)
        new_patterns = "\n".join(lines)

        counts = await _count_purgeable(conn, session_id, matched)

        # The row deletes and the pattern must land together: rows gone without
        # the pattern means the next scan puts the file straight back.
        await conn.execute("BEGIN")
        try:
            if matched:
                await _drop_file_rows(conn, [(session_id, p) for p in matched], True)
            await conn.execute(
                "UPDATE sessions SET exclusion_patterns = ? WHERE id = ?",
                (new_patterns, session_id),
            )
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

        spec = _base_spec(new_patterns)
        current_app.watcher.invalidate_scan(session_id, spec=spec)

        # Re-reconcile before vacuuming: a watchdog event already in flight can
        # have re-inserted the row via reconcile_file's UPSERT after our delete.
        rel_paths, _purged, _changed = await _reconcile_file_table(
            conn, session_id, root_path, new_patterns, purge=True
        )
        await _backfill_countable(conn, session_id, root_path, rel_paths)
        result = await _build_file_list_response(conn, session_id)

        vacuumed = await _vacuum(conn)

    # file_changed only. annotation_changed carries a per-note payload that
    # CodeViewer/IssuesView dispatch on (kind/action/id); a purge has no such
    # payload, and FileTree refreshes off file_changed regardless.
    current_app.watcher.broadcast_to_session(
        session_id, {"type": "file_changed", "rel_path": rel_path}
    )

    return jsonify({
        "purged_paths": matched,
        "purged_files": counts["files"],
        "purged_notes": counts["notes"],
        "purged_reviewed_lines": counts["reviewed_lines"],
        "exclusion_patterns": new_patterns,
        "vacuumed": vacuumed,
        "files": result,
    })


@bp.route("/sessions/<int:session_id>/files/<path:fpath>", methods=["GET"])
async def get_file(session_id, fpath):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
            (session_id,),
        )
        session = await cur.fetchone()
        if session is None:
            return jsonify({"error": "Session not found"}), 404

        root_path = session["root_path"]
        full_path = safe_path(root_path, fpath)
        if full_path is None:
            return jsonify({"error": "Invalid path"}), 400
        if not os.path.isfile(full_path):
            return jsonify({"error": "File not found"}), 404

        force = request.args.get("force", "").lower() in ("1", "true", "yes")
        try:
            if not force:
                if file_is_large(full_path):
                    size = os.path.getsize(full_path)
                    return jsonify({"error": "File is too large", "reason": "large", "size": size}), 422
                if is_binary_file(full_path):
                    return jsonify({"error": "Binary file detected", "reason": "binary"}), 422
        except OSError:
            return jsonify({"error": "Could not read file"}), 500

        cur = await conn.execute(
            "SELECT last_mtime FROM files WHERE session_id = ? AND rel_path = ?",
            (session_id, fpath),
        )
        file_row = await cur.fetchone()
        if file_row is None:
            # Two situations that look identical to the client and are not: the
            # file is excluded from this session, or the files table has merely
            # not caught up with the disk. Only the second is fixable by the
            # caller, so the difference is reported as a machine-readable reason
            # (as the 422 guards above do) rather than as prose.
            #
            # path_excluded() rather than the session's cached scan: a file
            # created since the last scan is missing from that list too, and it
            # is missing whether or not the watcher ever saw the create — an
            # inotify watch that never armed would otherwise have every new file
            # reported as excluded. GET stays read-only either way; POST /rescan
            # remains the only endpoint that adopts a file.
            excluded = await asyncio.to_thread(
                path_excluded, root_path, fpath, session["exclusion_patterns"] or ""
            )
            if excluded:
                return jsonify({
                    "error": "File is excluded from this session by exclusion_patterns or a .gitignore",
                    "reason": "excluded",
                }), 404
            return jsonify({
                "error": f"File is not scanned yet — POST /api/sessions/{session_id}/rescan",
                "reason": "untracked",
            }), 404

        try:
            current_mtime = os.path.getmtime(full_path)
        except OSError:
            return jsonify({"error": "Could not read file"}), 500
        stored_mtime = file_row["last_mtime"]
        if stored_mtime is None or abs(stored_mtime - current_mtime) > 1e-6:
            await reconcile_file(conn, session_id, fpath, root_path)

        ext = os.path.splitext(fpath)[1].lower()

        try:
            lines = await read_file_lines(full_path)
        except OSError:
            return jsonify({"error": "Could not read file"}), 500

        cur = await conn.execute(
            "SELECT line_hash, context_hash, line_no FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
            (session_id, fpath),
        )
        reviewed_set = {(r["line_hash"], r["context_hash"], r["line_no"]) for r in await cur.fetchall()}

        result_lines = []
        for i, line_content in enumerate(lines):
            prev_content = lines[i - 1] if i > 0 else ""
            next_content = lines[i + 1] if i < len(lines) - 1 else ""
            lh = line_hash(line_content)
            ch = context_hash(prev_content, line_content, next_content)
            result_lines.append({
                "line_no": i + 1,
                "content": line_content,
                "line_hash": lh,
                "context_hash": ch,
                "is_reviewed": (lh, ch, i + 1) in reviewed_set,
                "is_countable": is_countable_line(line_content, ext),
            })

        cur = await conn.execute(
            "SELECT n.id, n.start_line, n.end_line, n.content, n.is_todo, n.is_orphaned, "
            "n.snapshot_text, n.created_at, n.issue_id, i.severity "
            "FROM notes n LEFT JOIN issues i ON n.issue_id = i.id "
            "WHERE n.session_id = ? AND n.file_path = ? ORDER BY n.start_line",
            (session_id, fpath),
        )
        note_rows = await cur.fetchall()

    notes = [
        {
            "id": r["id"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "content": r["content"],
            "is_todo": bool(r["is_todo"]),
            "is_orphaned": bool(r["is_orphaned"]),
            "snapshot_text": r["snapshot_text"],
            "created_at": r["created_at"],
            "issue_id": r["issue_id"],
            "issue_severity": r["severity"],
        }
        for r in note_rows
    ]

    return jsonify({"lines": result_lines, "notes": notes})
