import os
from flask import Blueprint, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.scanner import scan_folder
from auditview.db.checkpoint import CheckpointManager

bp = Blueprint("coverage", __name__)


@bp.route("/sessions/<int:session_id>/coverage", methods=["GET"])
def get_coverage(session_id):
    conn = open_db(current_app.config["DB_PATH"])
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()

    session_row = cur.execute(
        "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None:
        return jsonify({"error": "Session not found"}), 404

    if is_apsw:
        root_path = session_row[1]
        exclusion_patterns = session_row[2]
    else:
        root_path = session_row["root_path"]
        exclusion_patterns = session_row["exclusion_patterns"]

    rel_paths = scan_folder(root_path, exclusion_patterns)

    total_countable = 0
    total_reviewed = 0

    for rel_path in rel_paths:
        ext = os.path.splitext(rel_path)[1].lower()
        full_path = os.path.join(root_path, rel_path)
        if not os.path.isfile(full_path):
            continue
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue

        reviewed_rows = cur.execute(
            "SELECT line_hash, context_hash FROM reviewed_lines "
            "WHERE session_id = ? AND file_path = ?",
            (session_id, rel_path),
        ).fetchall()
        if is_apsw:
            reviewed_set = {(r[0], r[1]) for r in reviewed_rows}
        else:
            reviewed_set = {(r["line_hash"], r["context_hash"]) for r in reviewed_rows}

        for i, l in enumerate(lines):
            if is_countable_line(l, ext):
                total_countable += 1
                prev = lines[i - 1] if i > 0 else ""
                nxt = lines[i + 1] if i < len(lines) - 1 else ""
                if (line_hash(l), context_hash(prev, l, nxt)) in reviewed_set:
                    total_reviewed += 1

    coverage = total_reviewed / total_countable if total_countable > 0 else 0.0

    cm = CheckpointManager(conn)
    supports_cp = cm.supports_checkpoints()

    return jsonify({
        "total_files": len(rel_paths),
        "total_countable_lines": total_countable,
        "total_reviewed_lines": total_reviewed,
        "coverage": coverage,
        "supports_checkpoints": supports_cp,
    })
