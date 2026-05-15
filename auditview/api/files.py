import os
from flask import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.reconciler import reconcile_file
from auditview.api.util import safe_path

bp = Blueprint("files", __name__)


def _get_session(cur, session_id, is_apsw):
    row = cur.execute(
        "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    if is_apsw:
        return {"id": row[0], "root_path": row[1], "exclusion_patterns": row[2]}
    return dict(row)


@bp.route("/sessions/<int:session_id>/files", methods=["GET"])
def list_files(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    session = _get_session(cur, session_id, is_apsw)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    root_path = session["root_path"]
    exclusion_patterns = session["exclusion_patterns"]

    rel_paths = current_app.watcher.get_scan(session_id, root_path, exclusion_patterns)
    rel_path_set = set(rel_paths)

    for rel_path in rel_paths:
        cur.execute(
            "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (session_id, rel_path),
        )

    # Fetch cached countable_lines per file
    file_rows = cur.execute(
        "SELECT rel_path, countable_lines FROM files WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    countable_map = {}
    uncached = []
    for r in file_rows:
        rp = r[0] if is_apsw else r["rel_path"]
        cl = r[1] if is_apsw else r["countable_lines"]
        countable_map[rp] = cl
        if cl is None and rp in rel_path_set:
            uncached.append(rp)

    # Compute and cache for files not yet indexed
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
        cur.execute(
            "UPDATE files SET countable_lines = ? WHERE session_id = ? AND rel_path = ?",
            (countable, session_id, rp),
        )
        countable_map[rp] = countable

    # Batch: reviewed counts per file
    reviewed_rows = cur.execute(
        "SELECT file_path, COUNT(*) FROM reviewed_lines WHERE session_id = ? GROUP BY file_path",
        (session_id,),
    ).fetchall()
    reviewed_map = {(r[0] if is_apsw else r["file_path"]): (r[1] if is_apsw else r[1])
                    for r in reviewed_rows}

    # Batch: note/todo counts per file (live only)
    note_rows = cur.execute(
        "SELECT file_path, "
        "SUM(CASE WHEN is_todo=0 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN is_todo=1 THEN 1 ELSE 0 END) "
        "FROM notes WHERE session_id = ? AND is_orphaned=0 GROUP BY file_path",
        (session_id,),
    ).fetchall()
    notes_map = {(r[0] if is_apsw else r["file_path"]): (
        (r[1] if is_apsw else r[1]) or 0,
        (r[2] if is_apsw else r[2]) or 0,
    ) for r in note_rows}

    result = []
    for rel_path in rel_paths:
        countable = countable_map.get(rel_path) or 0
        reviewed = reviewed_map.get(rel_path, 0)
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
def get_file(session_id, fpath):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    session = _get_session(cur, session_id, is_apsw)
    if session is None:
        return jsonify({"error": "Session not found"}), 404

    root_path = session["root_path"]
    full_path = safe_path(root_path, fpath)
    if full_path is None:
        return jsonify({"error": "Invalid path"}), 400

    if not os.path.isfile(full_path):
        return jsonify({"error": "File not found"}), 404

    file_row = cur.execute(
        "SELECT last_mtime FROM files WHERE session_id = ? AND rel_path = ?",
        (session_id, fpath),
    ).fetchone()
    if file_row is None:
        return jsonify({"error": "File not tracked in this session — call list_files first"}), 404

    current_mtime = os.path.getmtime(full_path)
    stored_mtime = file_row[0] if is_apsw else file_row["last_mtime"]
    if stored_mtime is None or abs(stored_mtime - current_mtime) > 1e-6:
        reconcile_file(conn, session_id, fpath, root_path)

    skip_comments = request.args.get("skip_comments", "1") != "0"
    ext = os.path.splitext(fpath)[1].lower()

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    lines = content.splitlines()

    reviewed_rows = cur.execute(
        "SELECT line_hash, context_hash FROM reviewed_lines "
        "WHERE session_id = ? AND file_path = ?",
        (session_id, fpath),
    ).fetchall()

    if is_apsw:
        reviewed_set = {(r[0], r[1]) for r in reviewed_rows}
    else:
        reviewed_set = {(r["line_hash"], r["context_hash"]) for r in reviewed_rows}

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

    note_rows = cur.execute(
        "SELECT n.id, n.start_line, n.end_line, n.content, n.is_todo, n.is_orphaned, n.snapshot_text, n.created_at, n.issue_id, i.severity "
        "FROM notes n LEFT JOIN issues i ON n.issue_id = i.id "
        "WHERE n.session_id = ? AND n.file_path = ? ORDER BY n.start_line",
        (session_id, fpath),
    ).fetchall()

    def note_to_dict(r):
        if is_apsw:
            return {"id": r[0], "start_line": r[1], "end_line": r[2], "content": r[3],
                    "is_todo": bool(r[4]), "is_orphaned": bool(r[5]),
                    "snapshot_text": r[6], "created_at": r[7],
                    "issue_id": r[8], "issue_severity": r[9]}
        return {"id": r["id"], "start_line": r["start_line"], "end_line": r["end_line"],
                "content": r["content"], "is_todo": bool(r["is_todo"]),
                "is_orphaned": bool(r["is_orphaned"]),
                "snapshot_text": r["snapshot_text"], "created_at": r["created_at"],
                "issue_id": r["issue_id"], "issue_severity": r["severity"]}

    return jsonify({"lines": result_lines, "notes": [note_to_dict(r) for r in note_rows]})
