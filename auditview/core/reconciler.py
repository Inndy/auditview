import difflib
import os

from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.db.checkpoint import CheckpointManager


def build_line_map(old_lines, new_lines):
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    line_map = {}
    for block in sm.get_matching_blocks():
        old_start, new_start, length = block.a, block.b, block.size
        for i in range(length):
            line_map[old_start + i] = new_start + i
    return line_map


def _reconcile_reviewed(cur, rows, new_lines, new_line_hashes,
                         old_line_hashes, is_apsw):
    if not rows:
        return

    if is_apsw:
        row_ids = [r[0] for r in rows]
        old_line_nos = [r[1] for r in rows]
    else:
        row_ids = [r["id"] for r in rows]
        old_line_nos = [r["line_no"] for r in rows]

    if old_line_hashes:
        full_map = build_line_map(old_line_hashes, new_line_hashes)
        for row_id, old_ln in zip(row_ids, old_line_nos):
            old_idx = old_ln - 1
            new_idx = full_map.get(old_idx)
            if new_idx is None:
                cur.execute("DELETE FROM reviewed_lines WHERE id = ?", (row_id,))
            else:
                new_ln = new_idx + 1
                prev_content = new_lines[new_idx - 1] if new_idx > 0 else ""
                curr_content = new_lines[new_idx]
                next_content = new_lines[new_idx + 1] if new_idx < len(new_lines) - 1 else ""
                new_ctx_hash = context_hash(prev_content, curr_content, next_content)
                new_lh = line_hash(curr_content)
                cur.execute(
                    "UPDATE reviewed_lines SET line_no = ?, line_hash = ?, context_hash = ? WHERE id = ?",
                    (new_ln, new_lh, new_ctx_hash, row_id),
                )
    else:
        if is_apsw:
            old_actual_lines = [r[2] for r in rows]
        else:
            old_actual_lines = [r["line_hash"] for r in rows]
        line_map = build_line_map(old_actual_lines, new_line_hashes)
        for i, row_id in enumerate(row_ids):
            if i in line_map:
                new_idx = line_map[i]
                new_ln = new_idx + 1
                prev_content = new_lines[new_idx - 1] if new_idx > 0 else ""
                curr_content = new_lines[new_idx]
                next_content = new_lines[new_idx + 1] if new_idx < len(new_lines) - 1 else ""
                new_ctx_hash = context_hash(prev_content, curr_content, next_content)
                new_lh = line_hash(curr_content)
                cur.execute(
                    "UPDATE reviewed_lines SET line_no = ?, line_hash = ?, context_hash = ? WHERE id = ?",
                    (new_ln, new_lh, new_ctx_hash, row_id),
                )
            else:
                cur.execute("DELETE FROM reviewed_lines WHERE id = ?", (row_id,))


def _reconcile_notes(cur, session_id, file_path, new_lines, new_line_hashes,
                     old_line_hashes, is_apsw):
    note_rows = cur.execute(
        "SELECT id, start_line, end_line, start_hash, end_hash FROM notes "
        "WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
        (session_id, file_path),
    ).fetchall()

    if not note_rows:
        return

    if old_line_hashes:
        full_map = build_line_map(old_line_hashes, new_line_hashes)
    else:
        full_map = None

    for note in note_rows:
        if is_apsw:
            note_id, start_line, end_line, start_hash, end_hash = note
        else:
            note_id = note["id"]
            start_line = note["start_line"]
            end_line = note["end_line"]
            start_hash = note["start_hash"]
            end_hash = note["end_hash"]

        start_orig_idx = start_line - 1
        end_orig_idx = end_line - 1

        if full_map is not None:
            new_start_idx = full_map.get(start_orig_idx)
            new_end_idx = full_map.get(end_orig_idx)

            if new_start_idx is None or new_end_idx is None:
                cur.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
                continue

            if (new_line_hashes[new_start_idx] != start_hash or
                    new_line_hashes[new_end_idx] != end_hash):
                cur.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
                continue

            if new_start_idx > new_end_idx:
                cur.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
            elif new_start_idx != start_orig_idx or new_end_idx != end_orig_idx:
                cur.execute(
                    "UPDATE notes SET start_line = ?, end_line = ? WHERE id = ?",
                    (new_start_idx + 1, new_end_idx + 1, note_id),
                )
        else:
            if (start_orig_idx >= len(new_lines) or
                    new_line_hashes[start_orig_idx] != start_hash or
                    end_orig_idx >= len(new_lines) or
                    new_line_hashes[end_orig_idx] != end_hash):
                cur.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))


def reconcile_file(conn, session_id, file_path, root_path):
    full_path = os.path.join(root_path, file_path)
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return

    new_lines = content.splitlines()
    new_line_hashes = [line_hash(l) for l in new_lines]

    cur = conn.cursor()
    is_apsw = getattr(conn, '_is_apsw', False)

    file_row = cur.execute(
        "SELECT last_mtime, prev_line_hashes FROM files "
        "WHERE session_id = ? AND rel_path = ?",
        (session_id, file_path),
    ).fetchone()

    if file_row is None:
        old_line_hashes = None
    else:
        stored_phashes = file_row[1] if is_apsw else file_row["prev_line_hashes"]
        old_line_hashes = stored_phashes.split("\n") if stored_phashes else None

    rows = cur.execute(
        "SELECT id, line_no, line_hash, context_hash FROM reviewed_lines "
        "WHERE session_id = ? AND file_path = ? ORDER BY line_no",
        (session_id, file_path),
    ).fetchall()

    cm = CheckpointManager(conn)
    if cm.supports_checkpoints():
        cm.begin(session_id)

    conn.begin()

    try:
        _reconcile_reviewed(cur, rows, new_lines, new_line_hashes, old_line_hashes, is_apsw)
        _reconcile_notes(cur, session_id, file_path, new_lines, new_line_hashes,
                         old_line_hashes, is_apsw)

        mtime = os.path.getmtime(full_path)
        new_phashes = "\n".join(new_line_hashes)
        ext = os.path.splitext(file_path)[1].lower()
        countable = sum(1 for l in new_lines if is_countable_line(l, ext))
        cur.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes, countable_lines) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, rel_path) DO UPDATE SET "
            "last_mtime=excluded.last_mtime, prev_line_hashes=excluded.prev_line_hashes, "
            "countable_lines=excluded.countable_lines",
            (session_id, file_path, mtime, new_phashes, countable),
        )

        conn.commit()

        if cm.supports_checkpoints():
            cm.save(f"reconcile:{file_path}")

    except Exception:
        conn.rollback()
        raise
