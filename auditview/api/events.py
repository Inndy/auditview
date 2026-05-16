import asyncio
import json

from quart import Blueprint, jsonify, current_app, Response

from auditview.db.connection import open_db

bp = Blueprint("events", __name__)


@bp.route("/sessions/<int:session_id>/events", methods=["GET"])
async def event_stream(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        row = await cur.fetchone()
    if row is None:
        return jsonify({"error": "Session not found"}), 404

    watcher = current_app.watcher
    q = watcher.register_client(session_id)

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {event['type']}\ndata: {json.dumps({k: v for k, v in event.items() if k != 'type'})}\n\n"
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            watcher.unregister_client(session_id, q)

    response = Response(generate(), content_type="text/event-stream")
    response.timeout = None
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
