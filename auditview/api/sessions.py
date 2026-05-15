from quart import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db

bp = Blueprint("sessions", __name__)


@bp.route("/sessions", methods=["GET"])
async def list_sessions():
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, label, root_path, exclusion_patterns, created_at FROM sessions ORDER BY id"
        )
        rows = await cur.fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/sessions", methods=["POST"])
async def create_session():
    data = await request.get_json(force=True, silent=True) or {}
    label = data.get("label", "").strip()
    exclusion_patterns = data.get("exclusion_patterns", "")

    if not label:
        return jsonify({"error": "label is required"}), 400

    root_path = current_app.config["ROOT_PATH"]

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "INSERT INTO sessions (label, root_path, exclusion_patterns) VALUES (?, ?, ?)",
            (label, root_path, exclusion_patterns),
        )
        row_id = cur.lastrowid
        cur = await conn.execute(
            "SELECT id, label, root_path, exclusion_patterns, created_at FROM sessions WHERE id = ?",
            (row_id,),
        )
        row = await cur.fetchone()
    return jsonify(dict(row)), 201
