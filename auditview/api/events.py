import json
import queue

from flask import Blueprint, jsonify, current_app, Response

from auditview.db.connection import open_db

bp = Blueprint("events", __name__)


@bp.route("/sessions/<int:session_id>/events", methods=["GET"])
def event_stream(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    watcher = current_app.watcher
    q = watcher.register_client(session_id)

    def generate():
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"event: {event['type']}\ndata: {json.dumps({k: v for k, v in event.items() if k != 'type'})}\n\n"
                except queue.Empty:
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            watcher.unregister_client(session_id, q)

    return Response(generate(), content_type="text/event-stream")
