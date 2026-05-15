from quart import Blueprint, jsonify, current_app
from auditview.db.connection import open_db

bp = Blueprint("coverage", __name__)


@bp.route("/sessions/<int:session_id>/coverage", methods=["GET"])
async def get_coverage(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "Session not found"}), 404

        cur = await conn.execute(
            "SELECT COUNT(*) AS total_files, COALESCE(SUM(countable_lines), 0) AS total_countable "
            "FROM files WHERE session_id = ? AND countable_lines IS NOT NULL",
            (session_id,),
        )
        file_agg = await cur.fetchone()

        cur = await conn.execute(
            "SELECT COUNT(*) AS total_reviewed FROM reviewed_lines WHERE session_id = ?",
            (session_id,),
        )
        rl_agg = await cur.fetchone()

    total_countable = file_agg["total_countable"]
    total_reviewed = rl_agg["total_reviewed"]
    coverage = total_reviewed / total_countable if total_countable > 0 else 0.0

    return jsonify({
        "total_files": file_agg["total_files"],
        "total_countable_lines": total_countable,
        "total_reviewed_lines": total_reviewed,
        "coverage": coverage,
    })
