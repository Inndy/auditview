from flask import Blueprint, jsonify, request, current_app
from auditview.db.connection import open_db
from auditview.db.checkpoint import CheckpointManager

bp = Blueprint("checkpoints", __name__)


@bp.route("/sessions/<int:session_id>/checkpoints", methods=["POST"])
def create_checkpoint(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    body = request.get_json(silent=True) or {}
    label = (body.get("label") or "").strip() or "manual"

    cm = CheckpointManager(conn)
    cm.save_snapshot(session_id, label)
    conn.commit()

    cp = cur.execute(
        "SELECT id, label, created_at FROM checkpoints WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    is_apsw = getattr(conn, '_is_apsw', False)
    if is_apsw:
        result = {"id": cp[0], "label": cp[1], "created_at": cp[2]}
    else:
        result = {"id": cp["id"], "label": cp["label"], "created_at": cp["created_at"]}
    return jsonify(result), 201


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
