import difflib
import logging
import os

from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.io_utils import read_file_lines, unreviewable_reason

logger = logging.getLogger("auditview")


def build_line_map(old_lines, new_lines):
    """Return (line_map, block_margins).

    - line_map: old_idx -> new_idx for positions inside a matching block.
    - block_margins: old_idx -> (margin_before, margin_after), the number of
      lines inside the same matching block on either side of old_idx.

    Callers use block_margins to refuse migrations where the matched block
    barely surrounds the marked position. SequenceMatcher matches on
    line_hash alone, so a 3-line context (prev/curr/next) accidentally
    reproduced by an insert is enough to anchor a marked row onto a
    sibling occurrence; demanding K lines of intact context on EACH side
    of the marked position raises the bar to "K+1 consecutive identical
    lines centered on the mark survived the edit", which a coincidental
    insert is much less likely to produce.
    """
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    line_map = {}
    block_margins = {}
    for block in sm.get_matching_blocks():
        for i in range(block.size):
            line_map[block.a + i] = block.b + i
            block_margins[block.a + i] = (i, block.size - i - 1)
    return line_map, block_margins


def _build_context_index(new_lines, new_line_hashes):
    """Return (index, counts).

    - index: (line_hash, context_hash) -> 1-indexed new line_no (last writer wins).
    - counts: (line_hash, context_hash) -> total occurrences in the new file.

    Both are derived in one pass. The counts let callers detect ambiguity
    (key occurring more than once) and refuse to migrate marks onto an
    arbitrary occurrence.
    """
    index = {}
    counts = {}
    for i in range(len(new_lines)):
        prev_c = new_lines[i - 1] if i > 0 else ""
        curr_c = new_lines[i]
        next_c = new_lines[i + 1] if i < len(new_lines) - 1 else ""
        k = (new_line_hashes[i], context_hash(prev_c, curr_c, next_c))
        index[k] = i + 1
        counts[k] = counts.get(k, 0) + 1
    return index, counts



_BLOCK_MARGIN_K = 1
"""Minimum number of unedited lines required on each side of a marked
position inside the matched block before we trust the migration.

K=1 matches the 1-line radius that context_hash already verifies (prev +
curr + next). Requiring m_before ≥ 1 and m_after ≥ 1 ensures both
immediate neighbors are confirmed originals in the SequenceMatcher block
rather than inserted copies with identical content. Lower K → fewer false
unmarks; higher FP risk from small verbatim copies (trigger = K+1 lines).

K=5 was previously used to drive the random-fuzz FP rate toward zero, but
it caused excessive mark drops (false unmarks) even when the mark's
immediate context was clearly intact. K=5 also still left known FP edge
cases (see tests/fuzz/saved_seeds/). Accepting a small FP risk is
preferable during active review, where users see the file and can re-check.
"""


async def _reconcile_reviewed(
    conn, rows, new_lines, new_line_hashes, line_map, block_margins, old_line_hashes
):
    if not rows:
        return

    updates = []
    delete_ids = []

    context_index, ctx_counts = _build_context_index(new_lines, new_line_hashes)

    if line_map is not None:
        for row in rows:
            row_id = row["id"]
            old_idx = row["line_no"] - 1
            new_idx = line_map.get(old_idx)
            if new_idx is None:
                delete_ids.append(row_id)
                continue
            prev_content = new_lines[new_idx - 1] if new_idx > 0 else ""
            curr_content = new_lines[new_idx]
            next_content = new_lines[new_idx + 1] if new_idx < len(new_lines) - 1 else ""
            new_ch = context_hash(prev_content, curr_content, next_content)
            new_lh = line_hash(curr_content)
            # Safety: SequenceMatcher gives us old_idx → new_idx directly, so
            # content-uniqueness guards (were #2/#3) are not needed — if the
            # matcher mapped to the wrong sibling, guard #1 catches it because
            # a different sibling has a different context. Guard #4 then
            # ensures the matched block is long enough that the mapping isn't
            # a coincidental short-run anchor.
            #   (1) context_hash at the proposed new position must match what
            #       was stored at review time — catches wrong-sibling mapping
            #       and any change to the immediate surroundings.
            #   (2) the matched block must extend at least K lines on each
            #       side of the marked position (capped at the file edge so
            #       the first/last line are not unfairly penalised).
            if new_ch != row["context_hash"]:
                delete_ids.append(row_id)
                continue
            m_before, m_after = block_margins.get(old_idx, (0, 0))
            k_before = min(_BLOCK_MARGIN_K, old_idx)
            k_after = min(_BLOCK_MARGIN_K, len(old_line_hashes) - 1 - old_idx)
            if m_before < k_before or m_after < k_after:
                delete_ids.append(row_id)
                continue
            new_ln = new_idx + 1
            updates.append((new_ln, new_lh, new_ch, row_id))
    else:
        for row in rows:
            key = (row["line_hash"], row["context_hash"])
            new_ln = context_index.get(key)
            if new_ln is None:
                delete_ids.append(row["id"])
                continue
            if ctx_counts.get(key, 0) > 1:
                # Ambiguous: more than one new line matches the row's
                # stored (lh, ch); the snapshot-less fallback cannot tell
                # them apart, so drop instead of attaching to whichever
                # one happened to be the last writer in the index.
                delete_ids.append(row["id"])
                continue
            if new_ln != row["line_no"]:
                updates.append((new_ln, row["line_hash"], row["context_hash"], row["id"]))

    # UNIQUE is (session_id, file_path, line_hash, context_hash, line_no), so
    # rows with the same (lh, ch) at different line_no coexist. Collisions only
    # happen when two old rows map to the same new_ln (e.g. an edit deletes the
    # unmarked sibling so the marked row slides next to another identical line).
    # Keep the first survivor per (lh, ch, new_ln), drop the rest.
    deduped_updates = []
    seen_keys = set()
    for new_ln, lh, ch, row_id in updates:
        key = (lh, ch, new_ln)
        if key in seen_keys:
            delete_ids.append(row_id)
        else:
            seen_keys.add(key)
            deduped_updates.append((new_ln, lh, ch, row_id))

    # Deletes first: a deleted row may sit at a position that a surviving row
    # is migrating to; removing it before the updates avoids UNIQUE conflicts.
    if delete_ids:
        placeholders = ",".join("?" * len(delete_ids))
        await conn.execute(f"DELETE FROM reviewed_lines WHERE id IN ({placeholders})", delete_ids)
    if deduped_updates:
        # Two-phase update avoids UNIQUE constraint violations when two marks
        # with the same (lh, ch) effectively swap positions: first move all
        # migrating rows to guaranteed-safe negative line_nos, then to their
        # real destinations. Negative line_nos never exist outside this window.
        await conn.executemany(
            "UPDATE reviewed_lines SET line_no = -? WHERE id = ?",
            [(new_ln, row_id) for new_ln, lh, ch, row_id in deduped_updates],
        )
        await conn.executemany(
            "UPDATE reviewed_lines SET line_no = ?, line_hash = ?, context_hash = ? WHERE id = ?",
            deduped_updates,
        )


async def _reconcile_notes(conn, session_id, file_path, new_lines, new_line_hashes, line_map, block_margins, old_line_hashes):
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

            # Apply the same block_margins guard as _reconcile_reviewed: both
            # anchor endpoints must sit deep enough inside their matched block
            # to rule out a coincidental short-run mapping.
            for orig_idx in (start_orig_idx, end_orig_idx):
                m_before, m_after = block_margins.get(orig_idx, (0, 0))
                k_before = min(_BLOCK_MARGIN_K, orig_idx)
                k_after = min(_BLOCK_MARGIN_K, len(old_line_hashes) - 1 - orig_idx)
                if m_before < k_before or m_after < k_after:
                    await conn.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
                    break
            else:
                if new_start_idx > new_end_idx:
                    await conn.execute("UPDATE notes SET is_orphaned = 1 WHERE id = ?", (note_id,))
                elif new_start_idx != start_orig_idx or new_end_idx != end_orig_idx:
                    await conn.execute(
                        "UPDATE notes SET start_line = ?, end_line = ? WHERE id = ?",
                        (new_start_idx + 1, new_end_idx + 1, note_id),
                    )
            continue
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
        reason = unreviewable_reason(full_path)
    except FileNotFoundError:
        # Preserve the deletion path below, which also removes the files row.
        reason = None
    except OSError:
        logger.warning("reconcile_file: cannot classify %s", full_path, exc_info=True)
        return

    if reason is not None:
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            logger.warning("reconcile_file: cannot stat %s", full_path, exc_info=True)
            return
        # Keep marks, notes and the last readable snapshot intact. If the file
        # becomes reviewable again, that snapshot lets the normal reconciler
        # verify them. NULL countability excludes the file from coverage while
        # we deliberately refuse to read its current contents.
        await conn.execute(
            "INSERT INTO files (session_id, rel_path, last_mtime, countable_lines) "
            "VALUES (?, ?, ?, NULL) ON CONFLICT(session_id, rel_path) DO UPDATE SET "
            "last_mtime=excluded.last_mtime, countable_lines=NULL",
            (session_id, file_path, mtime),
        )
        return
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
            logger.exception(
                "reconcile_file: cleanup failed for deleted file %s (session %s)",
                file_path, session_id,
            )
        return
    except OSError:
        logger.warning("reconcile_file: cannot read %s", full_path, exc_info=True)
        return

    ext = os.path.splitext(file_path)[1].lower()
    try:
        mtime = os.path.getmtime(full_path)
    except OSError:
        logger.warning("reconcile_file: cannot stat %s", full_path, exc_info=True)
        return
    countable = sum(1 for l in new_lines if is_countable_line(l, ext))

    # BEGIN here so that _has_migration_state, prev_line_hashes, and
    # reviewed_lines are all read inside the same snapshot. Without this a
    # concurrent /mark POST can insert a row between our reads and our writes,
    # causing the new row to be migrated based on stale snapshot data.
    await conn.execute("BEGIN")
    try:
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
            await conn.execute("COMMIT")
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

        if old_line_hashes and new_line_hashes == old_line_hashes:
            await conn.execute(
                "UPDATE files SET last_mtime = ?, countable_lines = ? "
                "WHERE session_id = ? AND rel_path = ?",
                (mtime, countable, session_id, file_path),
            )
            await conn.execute("COMMIT")
            return

        if old_line_hashes:
            line_map, block_margins = build_line_map(old_line_hashes, new_line_hashes)
        else:
            line_map, block_margins = None, {}

        cur = await conn.execute(
            "SELECT id, line_no, line_hash, context_hash FROM reviewed_lines "
            "WHERE session_id = ? AND file_path = ? ORDER BY line_no",
            (session_id, file_path),
        )
        rows = await cur.fetchall()

        await _reconcile_reviewed(
            conn, rows, new_lines, new_line_hashes, line_map, block_margins, old_line_hashes
        )
        await _reconcile_notes(
            conn, session_id, file_path, new_lines, new_line_hashes,
            line_map, block_margins, old_line_hashes or [],
        )

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
