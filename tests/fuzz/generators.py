"""Synthetic file + patch generators for the reconciler fuzzer.

All functions are deterministic given a `random.Random` instance. Ops carry
concrete content, so `apply_ops_pure` is RNG-free and idempotent — the shrinker
relies on this to re-run subsets without re-rolling.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Insert:
    pos: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Delete:
    pos: int
    n: int


Op = Insert | Delete


_LINE_CHARS = string.ascii_letters + string.digits + "  ()[]{}.,;=+-*/<>!"


def random_line(rng: random.Random) -> str:
    length = rng.randint(0, 40)
    return "".join(rng.choice(_LINE_CHARS) for _ in range(length))


def make_repetitive_seed_file(rng: random.Random) -> tuple[list[str], list[int]]:
    """Generate files with high content-duplication to stress context-hash disambiguation.

    Five strategies, chosen randomly:
      0 - sequence repeat:  [a, b, c] * N
      1 - triangle:         line_i appears i+1 times consecutively
      2 - nested-loop:      for i in range(n): for j in range(i+1): append(seq[j])
      3 - interleaved:      sequence repeat with random filler lines between blocks
      4 - scatter:          one anchor line scattered throughout unique content
    """
    strategy = rng.randint(0, 4)

    if strategy == 0:
        seq_len = rng.randint(2, 6)
        seq = [random_line(rng) for _ in range(seq_len)]
        repeats = rng.randint(3, 10)
        lines = seq * repeats

    elif strategy == 1:
        n_unique = rng.randint(4, 10)
        lines = []
        for i in range(n_unique):
            content = random_line(rng)
            lines.extend([content] * (i + 1))

    elif strategy == 2:
        n_unique = rng.randint(4, 8)
        seq = [random_line(rng) for _ in range(n_unique)]
        lines = []
        for i in range(n_unique):
            for j in range(i + 1):
                lines.append(seq[j])

    elif strategy == 3:
        seq_len = rng.randint(2, 5)
        seq = [random_line(rng) for _ in range(seq_len)]
        repeats = rng.randint(3, 8)
        filler_pool = [random_line(rng) for _ in range(rng.randint(2, 6))]
        lines = []
        for _ in range(repeats):
            lines.extend(seq)
            for _ in range(rng.randint(0, 3)):
                lines.append(rng.choice(filler_pool))

    else:
        anchor = random_line(rng)
        n_total = rng.randint(20, 60)
        filler_pool = [random_line(rng) for _ in range(rng.randint(5, 15))]
        anchor_prob = rng.uniform(0.2, 0.5)
        lines = [
            anchor if rng.random() < anchor_prob else rng.choice(filler_pool)
            for _ in range(n_total)
        ]

    ids = list(range(len(lines)))
    return lines, ids


def make_seed_file(rng: random.Random) -> tuple[list[str], list[int]]:
    n = rng.randint(20, 200)
    pool_size = rng.randint(5, max(5, n // 3))
    pool = [random_line(rng) for _ in range(pool_size)]
    lines = [rng.choice(pool) for _ in range(n)]
    if rng.random() < 0.5 and n > 10:
        sec_len = rng.randint(2, min(5, n // 4))
        sec_start = rng.randint(0, n - sec_len)
        section = lines[sec_start:sec_start + sec_len]
        insert_at = rng.randint(0, n - sec_len)
        lines = (lines[:insert_at] + section + lines[insert_at:])[:n]
    ids = list(range(n))
    return lines, ids


def pick_marked_ids(rng: random.Random, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    frac = rng.uniform(0.1, 0.3)
    k = max(1, int(len(ids) * frac))
    return set(rng.sample(ids, k))


def _make_insert_content(rng: random.Random, cur_lines: list[str], n: int) -> list[str]:
    if cur_lines and n <= len(cur_lines) and rng.random() < 0.4:
        start = rng.randint(0, len(cur_lines) - n)
        return list(cur_lines[start:start + n])
    if cur_lines and rng.random() < 0.3:
        src = rng.choice(cur_lines)
        return [src] * n
    return [random_line(rng) for _ in range(n)]


def generate_patch_ops(rng: random.Random, initial_lines: list[str]) -> list[Op]:
    """Generate 1..8 ops with concrete content. Positions are valid relative to
    the file state after all prior ops have been applied."""
    n_ops = rng.randint(1, 8)
    cur_lines = list(initial_lines)
    ops: list[Op] = []
    for _ in range(n_ops):
        if cur_lines and rng.random() < 0.5:
            n_del = rng.randint(1, min(10, len(cur_lines)))
            pos = rng.randint(0, len(cur_lines) - n_del)
            ops.append(Delete(pos=pos, n=n_del))
            del cur_lines[pos:pos + n_del]
        else:
            pos = rng.randint(0, len(cur_lines))
            n_ins = rng.randint(1, 10)
            content = _make_insert_content(rng, cur_lines, n_ins)
            ops.append(Insert(pos=pos, lines=tuple(content)))
            cur_lines[pos:pos] = content
    return ops


def apply_ops_pure(
    lines: list[str],
    ids: list[int],
    ops: Iterable[Op],
    next_id_start: int | None = None,
) -> tuple[list[str], list[int]]:
    """Apply ops to (lines, ids); fresh IDs assigned to every inserted line.

    Note "section"/"repeat" inserts produce lines with the same *content* as
    existing ones but always with *fresh* IDs — that's the false-positive
    trigger pattern the harness probes.
    """
    new_lines = list(lines)
    new_ids = list(ids)
    next_id = next_id_start if next_id_start is not None else ((max(ids) + 1) if ids else 0)
    for op in ops:
        if isinstance(op, Insert):
            inserted_ids = list(range(next_id, next_id + len(op.lines)))
            next_id += len(op.lines)
            new_lines[op.pos:op.pos] = op.lines
            new_ids[op.pos:op.pos] = inserted_ids
        else:
            del new_lines[op.pos:op.pos + op.n]
            del new_ids[op.pos:op.pos + op.n]
    return new_lines, new_ids


def op_to_dict(op: Op) -> dict:
    if isinstance(op, Insert):
        return {"kind": "insert", "pos": op.pos, "lines": list(op.lines)}
    return {"kind": "delete", "pos": op.pos, "n": op.n}


def op_from_dict(d: dict) -> Op:
    if d["kind"] == "insert":
        return Insert(pos=d["pos"], lines=tuple(d["lines"]))
    return Delete(pos=d["pos"], n=d["n"])
