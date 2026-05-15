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
            """
            SELECT
                COUNT(f.id) AS total_files,
                COALESCE(SUM(f.countable_lines), 0) AS total_countable,
                COUNT(DISTINCT rl.file_path || '|' || rl.line_hash || '|' || rl.context_hash)
                    AS total_reviewed
            FROM files f
            LEFT JOIN reviewed_lines rl
                ON rl.session_id = f.session_id AND rl.file_path = f.rel_path
            WHERE f.session_id = ? AND f.countable_lines IS NOT NULL
            """,
            (session_id,),
        )
        agg = await cur.fetchone()

    total_countable = agg["total_countable"]
    total_reviewed = agg["total_reviewed"]
    coverage = total_reviewed / total_countable if total_countable > 0 else 0.0

    return jsonify({
        "total_files": agg["total_files"],
        "total_countable_lines": total_countable,
        "total_reviewed_lines": total_reviewed,
        "coverage": coverage,
    })
