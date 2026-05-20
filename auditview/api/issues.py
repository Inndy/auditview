from quart import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.api.notes import NOTE_SELECT_COLUMNS, NOTE_SELECT_FROM, note_row

bp = Blueprint("issues", __name__)

_ISSUE_COLUMNS = "id, session_id, title, description, severity, status, source, closed_by, created_at"


async def _broadcast_notes_by_ids(conn, session_id, note_ids):
    if not note_ids:
        return
    placeholders = ",".join("?" * len(note_ids))
    cur = await conn.execute(
        f"SELECT {NOTE_SELECT_COLUMNS} FROM {NOTE_SELECT_FROM} "
        f"WHERE n.session_id = ? AND n.id IN ({placeholders})",
        (session_id, *note_ids),
    )
    rows = await cur.fetchall()
    for r in rows:
        current_app.watcher.broadcast_to_session(session_id, {
            "type": "annotation_changed",
            "kind": "note",
            "action": "update",
            "note": note_row(r),
        })


async def _broadcast_notes_by_issue(conn, session_id, issue_id):
    cur = await conn.execute(
        f"SELECT {NOTE_SELECT_COLUMNS} FROM {NOTE_SELECT_FROM} "
        "WHERE n.session_id = ? AND n.issue_id = ?",
        (session_id, issue_id),
    )
    rows = await cur.fetchall()
    for r in rows:
        current_app.watcher.broadcast_to_session(session_id, {
            "type": "annotation_changed",
            "kind": "note",
            "action": "update",
            "note": note_row(r),
        })


@bp.route("/sessions/<int:session_id>/issues", methods=["GET"])
async def list_issues(session_id):
    status_filter = request.args.get("status")
    file_path_filter = request.args.get("file_path")
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "session not found"}), 404

        conditions = ["i.session_id = ?"]
        params = [session_id]
        from_clause = "issues i"

        if file_path_filter:
            from_clause = (
                "issues i JOIN notes n ON n.issue_id = i.id AND n.is_orphaned = 0"
            )
            conditions.append("n.file_path = ?")
            params.append(file_path_filter)

        if status_filter:
            conditions.append("i.status = ?")
            params.append(status_filter)

        cols = ", ".join(f"i.{c}" for c in _ISSUE_COLUMNS.split(", "))
        distinct = "DISTINCT " if file_path_filter else ""
        cur = await conn.execute(
            f"SELECT {distinct}{cols} FROM {from_clause} "
            f"WHERE {' AND '.join(conditions)} ORDER BY i.created_at DESC",
            params,
        )
        rows = await cur.fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["GET"])
async def get_issue(session_id, issue_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            f"SELECT {_ISSUE_COLUMNS} "
            "FROM issues WHERE id = ? AND session_id = ?",
            (issue_id, session_id),
        )
        row = await cur.fetchone()
    if not row:
        return jsonify({"error": "issue not found"}), 404
    return jsonify(dict(row))


@bp.route("/sessions/<int:session_id>/issues", methods=["POST"])
async def create_issue(session_id):
    data = await request.get_json(force=True, silent=True) or {}
    title = data.get("title", "").strip()
    severity = data.get("severity", "P2")
    description = data.get("description", "")
    note_ids = data.get("note_ids", [])
    source = data.get("source") or None

    if not title:
        return jsonify({"error": "title is required"}), 400
    if severity not in ("P0", "P1", "P2"):
        return jsonify({"error": "severity must be P0, P1, or P2"}), 400
    if not isinstance(description, str):
        return jsonify({"error": "description must be a string"}), 400
    if not isinstance(note_ids, list) or not all(isinstance(n, int) for n in note_ids):
        return jsonify({"error": "note_ids must be an array of integers"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "Session not found"}), 404

        if note_ids:
            placeholders = ",".join("?" * len(note_ids))
            cur = await conn.execute(
                f"SELECT id FROM notes WHERE session_id = ? AND id IN ({placeholders})",
                (session_id, *note_ids),
            )
            found = {r["id"] for r in await cur.fetchall()}
            missing = [n for n in note_ids if n not in found]
            if missing:
                return jsonify({
                    "error": "some note_ids do not exist in this session",
                    "missing": missing,
                }), 400

        await conn.execute("BEGIN")
        try:
            cur = await conn.execute(
                "INSERT INTO issues (session_id, title, description, severity, source) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, description, severity, source),
            )
            row_id = cur.lastrowid
            if note_ids:
                await conn.executemany(
                    "UPDATE notes SET issue_id = ? WHERE id = ? AND session_id = ?",
                    [(row_id, nid, session_id) for nid in note_ids],
                )
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

        cur = await conn.execute(
            f"SELECT {_ISSUE_COLUMNS} FROM issues WHERE id = ?",
            (row_id,),
        )
        row = await cur.fetchone()
        issue_dict = dict(row)
        current_app.watcher.broadcast_to_session(session_id, {
            "type": "annotation_changed",
            "kind": "issue",
            "action": "create",
            "issue": issue_dict,
        })
        await _broadcast_notes_by_ids(conn, session_id, note_ids)
    return jsonify(issue_dict), 201


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["PATCH"])
async def update_issue(session_id, issue_id):
    data = await request.get_json(force=True, silent=True) or {}
    title = data.get("title")
    severity = data.get("severity")
    status = data.get("status")
    description = data.get("description")
    actor = data.get("actor") or None

    if title is not None:
        title = title.strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
    if severity is not None and severity not in ("P0", "P1", "P2"):
        return jsonify({"error": "severity must be P0, P1, or P2"}), 400
    if status is not None and status not in ("open", "resolved", "dismissed"):
        return jsonify({"error": "status must be open, resolved, or dismissed"}), 400
    if description is not None and not isinstance(description, str):
        return jsonify({"error": "description must be a string"}), 400

    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "session not found"}), 404

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
            if status in ("resolved", "dismissed"):
                updates.append("closed_by = ?")
                params.append(actor)
            elif status == "open":
                updates.append("closed_by = ?")
                params.append(None)
        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if not updates:
            return jsonify({"error": "no fields to update"}), 400

        params.extend((session_id, issue_id))
        await conn.execute(
            f"UPDATE issues SET {', '.join(updates)} WHERE session_id = ? AND id = ?",
            params,
        )
        cur = await conn.execute(
            f"SELECT {_ISSUE_COLUMNS} FROM issues WHERE id = ? AND session_id = ?",
            (issue_id, session_id),
        )
        row = await cur.fetchone()
        if not row:
            return jsonify({"error": "issue not found"}), 404

        issue_dict = dict(row)
        current_app.watcher.broadcast_to_session(session_id, {
            "type": "annotation_changed",
            "kind": "issue",
            "action": "update",
            "issue": issue_dict,
        })
        if severity is not None:
            await _broadcast_notes_by_issue(conn, session_id, issue_id)
    return jsonify(issue_dict)


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>", methods=["DELETE"])
async def delete_issue(session_id, issue_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        await conn.execute("BEGIN")
        try:
            cur = await conn.execute(
                "SELECT id FROM notes WHERE issue_id = ? AND session_id = ?",
                (issue_id, session_id),
            )
            affected_note_ids = [r["id"] for r in await cur.fetchall()]
            await conn.execute(
                "UPDATE notes SET issue_id = NULL WHERE issue_id = ? AND session_id = ?",
                (issue_id, session_id),
            )
            cur = await conn.execute(
                "DELETE FROM issues WHERE id = ? AND session_id = ?",
                (issue_id, session_id),
            )
            deleted = cur.rowcount
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

        if not deleted:
            return jsonify({"error": "issue not found"}), 404
        current_app.watcher.broadcast_to_session(session_id, {
            "type": "annotation_changed",
            "kind": "issue",
            "action": "delete",
            "id": issue_id,
        })
        await _broadcast_notes_by_ids(conn, session_id, affected_note_ids)
    return jsonify({"deleted": True})


@bp.route("/sessions/<int:session_id>/issues/<int:issue_id>/notes", methods=["GET"])
async def list_issue_notes(session_id, issue_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if await cur.fetchone() is None:
            return jsonify({"error": "session not found"}), 404

        cur = await conn.execute(
            f"SELECT {NOTE_SELECT_COLUMNS} FROM {NOTE_SELECT_FROM} "
            "WHERE n.session_id = ? AND n.issue_id = ? ORDER BY n.created_at",
            (session_id, issue_id),
        )
        rows = await cur.fetchall()
    return jsonify([note_row(r) for r in rows])


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
        await _broadcast_notes_by_ids(conn, session_id, [note_id])
    return jsonify({"attached": True})
