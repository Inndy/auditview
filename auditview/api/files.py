import asyncio
import os
from quart import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.reconciler import reconcile_file
from auditview.core.io_utils import read_file_lines
from auditview.api.util import safe_path

bp = Blueprint("files", __name__)

_BACKFILL_CONCURRENCY = 16


async def _reconcile_file_table(conn, session_id, root_path, exclusion_patterns):
    """Sync the files table with the scanner: insert new, delete stale, orphan their notes."""
    rel_paths = await current_app.watcher.get_scan(session_id, root_path, exclusion_patterns)
    rel_path_set = set(rel_paths)

    cur = await conn.execute(
        "SELECT rel_path FROM files WHERE session_id = ?", (session_id,)
    )
    existing = {r["rel_path"] for r in await cur.fetchall()}
    stale_paths = existing - rel_path_set
    new_paths = [p for p in rel_paths if p not in existing]

    if not new_paths and not stale_paths:
        return rel_paths

    await conn.execute("BEGIN")
    try:
        if new_paths:
            await conn.executemany(
                "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(session_id, p) for p in new_paths],
            )
        if stale_paths:
            stale_params = [(session_id, p) for p in stale_paths]
            await conn.executemany(
                "UPDATE notes SET is_orphaned = 1 WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
                stale_params,
            )
            await conn.executemany(
                "DELETE FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
                stale_params,
            )
            await conn.executemany(
                "DELETE FROM files WHERE session_id = ? AND rel_path = ?",
                stale_params,
            )
        await conn.execute("COMMIT")
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    return rel_paths


async def _count_one(rel_path, root_path, sem):
    ext = os.path.splitext(rel_path)[1].lower()
    full_path = os.path.join(root_path, rel_path)
    async with sem:
        if not os.path.isfile(full_path):
            return rel_path, 0
        try:
            lines = await read_file_lines(full_path)
        except OSError:
            return rel_path, 0
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


async def _build_file_list_response(conn, session_id):
    cur = await conn.execute(
        "SELECT rel_path, countable_lines FROM files WHERE session_id = ? ORDER BY rel_path",
        (session_id,),
    )
    file_rows = await cur.fetchall()
    countable_map = {r["rel_path"]: r["countable_lines"] for r in file_rows}

    cur = await conn.execute(
        "SELECT file_path, COUNT(*) AS cnt FROM reviewed_lines WHERE session_id = ? GROUP BY file_path",
        (session_id,),
    )
    reviewed_map = {r["file_path"]: r["cnt"] for r in await cur.fetchall()}

    cur = await conn.execute(
        "SELECT file_path, "
        "SUM(CASE WHEN is_todo=0 THEN 1 ELSE 0 END) AS notes_cnt, "
        "SUM(CASE WHEN is_todo=1 THEN 1 ELSE 0 END) AS todos_cnt "
        "FROM notes WHERE session_id = ? AND is_orphaned=0 GROUP BY file_path",
        (session_id,),
    )
    notes_map = {r["file_path"]: (r["notes_cnt"] or 0, r["todos_cnt"] or 0) for r in await cur.fetchall()}

    result = []
    for rel_path, countable_raw in countable_map.items():
        countable = countable_raw or 0
        reviewed = min(reviewed_map.get(rel_path, 0), countable)
        coverage = reviewed / countable if countable > 0 else 0.0
        notes_c, todos_c = notes_map.get(rel_path, (0, 0))

        if countable == 0:
            status = "empty"
        elif reviewed == 0:
            status = "not_viewed"
        elif reviewed >= countable:
            status = "reviewed"
        else:
            status = "partial"

        result.append({
            "rel_path": rel_path,
            "countable_lines": countable,
            "reviewed_lines": reviewed,
            "coverage": coverage,
            "status": status,
            "notes_count": notes_c,
            "todos_count": todos_c,
        })
    return result


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


@bp.route("/sessions/<int:session_id>/rescan", methods=["POST"])
async def rescan_session(session_id):
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

        rel_paths = await _reconcile_file_table(conn, session_id, root_path, exclusion_patterns)
        await _backfill_countable(conn, session_id, root_path, rel_paths)
        result = await _build_file_list_response(conn, session_id)
    return jsonify(result)


@bp.route("/sessions/<int:session_id>/files/<path:fpath>", methods=["GET"])
async def get_file(session_id, fpath):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, root_path FROM sessions WHERE id = ?", (session_id,)
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

        cur = await conn.execute(
            "SELECT last_mtime FROM files WHERE session_id = ? AND rel_path = ?",
            (session_id, fpath),
        )
        file_row = await cur.fetchone()
        if file_row is None:
            return jsonify({"error": "File not tracked in this session — call list_files first"}), 404

        current_mtime = os.path.getmtime(full_path)
        stored_mtime = file_row["last_mtime"]
        if stored_mtime is None or abs(stored_mtime - current_mtime) > 1e-6:
            await reconcile_file(conn, session_id, fpath, root_path)

        ext = os.path.splitext(fpath)[1].lower()

        lines = await read_file_lines(full_path)

        cur = await conn.execute(
            "SELECT line_hash, context_hash FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
            (session_id, fpath),
        )
        reviewed_set = {(r["line_hash"], r["context_hash"]) for r in await cur.fetchall()}

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
                "is_reviewed": (lh, ch) in reviewed_set,
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
