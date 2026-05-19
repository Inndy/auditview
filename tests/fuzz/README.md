# Reconciler Fuzz Runner

The fuzzer stress-tests `reconcile_file` by generating synthetic files,
randomly marking lines, applying edit patches, and asserting that no
surviving review mark lands on code the user never marked (false positive).
False unmarks (dropped marks) are acceptable; false positives cause the
test to fail and trigger shrinking.

## Fundamental limitation and FP semantics

The reconciler uses `difflib.SequenceMatcher` to map old line positions to new ones. For any two versions of a file there may be **multiple equally-valid diffs** — different alignments that all produce the same final text. When content is duplicated, the differ must pick one arbitrarily.

The fuzzer uses ID tracking to classify outcomes: a mark landing on a line whose ID was never explicitly marked counts as a "FP." But the reconciler is **content-based**: if a line has identical content and identical 3-line context (prev+curr+next), it is indistinguishable from the originally-reviewed line under any diff-based scheme. Migrating the mark there is semantically correct.

True FPs — marks migrating onto code with *different* content or context than what was reviewed — are bugs. Content-identical migration under K=1 is expected and acceptable, especially during active review sessions where the user can verify marks.

The block-margin guard (`_BLOCK_MARGIN_K`) controls the FP/FN tradeoff: larger K drops more marks (fewer FP risk, more FN pain); smaller K preserves more marks. K=1 matches the 1-line radius already verified by `context_hash` and is the current setting.

## Quick start

```bash
uv run pytest tests/test_reconciler_fuzz.py -s
```

Runs 100 iterations across all CPU cores. `/dev/shm` is used for temp
SQLite DBs on Linux so no disk I/O occurs.

## CLI options

| Option | Default | Description |
|---|---|---|
| `--fuzz-iters N` | 100 | Number of scenarios to run |
| `--fuzz-seed N` | 0 | Base seed; iteration `i` uses seed `base + i` |
| `--fuzz-jobs N` | cpu_count | Worker processes |
| `--fuzz-save-fn` | off | Also save false-unmark samples to `saved_seeds/` |

## Recommended commands

```bash
# Default smoke run — fast, covers both generator types
uv run pytest tests/test_reconciler_fuzz.py -s

# Deep run for pre-merge confidence
uv run pytest tests/test_reconciler_fuzz.py -s --fuzz-iters=2000

# Explore a fresh seed range (avoids re-running known-clean seeds)
uv run pytest tests/test_reconciler_fuzz.py -s --fuzz-seed=10000 --fuzz-iters=1000

# Focus CPU — useful when other workloads are running
uv run pytest tests/test_reconciler_fuzz.py -s --fuzz-jobs=4 --fuzz-iters=500

# Collect false-unmark samples for later triage
uv run pytest tests/test_reconciler_fuzz.py -s --fuzz-iters=500 --fuzz-save-fn

# Reproduce a saved failure seed exactly
uv run pytest tests/test_reconciler_fuzz.py -s --fuzz-seed=<N> --fuzz-iters=1
```

## Input generators

Each iteration uses one of two generators:

- **Random** (odd seeds) — pool-based file with random duplicate lines and
  arbitrary insert/delete patches. General coverage.
- **Repetitive** (even seeds) — structured high-duplication patterns that
  stress context-hash disambiguation. Five strategies chosen randomly per seed:

  | Strategy | Pattern |
  |---|---|
  | sequence-repeat | `[a, b, c] * N` |
  | triangle | line *i* repeated *i+1* times consecutively |
  | nested-loop | `for i in range(n): for j in range(i+1): append(seq[j])` |
  | interleaved | sequence blocks with random filler lines between |
  | scatter | one anchor line scattered throughout unique content |

## Failure artifacts

When a false positive is found:
1. The case is delta-debugged (ops and marked IDs shrunk to a minimal repro).
2. The minimal repro is written to `tests/fuzz/saved_seeds/fp_<sha8>.json`.
3. The test fails and prints the seed(s).

Files under `saved_seeds/` committed to the repo are regression fixtures —
they represent cases where the reconciler was not conservative enough, and
must continue to pass (i.e. no FP) after any reconciler change.

## Future work

### Calibrate false-negative rate

The fuzzer currently only enforces the safety invariant (no FPs). But tightening the reconciler's guards to eliminate FPs also increases false negatives — dropped marks that force the reviewer to re-examine lines they already covered. Too many drops make the tool impractical.

The right threshold is not "zero FPs at any cost" but a balance: minimize FPs while keeping the FN rate low enough that review workload stays manageable. That balance point is currently unknown.

One concrete way to measure it: take a real git repository, mark all lines as reviewed at an early commit, then walk each subsequent commit one by one through the reconciler and count how many marks survive. A well-calibrated reconciler should preserve the vast majority of marks across typical commits (refactors, renames, small edits) and only drop marks where genuine ambiguity exists. This gives a realistic FN rate grounded in actual developer behavior rather than synthetic generators.

A secondary metric worth tracking: what fraction of dropped marks were in regions that actually changed (acceptable drops) vs. regions that were untouched (unnecessary drops from overly conservative guards).

To replay a saved seed manually:

```python
import asyncio, json
from tests.fuzz.harness import run_with_inputs
from tests.fuzz.generators import op_from_dict

data = json.load(open("tests/fuzz/saved_seeds/fp_abcd1234.json"))
ops = [op_from_dict(o) for o in data["ops"]]

async def main():
    outcome = await run_with_inputs(
        data["seed"], data["initial_lines"], data["initial_ids"],
        set(data["marked_ids"]), ops,
    )
    print("FP rows:", outcome.fp_rows)

asyncio.run(main())
```
