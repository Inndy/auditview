import os
from flask import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.reconciler import reconcile_file
from auditview.core.scanner import scan_folder
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

    rel_paths = scan_folder(root_path, exclusion_patterns)

    for rel_path in rel_paths:
        cur.execute(
            "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (session_id, rel_path),
        )

    result = []
    for rel_path in rel_paths:
        ext = os.path.splitext(rel_path)[1].lower()
        full_path = os.path.join(root_path, rel_path)

        reviewed_rows = cur.execute(
            "SELECT line_hash, context_hash FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
            (session_id, rel_path),
        ).fetchall()
        if is_apsw:
            reviewed_set = {(r[0], r[1]) for r in reviewed_rows}
        else:
            reviewed_set = {(r["line_hash"], r["context_hash"]) for r in reviewed_rows}

        countable = 0
        reviewed_count = 0
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    file_lines = f.read().splitlines()
                for i, l in enumerate(file_lines):
                    if is_countable_line(l, ext):
                        countable += 1
                        prev = file_lines[i - 1] if i > 0 else ""
                        nxt = file_lines[i + 1] if i < len(file_lines) - 1 else ""
                        if (line_hash(l), context_hash(prev, l, nxt)) in reviewed_set:
                            reviewed_count += 1
            except OSError:
                pass

        coverage = reviewed_count / countable if countable > 0 else 0.0
        result.append({
            "rel_path": rel_path,
            "countable_lines": countable,
            "reviewed_lines": reviewed_count,
            "coverage": coverage,
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
        idx = i
        prev_content = lines[idx - 1] if idx > 0 else ""
        next_content = lines[idx + 1] if idx < len(lines) - 1 else ""
        lh = line_hash(line_content)
        ch = context_hash(prev_content, line_content, next_content)
        is_reviewed = (lh, ch) in reviewed_set
        result_lines.append({
            "line_no": i + 1,
            "content": line_content,
            "line_hash": lh,
            "context_hash": ch,
            "is_reviewed": is_reviewed,
            "is_countable": is_countable_line(line_content, ext, skip_comments),
        })

    note_rows = cur.execute(
        "SELECT id, start_line, end_line, content, is_todo, is_orphaned, snapshot_text, created_at "
        "FROM notes WHERE session_id = ? AND file_path = ? ORDER BY start_line",
        (session_id, fpath),
    ).fetchall()

    def note_to_dict(r):
        if is_apsw:
            return {
                "id": r[0],
                "start_line": r[1],
                "end_line": r[2],
                "content": r[3],
                "is_todo": bool(r[4]),
                "is_orphaned": bool(r[5]),
                "snapshot_text": r[6],
                "created_at": r[7],
            }
        return {
            "id": r["id"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "content": r["content"],
            "is_todo": bool(r["is_todo"]),
            "is_orphaned": bool(r["is_orphaned"]),
            "snapshot_text": r["snapshot_text"],
            "created_at": r["created_at"],
        }

    notes = [note_to_dict(r) for r in note_rows]

    return jsonify({"lines": result_lines, "notes": notes})
