"""Single-iteration fuzz harness: drive `reconcile_file` end-to-end against
an in-temp-file aiosqlite DB and classify the outcome against ID-tracked
ground truth.

`run_one(seed)` is fully deterministic from the seed. `run_with_inputs(...)`
takes already-generated inputs (used by the shrinker, which re-runs subsets
of ops without re-rolling).
"""
from __future__ import annotations

import asyncio
import os
import random
import tempfile
from dataclasses import dataclass, field

from auditview.core.hashing import context_hash, line_hash
from auditview.core.reconciler import reconcile_file
from auditview.db.connection import open_db
from auditview.db.schema import run_migrations

from tests.fuzz.generators import (
    Op,
    apply_ops_pure,
    generate_patch_ops,
    make_repetitive_seed_file,
    make_seed_file,
    pick_marked_ids,
)

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


@dataclass
class Outcome:
    seed: int
    initial_lines: list[str]
    initial_ids: list[int]
    marked_ids: set[int]
    ops: list[Op]
    new_lines: list[str]
    new_ids: list[int]
    surviving_rows: list[tuple[int, str, str]]  # (line_no, line_hash, context_hash)
    tp_ids: set[int] = field(default_factory=set)
    fp_rows: list[tuple[int, int]] = field(default_factory=list)  # (line_no, id_at_that_line)
    fn_ids: set[int] = field(default_factory=set)
    tn_ids: set[int] = field(default_factory=set)

    @property
    def has_fp(self) -> bool:
        return bool(self.fp_rows)


async def run_one(seed: int, file_gen=None) -> Outcome:
    if file_gen is None:
        file_gen = make_seed_file
    rng = random.Random(seed)
    initial_lines, initial_ids = file_gen(rng)
    marked_ids = pick_marked_ids(rng, initial_ids)
    ops = generate_patch_ops(rng, initial_lines)
    return await run_with_inputs(seed, initial_lines, initial_ids, marked_ids, ops)


def run_one_sync(seed: int, use_repetitive: bool = False) -> Outcome:
    gen = make_repetitive_seed_file if use_repetitive else make_seed_file
    return asyncio.run(run_one(seed, file_gen=gen))


async def run_with_inputs(
    seed: int,
    initial_lines: list[str],
    initial_ids: list[int],
    marked_ids: set[int],
    ops: list[Op],
) -> Outcome:
    new_lines, new_ids = apply_ops_pure(initial_lines, initial_ids, ops)

    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmp:
        db_path = os.path.join(tmp, "fuzz.db")
        rel_path = "f.txt"
        full_path = os.path.join(tmp, rel_path)

        with open(full_path, "w") as fh:
            fh.write("\n".join(initial_lines))
        mtime0 = os.path.getmtime(full_path)

        async with open_db(db_path) as conn:
            await run_migrations(conn)
            cur = await conn.execute(
                "INSERT INTO sessions (label, root_path) VALUES (?, ?)",
                ("fuzz", tmp),
            )
            sid = cur.lastrowid

            initial_phashes = "\n".join(line_hash(l) for l in initial_lines)
            await conn.execute(
                "INSERT INTO files (session_id, rel_path, last_mtime, prev_line_hashes, countable_lines) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, rel_path, mtime0, initial_phashes, len(initial_lines)),
            )

            for i, id_ in enumerate(initial_ids):
                if id_ in marked_ids:
                    content = initial_lines[i]
                    prev_c = initial_lines[i - 1] if i > 0 else ""
                    next_c = initial_lines[i + 1] if i < len(initial_lines) - 1 else ""
                    await conn.execute(
                        "INSERT INTO reviewed_lines "
                        "(session_id, file_path, line_hash, context_hash, line_no) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (sid, rel_path, line_hash(content), context_hash(prev_c, content, next_c), i + 1),
                    )

            with open(full_path, "w") as fh:
                fh.write("\n".join(new_lines))

            await reconcile_file(conn, sid, rel_path, tmp)

            cur = await conn.execute(
                "SELECT line_no, line_hash, context_hash FROM reviewed_lines "
                "WHERE session_id = ? AND file_path = ? ORDER BY line_no",
                (sid, rel_path),
            )
            rows = [(r["line_no"], r["line_hash"], r["context_hash"]) for r in await cur.fetchall()]

    return _classify(seed, initial_lines, initial_ids, marked_ids, ops, new_lines, new_ids, rows)


def _classify(
    seed: int,
    initial_lines: list[str],
    initial_ids: list[int],
    marked_ids: set[int],
    ops: list[Op],
    new_lines: list[str],
    new_ids: list[int],
    rows: list[tuple[int, str, str]],
) -> Outcome:
    id_to_new_pos: dict[int, int] = {id_: i + 1 for i, id_ in enumerate(new_ids)}
    rows_by_ln: dict[int, tuple[int, str, str]] = {r[0]: r for r in rows}

    tp_ids: set[int] = set()
    fp_rows: list[tuple[int, int]] = []
    for ln, lh, ch in rows:
        if not (1 <= ln <= len(new_lines)):
            fp_rows.append((ln, -1))
            continue
        id_at_row = new_ids[ln - 1]
        if id_at_row in marked_ids:
            tp_ids.add(id_at_row)
        else:
            fp_rows.append((ln, id_at_row))

    fn_ids: set[int] = set()
    tn_ids: set[int] = set()
    for mid in marked_ids:
        new_pos = id_to_new_pos.get(mid)
        if new_pos is None:
            tn_ids.add(mid)
            continue
        row = rows_by_ln.get(new_pos)
        if row is None:
            fn_ids.add(mid)
            continue
        if new_ids[new_pos - 1] != mid:
            fn_ids.add(mid)

    return Outcome(
        seed=seed,
        initial_lines=list(initial_lines),
        initial_ids=list(initial_ids),
        marked_ids=set(marked_ids),
        ops=list(ops),
        new_lines=list(new_lines),
        new_ids=list(new_ids),
        surviving_rows=rows,
        tp_ids=tp_ids,
        fp_rows=fp_rows,
        fn_ids=fn_ids,
        tn_ids=tn_ids,
    )
