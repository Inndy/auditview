import os
from flask import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

bp = Blueprint("sessions", __name__)


def _row_to_dict(row, is_apsw):
    if is_apsw:
        return {
            "id": row[0],
            "label": row[1],
            "root_path": row[2],
            "exclusion_patterns": row[3],
            "created_at": row[4],
        }
    return dict(row)


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, label, root_path, exclusion_patterns, created_at FROM sessions ORDER BY id"
    ).fetchall()
    return jsonify([_row_to_dict(r, is_apsw) for r in rows])


@bp.route("/sessions", methods=["POST"])
def create_session():
    data = request.get_json(force=True, silent=True) or {}
    label = data.get("label", "").strip()
    root_path = data.get("root_path", "").strip()
    exclusion_patterns = data.get("exclusion_patterns", "")

    if not label:
        return jsonify({"error": "label is required"}), 400
    if not root_path:
        return jsonify({"error": "root_path is required"}), 400
    if not os.path.isdir(root_path):
        return jsonify({"error": "root_path does not exist or is not a directory"}), 400

    configured_root = os.path.realpath(current_app.config["ROOT_PATH"])
    candidate = os.path.realpath(root_path)
    if candidate != configured_root and not candidate.startswith(configured_root + os.sep):
        return jsonify({"error": "root_path must be within the configured audit root"}), 400

    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (label, root_path, exclusion_patterns) VALUES (?, ?, ?)",
        (label, root_path, exclusion_patterns),
    )
    if is_apsw:
        row_id = conn.last_insert_rowid()
    else:
        row_id = cur.lastrowid

    row = cur.execute(
        "SELECT id, label, root_path, exclusion_patterns, created_at FROM sessions WHERE id = ?",
        (row_id,),
    ).fetchone()
    return jsonify(_row_to_dict(row, is_apsw)), 201
