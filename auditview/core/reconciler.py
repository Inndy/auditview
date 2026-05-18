import difflib
import os

from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.io_utils import read_file_lines


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


def _build_old_hash_context_counts(old_line_hashes):
    """Count, for each old line, how many other old lines share the same
    (line_hash, prev_line_hash, next_line_hash) signature.

    Only line hashes are persisted in the snapshot, so we can't recover the
    raw content needed to recompute the user-facing context_hash. The
    hash-of-hashes triple is just as discriminating in practice (SHA-256
    collisions are negligible) and is the strongest uniqueness signal we
    can produce from the snapshot alone.
    """
    counts = {}
    n = len(old_line_hashes)
    for i in range(n):
        prev_h = old_line_hashes[i - 1] if i > 0 else ""
        next_h = old_line_hashes[i + 1] if i < n - 1 else ""
        k = (old_line_hashes[i], prev_h, next_h)
        counts[k] = counts.get(k, 0) + 1
    return counts


_BLOCK_MARGIN_K = 5
"""Minimum number of unedited lines required on each side of a marked
position inside the matched block before we trust the migration.

Picked empirically with the reconciler fuzzer: K=5 was the smallest value
that drove the false-positive rate to zero across 1000 random scenarios
(seeds 0..999) where inserts can copy 1-10 line sections verbatim from the
original file. Smaller K leaves a long tail of FPs in which a coincidental
section copy reproduces 4+ lines around the marked position; larger K just
inflates the false-unmark count without further FP reduction. See
feedback memory `feedback_reviewed_state_safety` — FN is acceptable here,
FP is not.
"""


async def _reconcile_reviewed(
    conn, rows, new_lines, new_line_hashes, line_map, block_margins, old_line_hashes
):
    if not rows:
        return

    updates = []
    delete_ids = []

    context_index, ctx_counts = _build_context_index(new_lines, new_line_hashes)
    old_hash_counts = (
        _build_old_hash_context_counts(old_line_hashes) if old_line_hashes else None
    )

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
            # Safety: SequenceMatcher matches on line_hash alone, so with
            # duplicate content it can align the marked line's old position
            # to a *sibling* occurrence in the new file. Four guards:
            #   (1) the row's stored context_hash (prev/curr/next from the
            #       user's review-time view) must equal the new context at
            #       the proposed position — otherwise the surroundings
            #       changed and we cannot claim it's the same line.
            #   (2) the (lh, ch) pair must be UNIQUE in the new file —
            #       otherwise multiple equally-valid candidates exist and
            #       the matcher's choice is arbitrary.
            #   (3) the row's old (line_hash, prev_lh, next_lh) signature
            #       must also be UNIQUE in the old file — if the user had
            #       siblings of this line back at mark time, we don't know
            #       which of them the snapshot row referred to and can't
            #       safely pick a survivor.
            #   (4) the matched block must extend at least K lines on each
            #       side of the marked position. A short matched run is
            #       the shape of a coincidental insert anchor — a long run
            #       of intact context centered on the mark is what real
            #       preservation looks like.
            # In any failure case, drop the row. False-unmark is acceptable;
            # false-positive on unreviewed code is not.
            if new_ch != row["context_hash"]:
                delete_ids.append(row_id)
                continue
            if ctx_counts.get((new_lh, new_ch), 0) > 1:
                delete_ids.append(row_id)
                continue
            if old_hash_counts is not None and old_idx < len(old_line_hashes):
                prev_old_h = old_line_hashes[old_idx - 1] if old_idx > 0 else ""
                next_old_h = (
                    old_line_hashes[old_idx + 1]
                    if old_idx < len(old_line_hashes) - 1
                    else ""
                )
                old_key = (old_line_hashes[old_idx], prev_old_h, next_old_h)
                if old_hash_counts.get(old_key, 0) > 1:
                    delete_ids.append(row_id)
                    continue
            m_before, m_after = block_margins.get(old_idx, (0, 0))
            if m_before < _BLOCK_MARGIN_K or m_after < _BLOCK_MARGIN_K:
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

    await conn.execute("BEGIN")
    try:
        await _reconcile_reviewed(
            conn, rows, new_lines, new_line_hashes, line_map, block_margins, old_line_hashes
        )
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
