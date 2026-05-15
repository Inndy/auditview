from flask import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db

bp = Blueprint("issues", __name__)


def _row_to_dict(row, is_apsw):
    if is_apsw:
        return {
            "id": row[0],
            "session_id": row[1],
            "title": row[2],
            "severity": row[3],
            "status": row[4],
            "created_at": row[5],
        }
    return dict(row)


@bp.route("/sessions/<int:session_id>/issues", methods=["GET"])
def list_issues(session_id):
    status_filter = request.args.get("status")
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, "_is_apsw", False)
    cur = conn.cursor()

    if status_filter:
        rows = cur.execute(
            "SELECT id, session_id, title, severity, status, created_at "
            "FROM issues WHERE session_id = ? AND status = ? ORDER BY created_at DESC",
            (session_id, status_filter),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, session_id, title, severity, status, created_at "
            "FROM issues WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()

    return jsonify([_row_to_dict(r, is_apsw) for r in rows])


@bp.route("/sessions/<int:session_id>/issues", methods=["POST"])
def create_issue(session_id):
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "").strip()
    severity = data.get("severity", "P2")

    if not title:
        return jsonify({"error": "title is required"}), 400
    if severity not in ("P0", "P1", "P2"):
        return jsonify({"error": "severity must be P0, P1, or P2"}), 400

    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, "_is_apsw", False)
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO issues (session_id, title, severity) VALUES (?, ?, ?)",
        (session_id, title, severity),
    )

    if is_apsw:
        row_id = conn.last_insert_rowid()
    else:
        row_id = cur.lastrowid

    row = cur.execute(
        "SELECT id, session_id, title, severity, status, created_at FROM issues WHERE id = ?",
        (row_id,),
    ).fetchone()

    return jsonify(_row_to_dict(row, is_apsw)), 201


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["PATCH"])
def update_issue(session_id, issue_id):
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title")
    severity = data.get("severity")
    status = data.get("status")

    if severity and severity not in ("P0", "P1", "P2"):
        return jsonify({"error": "severity must be P0, P1, or P2"}), 400
    if status and status not in ("open", "resolved", "dismissed"):
        return jsonify({"error": "status must be open, resolved, or dismissed"}), 400

    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, "_is_apsw", False)
    cur = conn.cursor()

    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if severity is not None:
        updates.append("severity = ?")
        params.append(severity)
    if status is not None:
        updates.append("status = ?")
        params.append(status)

    if not updates:
        return jsonify({"error": "no fields to update"}), 400

    params.extend((session_id, issue_id))
    cur.execute(
        f"UPDATE issues SET {', '.join(updates)} WHERE session_id = ? AND id = ?",
        params,
    )

    row = cur.execute(
        "SELECT id, session_id, title, severity, status, created_at FROM issues WHERE id = ? AND session_id = ?",
        (issue_id, session_id),
    ).fetchone()

    if not row:
        return jsonify({"error": "issue not found"}), 404

    return jsonify(_row_to_dict(row, is_apsw))


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["DELETE"])
def delete_issue(session_id, issue_id):
    conn = open_db(current_app.config["DB_PATH"])
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM issues WHERE id = ? AND session_id = ?",
        (issue_id, session_id),
    )

    return jsonify({"deleted": True})


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>/notes", methods=["GET"])
def list_issue_notes(session_id, issue_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, "_is_apsw", False)
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, snapshot_text, created_at "
        "FROM notes WHERE session_id = ? AND issue_id = ? ORDER BY created_at",
        (session_id, issue_id),
    ).fetchall()

    result = []
    for r in rows:
        if is_apsw:
            result.append({
                "id": r[0],
                "file_path": r[1],
                "start_line": r[2],
                "end_line": r[3],
                "content": r[4],
                "is_todo": r[5],
                "is_orphaned": r[6],
                "snapshot_text": r[7],
                "created_at": r[8],
            })
        else:
            result.append(dict(r))

    return jsonify(result)


@bp.route("/sessions/<int:session_id>/notes/<int:note_id>/issue", methods=["PUT"])
def attach_note_to_issue(session_id, note_id):
    data = request.get_json(force=True, silent=True) or {}
    issue_id = data.get("issue_id")

    if issue_id is None:
        return jsonify({"error": "issue_id is required"}), 400

    conn = open_db(current_app.config["DB_PATH"])
    cur = conn.cursor()

    cur.execute(
        "UPDATE notes SET issue_id = ? WHERE id = ? AND session_id = ?",
        (issue_id, note_id, session_id),
    )

    return jsonify({"attached": True})
