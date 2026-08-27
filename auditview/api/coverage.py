from quart import Blueprint, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.progress import session_coverage, session_exists

bp = Blueprint("coverage", __name__)


@bp.route("/sessions/<int:session_id>/coverage", methods=["GET"])
async def get_coverage(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        if not await session_exists(conn, session_id):
            return jsonify({"error": "Session not found"}), 404
        result = await session_coverage(conn, session_id)
    return jsonify(result)
