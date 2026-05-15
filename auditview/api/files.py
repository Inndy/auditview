import os
from quart import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.reconciler import reconcile_file
from auditview.api.util import safe_path

bp = Blueprint("files", __name__)


@bp.route("/sessions/<int:session_id>/files", methods=["GET"])
async def list_files(session_id):
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

        rel_paths = await current_app.watcher.get_scan(session_id, root_path, exclusion_patterns)
        rel_path_set = set(rel_paths)

        for rel_path in rel_paths:
            await conn.execute(
                "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (session_id, rel_path),
            )

        cur = await conn.execute(
            "SELECT rel_path FROM files WHERE session_id = ?", (session_id,)
        )
        stale_paths = {r["rel_path"] for r in await cur.fetchall()} - rel_path_set
        if stale_paths:
            await conn.execute("BEGIN")
            try:
                for stale in stale_paths:
                    await conn.execute(
                        "UPDATE notes SET is_orphaned = 1 WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
                        (session_id, stale),
                    )
                    await conn.execute(
                        "DELETE FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
                        (session_id, stale),
                    )
                    await conn.execute(
                        "DELETE FROM files WHERE session_id = ? AND rel_path = ?",
                        (session_id, stale),
                    )
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise

        cur = await conn.execute(
            "SELECT rel_path, countable_lines FROM files WHERE session_id = ?",
            (session_id,),
        )
        file_rows = await cur.fetchall()
        countable_map = {}
        uncached = []
        for r in file_rows:
            countable_map[r["rel_path"]] = r["countable_lines"]
            if r["countable_lines"] is None and r["rel_path"] in rel_path_set:
                uncached.append(r["rel_path"])

        for rp in uncached:
            ext = os.path.splitext(rp)[1].lower()
            full_path = os.path.join(root_path, rp)
            countable = 0
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        countable = sum(1 for l in f.read().splitlines() if is_countable_line(l, ext))
                except OSError:
                    pass
            await conn.execute(
                "UPDATE files SET countable_lines = ? WHERE session_id = ? AND rel_path = ?",
                (countable, session_id, rp),
            )
            countable_map[rp] = countable

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
    for rel_path in rel_paths:
        countable = countable_map.get(rel_path) or 0
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

        skip_comments = request.args.get("skip_comments", "1") != "0"
        ext = os.path.splitext(fpath)[1].lower()

        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.splitlines()

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
                "is_countable": is_countable_line(line_content, ext, skip_comments),
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
