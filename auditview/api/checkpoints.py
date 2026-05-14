from flask import Blueprint, jsonify, current_app
from auditview.db.connection import open_db
from auditview.db.checkpoint import CheckpointManager

bp = Blueprint("checkpoints", __name__)


@bp.route("/sessions/<int:session_id>/checkpoints", methods=["GET"])
def list_checkpoints(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    rows = cur.execute(
        "SELECT id, label, created_at FROM checkpoints WHERE session_id = ? ORDER BY id DESC",
        (session_id,),
    ).fetchall()

    def to_dict(r):
        if is_apsw:
            return {"id": r[0], "label": r[1], "created_at": r[2]}
        return {"id": r["id"], "label": r["label"], "created_at": r["created_at"]}

    return jsonify([to_dict(r) for r in rows])


@bp.route("/sessions/<int:session_id>/checkpoints/<int:checkpoint_id>/revert", methods=["POST"])
def revert_checkpoint(session_id, checkpoint_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    cm = CheckpointManager(conn)
    if not cm.supports_checkpoints():
        return jsonify({"error": "Checkpoints not supported: apsw not available"}), 409

    cp_row = cur.execute(
        "SELECT id FROM checkpoints WHERE id = ? AND session_id = ?",
        (checkpoint_id, session_id),
    ).fetchone()
    if cp_row is None:
        return jsonify({"error": "Checkpoint not found"}), 404

    try:
        cm.revert(checkpoint_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Revert failed: {e}"}), 500

    return jsonify({"reverted": True})
