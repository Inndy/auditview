from quart import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db

bp = Blueprint("issues", __name__)


@bp.route("/sessions/<int:session_id>/issues", methods=["GET"])
async def list_issues(session_id):
    status_filter = request.args.get("status")
    async with open_db(current_app.config["DB_PATH"]) as conn:
        if status_filter:
            cur = await conn.execute(
                "SELECT id, session_id, title, severity, status, created_at "
                "FROM issues WHERE session_id = ? AND status = ? ORDER BY created_at DESC",
                (session_id, status_filter),
            )
        else:
            cur = await conn.execute(
                "SELECT id, session_id, title, severity, status, created_at "
                "FROM issues WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            )
        rows = await cur.fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/sessions/<int:session_id>/issues", methods=["POST"])
async def create_issue(session_id):
    data = await request.get_json(force=True, silent=True) or {}
    title = data.get("title", "").strip()
    severity = data.get("severity", "P2")

    if not title:
        return jsonify({"error": "title is required"}), 400
    if severity not in ("P0", "P1", "P2"):
        return jsonify({"error": "severity must be P0, P1, or P2"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "Session not found"}), 404

        cur = await conn.execute(
            "INSERT INTO issues (session_id, title, severity) VALUES (?, ?, ?)",
            (session_id, title, severity),
        )
        row_id = cur.lastrowid
        cur = await conn.execute(
            "SELECT id, session_id, title, severity, status, created_at FROM issues WHERE id = ?",
            (row_id,),
        )
        row = await cur.fetchone()
    return jsonify(dict(row)), 201


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["PATCH"])
async def update_issue(session_id, issue_id):
    data = await request.get_json(force=True, silent=True) or {}
    title = data.get("title")
    severity = data.get("severity")
    status = data.get("status")

    if title is not None:
        title = title.strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
    if severity is not None and severity not in ("P0", "P1", "P2"):
        return jsonify({"error": "severity must be P0, P1, or P2"}), 400
    if status is not None and status not in ("open", "resolved", "dismissed"):
        return jsonify({"error": "status must be open, resolved, or dismissed"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if severity is not None:
            updates.append("severity = ?")
            params.append(severity)
        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if not updates:
            return jsonify({"error": "no fields to update"}), 400

        params.extend((session_id, issue_id))
        await conn.execute(
            f"UPDATE issues SET {', '.join(updates)} WHERE session_id = ? AND id = ?",
            params,
        )
        cur = await conn.execute(
            "SELECT id, session_id, title, severity, status, created_at FROM issues WHERE id = ? AND session_id = ?",
            (issue_id, session_id),
        )
        row = await cur.fetchone()

    if not row:
        return jsonify({"error": "issue not found"}), 404
    return jsonify(dict(row))


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["DELETE"])
async def delete_issue(session_id, issue_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        await conn.execute("BEGIN")
        try:
            await conn.execute(
                "UPDATE notes SET issue_id = NULL WHERE issue_id = ? AND session_id = ?",
                (issue_id, session_id),
            )
            await conn.execute(
                "DELETE FROM issues WHERE id = ? AND session_id = ?",
                (issue_id, session_id),
            )
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
    return jsonify({"deleted": True})


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>/notes", methods=["GET"])
async def list_issue_notes(session_id, issue_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, snapshot_text, created_at "
            "FROM notes WHERE session_id = ? AND issue_id = ? ORDER BY created_at",
            (session_id, issue_id),
        )
        rows = await cur.fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/sessions/<int:session_id>/notes/<int:note_id>/issue", methods=["PUT"])
async def attach_note_to_issue(session_id, note_id):
    data = await request.get_json(force=True, silent=True) or {}
    issue_id = data.get("issue_id")

    if issue_id is None:
        return jsonify({"error": "issue_id is required"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id FROM notes WHERE id = ? AND session_id = ?", (note_id, session_id)
        )
        if await cur.fetchone() is None:
            return jsonify({"error": "Note not found"}), 404

        cur = await conn.execute(
            "SELECT id FROM issues WHERE id = ? AND session_id = ?", (issue_id, session_id)
        )
        if await cur.fetchone() is None:
            return jsonify({"error": "Issue not found"}), 404

        await conn.execute(
            "UPDATE notes SET issue_id = ? WHERE id = ? AND session_id = ?",
            (issue_id, note_id, session_id),
        )
    return jsonify({"attached": True})
