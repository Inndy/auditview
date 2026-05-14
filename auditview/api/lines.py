from flask import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.api.util import safe_path

bp = Blueprint("lines", __name__)


@bp.route("/sessions/<int:session_id>/lines/mark", methods=["POST"])
def mark_lines(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute(
        "SELECT id, root_path FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404
    root_path = row[1] if is_apsw else row["root_path"]

    data = request.get_json(force=True, silent=True) or {}
    file_path = data.get("file_path")
    lines = data.get("lines")
    reviewed = data.get("reviewed")

    if not file_path or lines is None or reviewed is None:
        return jsonify({"error": "file_path, lines, and reviewed are required"}), 400

    if not isinstance(lines, list):
        return jsonify({"error": "lines must be an array"}), 400

    if safe_path(root_path, file_path) is None:
        return jsonify({"error": "Invalid path"}), 400

    count = 0
    conn.begin()
    try:
        for line in lines:
            lh = line.get("line_hash")
            ch = line.get("context_hash")
            ln = line.get("line_no")
            if not lh or not ch or ln is None:
                continue
            if reviewed:
                cur.execute(
                    "INSERT OR REPLACE INTO reviewed_lines "
                    "(session_id, file_path, line_hash, context_hash, line_no) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, file_path, lh, ch, ln),
                )
            else:
                cur.execute(
                    "DELETE FROM reviewed_lines "
                    "WHERE session_id = ? AND file_path = ? AND line_hash = ? AND context_hash = ?",
                    (session_id, file_path, lh, ch),
                )
            count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return jsonify({"updated": count})
