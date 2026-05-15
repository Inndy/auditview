import os
from pathlib import Path
from flask import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db

bp = Blueprint("config", __name__)


def _get_mcp_session(conn):
    is_apsw = getattr(conn, '_is_apsw', False)
    row = conn.cursor().execute(
        "SELECT value FROM app_config WHERE key = 'mcp_session_id'"
    ).fetchone()
    if not row:
        return None
    session_id = int(row[0] if is_apsw else row["value"])
    srow = conn.cursor().execute(
        "SELECT id, label, root_path FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not srow:
        return None
    if is_apsw:
        return {"id": srow[0], "label": srow[1], "root_path": srow[2]}
    return {"id": srow["id"], "label": srow["label"], "root_path": srow["root_path"]}


@bp.route("/config", methods=["GET"])
def get_config():
    conn = open_db(current_app.config["DB_PATH"])
    return jsonify({
        "root_path": current_app.config["ROOT_PATH"],
        "db_path": current_app.config["DB_PATH"],
        "mcp_session": _get_mcp_session(conn),
    })


@bp.route("/config/mcp-session", methods=["PUT"])
def set_mcp_session():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    if not isinstance(session_id, int):
        return jsonify({"error": "session_id required"}), 400

    conn = open_db(current_app.config["DB_PATH"])
    srow = conn.cursor().execute(
        "SELECT id FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not srow:
        return jsonify({"error": "session not found"}), 404

    conn.execute(
        "INSERT OR REPLACE INTO app_config (key, value) VALUES ('mcp_session_id', ?)",
        (str(session_id),),
    )
    return jsonify({"mcp_session": _get_mcp_session(conn)})


@bp.route("/config/mcp-session", methods=["DELETE"])
def clear_mcp_session():
    conn = open_db(current_app.config["DB_PATH"])
    conn.execute("DELETE FROM app_config WHERE key = 'mcp_session_id'")
    return jsonify({"mcp_session": None})


@bp.route("/config/resolve-path", methods=["POST"])
def resolve_path():
    conn = open_db(current_app.config["DB_PATH"])
    mcp_session = _get_mcp_session(conn)
    if not mcp_session:
        return jsonify({"error": "no MCP session active"}), 400

    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 400

    root = Path(mcp_session["root_path"]).resolve()
    p = Path(path)
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            return jsonify({"error": "path escapes session root"}), 400
    else:
        rel = Path(path)
        try:
            (root / rel).resolve().relative_to(root)
        except ValueError:
            return jsonify({"error": "path escapes session root"}), 400

    abs_path = str(root / rel)
    return jsonify({"rel_path": str(rel), "abs_path": abs_path})
