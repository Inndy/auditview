import os
from flask import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash
from auditview.api.util import safe_path

bp = Blueprint("notes", __name__)


def _note_row(r, is_apsw):
    if is_apsw:
        return {
            "id": r[0],
            "file_path": r[1],
            "start_line": r[2],
            "end_line": r[3],
            "content": r[4],
            "is_todo": bool(r[5]),
            "is_orphaned": bool(r[6]),
            "snapshot_text": r[7],
            "created_at": r[8],
            "issue_id": r[9],
        }
    return {
        "id": r["id"],
        "file_path": r["file_path"],
        "start_line": r["start_line"],
        "end_line": r["end_line"],
        "content": r["content"],
        "is_todo": bool(r["is_todo"]),
        "is_orphaned": bool(r["is_orphaned"]),
        "snapshot_text": r["snapshot_text"],
        "created_at": r["created_at"],
        "issue_id": r["issue_id"],
    }


@bp.route("/sessions/<int:session_id>/notes", methods=["GET"])
def list_notes(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    rows = cur.execute(
        "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, snapshot_text, created_at, issue_id "
        "FROM notes WHERE session_id = ? ORDER BY file_path, start_line",
        (session_id,),
    ).fetchall()

    return jsonify([_note_row(r, is_apsw) for r in rows])


@bp.route("/sessions/<int:session_id>/notes", methods=["POST"])
def create_note(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    session_row = cur.execute(
        "SELECT id, root_path FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if session_row is None:
        return jsonify({"error": "Session not found"}), 404

    root_path = session_row[1] if is_apsw else session_row["root_path"]

    data = request.get_json(force=True, silent=True) or {}
    file_path = data.get("file_path", "").strip()
    start_line = data.get("start_line")
    end_line = data.get("end_line")
    content = data.get("content", "").strip()
    is_todo = bool(data.get("is_todo", False))

    if not file_path:
        return jsonify({"error": "file_path is required"}), 400
    if not content:
        return jsonify({"error": "content is required"}), 400
    if start_line is None or end_line is None:
        return jsonify({"error": "start_line and end_line are required"}), 400
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return jsonify({"error": "start_line and end_line must be integers"}), 400
    if start_line > end_line or start_line < 1:
        return jsonify({"error": "invalid line range"}), 400

    full_path = safe_path(root_path, file_path)
    if full_path is None:
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.isfile(full_path):
        return jsonify({"error": "File not found"}), 404

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        file_lines = f.read().splitlines()

    if start_line > len(file_lines) or end_line > len(file_lines):
        return jsonify({"error": "line range out of bounds"}), 400

    start_idx = start_line - 1
    end_idx = end_line - 1
    start_hash = line_hash(file_lines[start_idx])
    end_hash = line_hash(file_lines[end_idx])
    snapshot_text = "\n".join(file_lines[start_idx:end_idx + 1])

    cur.execute(
        "INSERT INTO notes (session_id, file_path, start_line, end_line, start_hash, end_hash, snapshot_text, content, is_todo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, file_path, start_line, end_line, start_hash, end_hash, snapshot_text, content, int(is_todo)),
    )
    if is_apsw:
        row_id = conn.last_insert_rowid()
    else:
        row_id = cur.lastrowid

    row = cur.execute(
        "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, snapshot_text, created_at, issue_id "
        "FROM notes WHERE id = ?",
        (row_id,),
    ).fetchone()

    return jsonify(_note_row(row, is_apsw)), 201


@bp.route("/sessions/<int:session_id>/notes/<int:note_id>", methods=["PATCH"])
def update_note(session_id, note_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    note_row = cur.execute(
        "SELECT id FROM notes WHERE id = ? AND session_id = ?", (note_id, session_id)
    ).fetchone()
    if note_row is None:
        return jsonify({"error": "Note not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    updates = {}
    if "content" in data:
        content = data["content"].strip()
        if not content:
            return jsonify({"error": "content cannot be empty"}), 400
        updates["content"] = content
    if "is_todo" in data:
        updates["is_todo"] = int(bool(data["is_todo"]))

    if not updates:
        return jsonify({"error": "nothing to update"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    cur.execute(
        f"UPDATE notes SET {set_clause} WHERE id = ?",
        (*updates.values(), note_id),
    )

    row = cur.execute(
        "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, snapshot_text, created_at, issue_id "
        "FROM notes WHERE id = ?",
        (note_id,),
    ).fetchone()
    return jsonify(_note_row(row, is_apsw))


@bp.route("/sessions/<int:session_id>/notes/<int:note_id>", methods=["DELETE"])
def delete_note(session_id, note_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    note_row = cur.execute(
        "SELECT id FROM notes WHERE id = ? AND session_id = ?", (note_id, session_id)
    ).fetchone()
    if note_row is None:
        return jsonify({"error": "Note not found"}), 404

    cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    return jsonify({"deleted": True})
