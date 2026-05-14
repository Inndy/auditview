from flask import Blueprint, jsonify, current_app
from auditview.db.connection import open_db
from auditview.db.checkpoint import CheckpointManager

bp = Blueprint("coverage", __name__)


@bp.route("/sessions/<int:session_id>/coverage", methods=["GET"])
def get_coverage(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    # Aggregate using cached countable_lines and indexed reviewed_lines count
    agg = cur.execute(
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
    ).fetchone()

    total_files = agg[0] if is_apsw else agg["total_files"]
    total_countable = agg[1] if is_apsw else agg["total_countable"]
    total_reviewed = agg[2] if is_apsw else agg["total_reviewed"]

    coverage = total_reviewed / total_countable if total_countable > 0 else 0.0

    cm = CheckpointManager(conn)

    return jsonify({
        "total_files": total_files,
        "total_countable_lines": total_countable,
        "total_reviewed_lines": total_reviewed,
        "coverage": coverage,
        "supports_checkpoints": cm.supports_checkpoints(),
    })
