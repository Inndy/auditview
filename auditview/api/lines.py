import os
from quart import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.io_utils import read_file_lines
from auditview.core.reconciler import ensure_snapshot
from auditview.api.util import safe_path

bp = Blueprint("lines", __name__)


@bp.route("/sessions/<int:session_id>/lines/mark", methods=["POST"])
async def mark_lines(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        cur = await conn.execute(
            "SELECT id, root_path FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return jsonify({"error": "Session not found"}), 404
        root_path = row["root_path"]

        data = await request.get_json(force=True, silent=True) or {}
        file_path = data.get("file_path")
        lines = data.get("lines")
        reviewed = data.get("reviewed")

        if not file_path or lines is None or reviewed is None:
            return jsonify({"error": "file_path, lines, and reviewed are required"}), 400
        if not isinstance(lines, list):
            return jsonify({"error": "lines must be an array"}), 400
        full_path = safe_path(root_path, file_path)
        if full_path is None:
            return jsonify({"error": "Invalid path"}), 400
        if not os.path.isfile(full_path):
            return jsonify({"error": "File not found"}), 404

        try:
            file_lines = await read_file_lines(full_path)
        except OSError:
            return jsonify({"error": "Could not read file"}), 500

        valid_keys = set()
        for i, content in enumerate(file_lines):
            prev_c = file_lines[i - 1] if i > 0 else ""
            next_c = file_lines[i + 1] if i < len(file_lines) - 1 else ""
            valid_keys.add((i + 1, line_hash(content), context_hash(prev_c, content, next_c)))

        accepted = []
        rejected = []
        await conn.execute("BEGIN")
        try:
            for line in lines:
                lh = line.get("line_hash")
                ch = line.get("context_hash")
                ln = line.get("line_no")
                if not lh or not ch or ln is None:
                    rejected.append({
                        "line_hash": lh,
                        "context_hash": ch,
                        "line_no": ln,
                        "reason": "missing line_hash, context_hash, or line_no",
                    })
                    continue
                if reviewed:
                    if (ln, lh, ch) not in valid_keys:
                        rejected.append({
                            "line_hash": lh,
                            "context_hash": ch,
                            "line_no": ln,
                            "reason": "stale content: line not found in current file",
                        })
                        continue
                    await conn.execute(
                        "INSERT OR REPLACE INTO reviewed_lines "
                        "(session_id, file_path, line_hash, context_hash, line_no) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (session_id, file_path, lh, ch, ln),
                    )
                else:
                    await conn.execute(
                        "DELETE FROM reviewed_lines "
                        "WHERE session_id = ? AND file_path = ? AND line_hash = ? AND context_hash = ? AND line_no = ?",
                        (session_id, file_path, lh, ch, ln),
                    )
                accepted.append({"line_hash": lh, "context_hash": ch, "line_no": ln})
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

        if reviewed and accepted:
            await ensure_snapshot(conn, session_id, file_path, root_path)

    return jsonify({
        "updated": len(accepted),
        "accepted": accepted,
        "rejected": rejected,
    })
