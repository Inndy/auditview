import difflib
import os

from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.io_utils import read_file_lines


def build_line_map(old_lines, new_lines):
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    line_map = {}
    for block in sm.get_matching_blocks():
        old_start, new_start, length = block.a, block.b, block.size
        for i in range(length):
            line_map[old_start + i] = new_start + i
    return line_map


def _build_context_index(new_lines, new_line_hashes):
    index = {}
    for i in range(len(new_lines)):
        prev_c = new_lines[i - 1] if i > 0 else ""
        curr_c = new_lines[i]
        next_c = new_lines[i + 1] if i < len(new_lines) - 1 else ""
        index[(new_line_hashes[i], context_hash(prev_c, curr_c, next_c))] = i + 1
    return index


async def _reconcile_reviewed(conn, rows, new_lines, new_line_hashes, line_map):
    if not rows:
        return

    updates = []
    delete_ids = []

    if line_map is not None:
        for row in rows:
            row_id = row["id"]
            old_idx = row["line_no"] - 1
            new_idx = line_map.get(old_idx)
            if new_idx is None:
                delete_ids.append(row_id)
            else:
                new_ln = new_idx + 1
                prev_content = new_lines[new_idx - 1] if new_idx > 0 else ""
                curr_content = new_lines[new_idx]
                next_content = new_lines[new_idx + 1] if new_idx < len(new_lines) - 1 else ""
                updates.append((new_ln, line_hash(curr_content), context_hash(prev_content, curr_content, next_content), row_id))
    else:
        context_index = _build_context_index(new_lines, new_line_hashes)
        for row in rows:
            key = (row["line_hash"], row["context_hash"])
            new_ln = context_index.get(key)
            if new_ln is None:
                delete_ids.append(row["id"])
            elif new_ln != row["line_no"]:
                updates.append((new_ln, row["line_hash"], row["context_hash"], row["id"]))

    # An edit can collapse two previously distinct reviewed lines into the
    # same (line_hash, context_hash). UNIQUE(session_id, file_path, line_hash,
    # context_hash) would then reject the second UPDATE and roll back the
    # whole reconcile. Keep the first survivor per key, drop the rest.
    deduped_updates = []
    seen_keys = set()
    for new_ln, lh, ch, row_id in updates:
        key = (lh, ch)
        if key in seen_keys:
            delete_ids.append(row_id)
        else:
            seen_keys.add(key)
            deduped_updates.append((new_ln, lh, ch, row_id))

    if deduped_updates:
        await conn.executemany(
            "UPDATE reviewed_lines SET line_no = ?, line_hash = ?, context_hash = ? WHERE id = ?",
            deduped_updates,
        )
    if delete_ids:
        placeholders = ",".join("?" * len(delete_ids))
        await conn.execute(f"DELETE FROM reviewed_lines WHERE id IN ({placeholders})", delete_ids)


async def _reconcile_notes(conn, session_id, file_path, new_lines, new_line_hashes, line_map):
    cur = await conn.execute(
        "SELECT id, start_line, end_line, start_hash, end_hash FROM notes "
        "WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
        (session_id, file_path),
    )
    note_rows = await cur.fetchall()

    if not note_rows:
        return

    for note in note_rows:
        note_id = note["id"]
        start_line = note["start_line"]
        end_line = note["end_line"]
        start_hash = note["start_hash"]
        end_hash = note["end_hash"]

        start_orig_idx = start_line - 1
        end_orig_idx = end_line - 1

        if line_map is not None:
            new_start_idx = line_map.get(start_orig_idx)
            new_end_idx = line_map.get(end_orig_idx)

            if new_start_idx is None or new_end_idx is None:
                await conn.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
                continue

            if (new_line_hashes[new_start_idx] != start_hash or
                    new_line_hashes[new_end_idx] != end_hash):
                await conn.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
                continue

            if new_start_idx > new_end_idx:
                await conn.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
            elif new_start_idx != start_orig_idx or new_end_idx != end_orig_idx:
                await conn.execute(
                    "UPDATE notes SET start_line = ?, end_line = ? WHERE id = ?",
                    (new_start_idx + 1, new_end_idx + 1, note_id),
                )
        else:
            if (start_orig_idx >= len(new_lines) or
                    new_line_hashes[start_orig_idx] != start_hash or
                    end_orig_idx >= len(new_lines) or
                    new_line_hashes[end_orig_idx] != end_hash):
                await conn.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))


async def _has_migration_state(conn, session_id, file_path):
    cur = await conn.execute(
        "SELECT "
        "  EXISTS(SELECT 1 FROM reviewed_lines WHERE session_id = ? AND file_path = ?) "
        "  OR EXISTS(SELECT 1 FROM notes WHERE session_id = ? AND file_path = ? AND is_orphaned = 0) "
        "  AS has_state",
        (session_id, file_path, session_id, file_path),
    )
    row = await cur.fetchone()
    return bool(row["has_state"])


async def ensure_snapshot(conn, session_id, file_path, root_path):
    """Populate prev_line_hashes for a file if not yet stored.

    Call when reviewed lines or notes are first attached to a file so the next
    reconcile can run line-map migration instead of context-hash fallback.
    """
    cur = await conn.execute(
        "SELECT prev_line_hashes FROM files WHERE session_id = ? AND rel_path = ?",
        (session_id, file_path),
    )
    row = await cur.fetchone()
    if row is not None and row["prev_line_hashes"]:
        return

    full_path = os.path.join(root_path, file_path)
    try:
        lines = await read_file_lines(full_path)
    except (FileNotFoundError, OSError):
        return

    new_phashes = "\n".join(line_hash(l) for l in lines)
    mtime = os.path.getmtime(full_path)
    ext = os.path.splitext(file_path)[1].lower()
    countable = sum(1 for l in lines if is_countable_line(l, ext))
    await conn.execute(
        "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes, countable_lines) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(session_id, rel_path) DO UPDATE SET "
        "last_mtime=excluded.last_mtime, prev_line_hashes=excluded.prev_line_hashes, "
        "countable_lines=excluded.countable_lines",
        (session_id, file_path, mtime, new_phashes, countable),
    )


async def reconcile_file(conn, session_id, file_path, root_path):
    full_path = os.path.join(root_path, file_path)
    try:
        new_lines = await read_file_lines(full_path)
    except FileNotFoundError:
        await conn.execute("BEGIN")
        try:
            await conn.execute(
                "UPDATE notes SET is_orphaned = 1 WHERE session_id = ? AND file_path = ? AND is_orphaned = 0",
                (session_id, file_path),
            )
            await conn.execute(
                "DELETE FROM reviewed_lines WHERE session_id = ? AND file_path = ?",
                (session_id, file_path),
            )
            await conn.execute(
                "DELETE FROM files WHERE session_id = ? AND rel_path = ?",
                (session_id, file_path),
            )
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
        return

    ext = os.path.splitext(file_path)[1].lower()
    mtime = os.path.getmtime(full_path)
    countable = sum(1 for l in new_lines if is_countable_line(l, ext))

    has_state = await _has_migration_state(conn, session_id, file_path)

    if not has_state:
        # No reviewed lines or live notes to migrate. Skip per-line hashing,
        # SequenceMatcher, and the snapshot write — those exist solely to
        # support migration. Just refresh mtime/countable and drop any stale
        # snapshot from a prior version of this file.
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes, countable_lines) "
            "VALUES (?, ?, ?, NULL, ?) "
            "ON CONFLICT(session_id, rel_path) DO UPDATE SET "
            "last_mtime=excluded.last_mtime, prev_line_hashes=NULL, "
            "countable_lines=excluded.countable_lines",
            (session_id, file_path, mtime, countable),
        )
        return

    new_line_hashes = [line_hash(l) for l in new_lines]

    cur = await conn.execute(
        "SELECT prev_line_hashes FROM files WHERE session_id = ? AND rel_path = ?",
        (session_id, file_path),
    )
    file_row = await cur.fetchone()

    if file_row is None:
        old_line_hashes = None
    else:
        stored_phashes = file_row["prev_line_hashes"]
        old_line_hashes = stored_phashes.split("\n") if stored_phashes else None

    line_map = build_line_map(old_line_hashes, new_line_hashes) if old_line_hashes else None

    cur = await conn.execute(
        "SELECT id, line_no, line_hash, context_hash FROM reviewed_lines "
        "WHERE session_id = ? AND file_path = ? ORDER BY line_no",
        (session_id, file_path),
    )
    rows = await cur.fetchall()

    await conn.execute("BEGIN")
    try:
        await _reconcile_reviewed(conn, rows, new_lines, new_line_hashes, line_map)
        await _reconcile_notes(conn, session_id, file_path, new_lines, new_line_hashes, line_map)

        new_phashes = "\n".join(new_line_hashes)
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes, countable_lines) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, rel_path) DO UPDATE SET "
            "last_mtime=excluded.last_mtime, prev_line_hashes=excluded.prev_line_hashes, "
            "countable_lines=excluded.countable_lines",
            (session_id, file_path, mtime, new_phashes, countable),
        )
        await conn.execute("COMMIT")
    except Exception:
        await conn.execute("ROLLBACK")
        raise
