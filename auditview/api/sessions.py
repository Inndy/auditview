from quart import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.scanner import _base_spec

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
    if not isinstance(exclusion_patterns, str):
        return jsonify({"error": "exclusion_patterns must be a string"}), 400
    try:
        _base_spec(exclusion_patterns)
    except Exception as exc:
        return jsonify({"error": f"invalid exclusion pattern: {exc}"}), 400

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


@bp.route("/sessions/<int:session_id>", methods=["PATCH"])
async def update_session(session_id):
    data = await request.get_json(force=True, silent=True) or {}

    updates = []
    params = []
    if "label" in data:
        label = (data.get("label") or "").strip()
        if not label:
            return jsonify({"error": "label must be a non-empty string"}), 400
        updates.append("label = ?")
        params.append(label)
    spec = None
    if "exclusion_patterns" in data:
        patterns = data.get("exclusion_patterns")
        if not isinstance(patterns, str):
            return jsonify({"error": "exclusion_patterns must be a string"}), 400
        # Compile before storing. _base_spec is lru_cached and lru_cache does not
        # memoize exceptions, so an unparseable pattern that reaches the sessions
        # table would raise on every subsequent scan, with no way back through the API.
        try:
            spec = _base_spec(patterns)
        except Exception as exc:
            return jsonify({"error": f"invalid exclusion pattern: {exc}"}), 400
        updates.append("exclusion_patterns = ?")
        params.append(patterns)

    if not updates:
        return jsonify({"error": "nothing to update"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "Session not found"}), 404

        await conn.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            (*params, session_id),
        )
        cur = await conn.execute(
            "SELECT id, label, root_path, exclusion_patterns, created_at FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cur.fetchone()

    current_app.watcher.invalidate_scan(session_id, spec=spec)
    return jsonify(dict(row))
