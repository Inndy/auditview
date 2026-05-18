"""Reconciler fuzz: runs N randomized edit scenarios, asserts no false-positive
review marks survive reconciliation, reports drops.

See feedback memory `feedback_reviewed_state_safety.md`: false positives
(reviewed badge on code the user never marked) are unacceptable; false
unmarks (dropped marks) are acceptable.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor

import pytest

from tests.fuzz.harness import Outcome, run_one_sync
from tests.fuzz.shrink import save_outcome, shrink


FN_SAVE_CAP = 32


def _fuzz_worker(args: tuple) -> Outcome:
    seed, use_repetitive = args
    return run_one_sync(seed, use_repetitive=use_repetitive)


@pytest.mark.asyncio
async def test_fuzz_no_false_positives(pytestconfig):
    base_seed = pytestconfig.getoption("--fuzz-seed")
    iters = pytestconfig.getoption("--fuzz-iters")
    save_fn = pytestconfig.getoption("--fuzz-save-fn")
    jobs = pytestconfig.getoption("--fuzz-jobs")

    loop = asyncio.get_running_loop()
    task_args = [(base_seed + i, i % 2 == 0) for i in range(iters)]

    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = [loop.run_in_executor(pool, _fuzz_worker, args) for args in task_args]
        all_outcomes: list[Outcome] = await asyncio.gather(*futures)

    tp_total = fp_total = fn_total = tn_total = 0
    fp_outcomes: list = []
    fn_samples: list = []
    fn_seen = 0

    for outcome in all_outcomes:
        tp_total += len(outcome.tp_ids)
        fp_total += len(outcome.fp_rows)
        fn_total += len(outcome.fn_ids)
        tn_total += len(outcome.tn_ids)

        if outcome.has_fp:
            fp_outcomes.append(outcome)

        if outcome.fn_ids:
            fn_seen += 1
            if save_fn and len(fn_samples) < FN_SAVE_CAP:
                fn_samples.append(outcome)

    shrunk_list: list = await asyncio.gather(*[shrink(o) for o in fp_outcomes])

    saved_fp_paths: list = []
    for shrunk in shrunk_list:
        path = save_outcome(shrunk, prefix="fp")
        saved_fp_paths.append(path)

    saved_fn_paths: list = []
    if save_fn:
        for outcome in fn_samples:
            path = save_outcome(outcome, prefix="fn")
            saved_fn_paths.append(path)

    print()
    print(f"fuzz summary over {iters} iters (base seed {base_seed}, {jobs} workers):")
    print(f"  TP (mark correctly migrated): {tp_total}")
    print(f"  FP (mark landed on unreviewed code): {fp_total}   <-- must be 0")
    print(f"  FN (mark dropped though line survived): {fn_total} across {fn_seen} iters")
    print(f"  TN (line deleted; mark correctly gone): {tn_total}")
    if saved_fp_paths:
        print(f"  FP minimal repros saved ({len(saved_fp_paths)}):")
        for p in saved_fp_paths[:5]:
            print(f"    {p}")
        if len(saved_fp_paths) > 5:
            print(f"    ... and {len(saved_fp_paths) - 5} more")
    if saved_fn_paths:
        print(f"  FN samples saved ({len(saved_fn_paths)}; cap {FN_SAVE_CAP}):")
        for p in saved_fn_paths[:5]:
            print(f"    {p}")

    if fp_outcomes:
        seeds = sorted({o.seed for o in fp_outcomes})
        preview = ", ".join(str(s) for s in seeds[:10])
        more = "" if len(seeds) <= 10 else f" (+{len(seeds) - 10} more)"
        pytest.fail(
            f"{len(fp_outcomes)}/{iters} iters produced false-positive review marks. "
            f"Seeds: {preview}{more}. Minimal repros in tests/fuzz/saved_seeds/."
        )
