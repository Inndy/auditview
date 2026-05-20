from pathlib import Path
from quart import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db

bp = Blueprint("config", __name__)


async def _get_mcp_session(conn):
    cur = await conn.execute("SELECT value FROM app_config WHERE key = 'mcp_session_id'")
    row = await cur.fetchone()
    if not row:
        return None
    session_id = int(row["value"])
    cur = await conn.execute(
        "SELECT id, label, root_path FROM sessions WHERE id = ?", (session_id,)
    )
    srow = await cur.fetchone()
    if not srow:
        return None
    return {"id": srow["id"], "label": srow["label"], "root_path": srow["root_path"]}


@bp.route("/config", methods=["GET"])
async def get_config():
    async with open_db(current_app.config["DB_PATH"]) as conn:
        mcp_session = await _get_mcp_session(conn)
    return jsonify({
        "root_path": current_app.config["ROOT_PATH"],
        "db_path": current_app.config["DB_PATH"],
        "mcp_session": mcp_session,
    })


@bp.route("/config/mcp-session", methods=["PUT"])
async def set_mcp_session():
    data = await request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    if not isinstance(session_id, int):
        return jsonify({"error": "session_id required"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "session not found"}), 404
        await conn.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES ('mcp_session_id', ?)",
            (str(session_id),),
        )
        mcp_session = await _get_mcp_session(conn)
    return jsonify({"mcp_session": mcp_session})


@bp.route("/config/mcp-session", methods=["DELETE"])
async def clear_mcp_session():
    async with open_db(current_app.config["DB_PATH"]) as conn:
        await conn.execute("DELETE FROM app_config WHERE key = 'mcp_session_id'")
    return jsonify({"mcp_session": None})


@bp.route("/config/resolve-path", methods=["POST"])
async def resolve_path():
    async with open_db(current_app.config["DB_PATH"]) as conn:
        mcp_session = await _get_mcp_session(conn)
    if not mcp_session:
        return jsonify({"error": "no MCP session active"}), 400

    data = await request.get_json(force=True, silent=True) or {}
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 400

    root = Path(mcp_session["root_path"]).resolve()
    p = Path(path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (root / p).resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return jsonify({"error": "path escapes session root"}), 400

    return jsonify({"rel_path": str(rel), "abs_path": str(resolved)})
