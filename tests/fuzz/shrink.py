"""Delta-debugger and seed-corpus writer for fuzz failures.

Greedy single-element removal until a fixed point. Bounded by `max_trials`
so a pathological case can't blow up the whole test run.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from tests.fuzz.generators import op_to_dict
from tests.fuzz.harness import Outcome, run_with_inputs


SAVED_DIR = Path(__file__).parent / "saved_seeds"


async def shrink(outcome: Outcome, *, max_trials: int = 200, time_budget_s: float = 10.0) -> Outcome:
    cur = outcome
    deadline = time.perf_counter() + time_budget_s
    trials = 0

    def budget_left() -> bool:
        return trials < max_trials and time.perf_counter() < deadline

    # Phase 1: shrink ops
    while budget_left():
        progress = False
        for i in range(len(cur.ops)):
            if not budget_left():
                break
            trial_ops = cur.ops[:i] + cur.ops[i + 1:]
            if not trial_ops:
                continue
            trials += 1
            trial = await run_with_inputs(
                cur.seed, cur.initial_lines, cur.initial_ids, cur.marked_ids, trial_ops
            )
            if trial.has_fp:
                cur = trial
                progress = True
                break
        if not progress:
            break

    # Phase 2: shrink marked_ids
    while budget_left():
        progress = False
        for mid in sorted(cur.marked_ids):
            if not budget_left():
                break
            trial_marked = cur.marked_ids - {mid}
            if not trial_marked:
                continue
            trials += 1
            trial = await run_with_inputs(
                cur.seed, cur.initial_lines, cur.initial_ids, trial_marked, cur.ops
            )
            if trial.has_fp:
                cur = trial
                progress = True
                break
        if not progress:
            break

    return cur


def save_outcome(outcome: Outcome, *, prefix: str = "fp") -> Path:
    """Write JSON to saved_seeds/. Filename = `{prefix}_{sha8}.json` for dedup."""
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "seed": outcome.seed,
        "initial_lines": outcome.initial_lines,
        "initial_ids": outcome.initial_ids,
        "marked_ids": sorted(outcome.marked_ids),
        "ops": [op_to_dict(o) for o in outcome.ops],
        "new_lines": outcome.new_lines,
        "new_ids": outcome.new_ids,
        "fp_rows": [{"line_no": ln, "id_at_row": rid} for ln, rid in outcome.fp_rows],
        "fn_ids": sorted(outcome.fn_ids),
        "tp_ids": sorted(outcome.tp_ids),
        "tn_ids": sorted(outcome.tn_ids),
    }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    sha8 = hashlib.sha256(canonical.encode()).hexdigest()[:8]
    path = SAVED_DIR / f"{prefix}_{sha8}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return path
