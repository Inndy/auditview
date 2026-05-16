import os
from quart import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.io_utils import read_file_lines
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
        skip_comments = bool(data.get("skip_comments", True))

        if not file_path or lines is None or reviewed is None:
            return jsonify({"error": "file_path, lines, and reviewed are required"}), 400
        if not isinstance(lines, list):
            return jsonify({"error": "lines must be an array"}), 400
        full_path = safe_path(root_path, file_path)
        if full_path is None:
            return jsonify({"error": "Invalid path"}), 400
        if not os.path.isfile(full_path):
            return jsonify({"error": "File not found"}), 404

        ext = os.path.splitext(file_path)[1].lower()
        try:
            file_lines = await read_file_lines(full_path)
        except OSError:
            return jsonify({"error": "Could not read file"}), 500

        countable_keys = set()
        for i, content in enumerate(file_lines):
            if is_countable_line(content, ext, skip_comments):
                prev_c = file_lines[i - 1] if i > 0 else ""
                next_c = file_lines[i + 1] if i < len(file_lines) - 1 else ""
                countable_keys.add((i + 1, line_hash(content), context_hash(prev_c, content, next_c)))

        count = 0
        await conn.execute("BEGIN")
        try:
            for line in lines:
                lh = line.get("line_hash")
                ch = line.get("context_hash")
                ln = line.get("line_no")
                if not lh or not ch or ln is None:
                    continue
                if reviewed:
                    if (ln, lh, ch) not in countable_keys:
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
                        "WHERE session_id = ? AND file_path = ? AND line_hash = ? AND context_hash = ?",
                        (session_id, file_path, lh, ch),
                    )
                count += 1
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    return jsonify({"updated": count})
