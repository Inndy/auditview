# Reconciler Fuzz Runner

The fuzzer stress-tests `reconcile_file` by generating synthetic files,
randomly marking lines, applying edit patches, and asserting that no
surviving review mark lands on code the user never marked (false positive).
False unmarks (dropped marks) are acceptable; false positives cause the
test to fail and trigger shrinking.

## Fundamental limitation

The reconciler uses `difflib.SequenceMatcher` to map old line positions to new ones. For any two versions of a file there may be **multiple equally-valid diffs** — different alignments that all produce the same final text. When content is duplicated, the differ must pick one arbitrarily, and its choice may not match the user's intent about which copy "is" the originally-reviewed line.

This means false positives (a mark migrating to an unreviewed line) are not just implementation bugs — some are rooted in fundamental ambiguity that no line-based diff algorithm can resolve. The reconciler's margin-K guard and context hashing mitigate this, but cannot eliminate it entirely.

When the fuzzer finds a false positive, the correct response is always to make the reconciler **more conservative** — tighten the guard so it drops the ambiguous case rather than migrating it. Trying to correctly resolve the ambiguity is a dead end; there is no information to resolve it with.

The fuzzer is therefore a **permanent quality floor**, not a one-time validation step. It continuously confirms that the reconciler's guards are conservative enough, and catches regressions when the reconciler changes.

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
