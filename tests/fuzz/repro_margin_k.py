"""Minimal reproducer for the _BLOCK_MARGIN_K=5 false-positive.

The trigger:
  Inserting exactly K+1 lines at position K (where K = _BLOCK_MARGIN_K)
  that are a verbatim copy of old[K:2K+1] creates a matching block
  old[0:2K+1] → new[0:2K+1] of size 2K+1=11.  The marked old_idx=K
  falls at i=K inside that block:

      m_before = K = 5   (check: 5 < 5 = False  →  passes guard 4)
      m_after  = K = 5   (check: 5 < 5 = False  →  passes guard 4)

  The inserted copy at new[K] has the exact same prev/next as the
  original mark, so context_hash matches (guard 1 passes).
  The original M shifts to new[2K+1], where its new predecessor is
  old[2K] (not the original prev P), so the stored (lh, ch) pair is
  unique in the new file (guard 2 passes).
  The old signature is also unique because P…M…N does not repeat in
  the original file (guard 3 passes).

  → Mark migrates to the inserted (unreviewed) copy.

Layout
------
  index:   0    1  …  K-2   K-1  K   K+1  K+2  …  2K
  initial: u0  u1  …  u3     P   M    N   u4   …  u9
                              ↑
                           mark here

  insert K+1 lines at pos K: copy of old[K:2K+1] = [M, N, u4, … u8]

  new[0:2K+1] = [u0,…,u3, P, M, N, u4,…,u8]  ==  old[0:2K+1]
                                ↑
                    inserted M lands here with context (P, M, N)
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.fuzz.generators import Insert
from tests.fuzz.harness import run_with_inputs

K = 5   # must equal auditview.core.reconciler._BLOCK_MARGIN_K

P = "CTX_PREV"
M = "MARKED_LINE"
N = "CTX_NEXT"

# 2K unique filler lines so no accidental context collisions
UNIQ = [f"unique_{i}" for i in range(2 * K)]

# Initial file: K-1 fillers | P | M | N | K+1 fillers  (total 2K+2 lines)
initial = UNIQ[:K-1] + [P, M, N] + UNIQ[K-1:2*K]
# positions:    0..K-2,  K-1, K, K+1,  K+2..2K+1
assert len(initial) == 2 * K + 3, len(initial)

initial_ids = list(range(len(initial)))
marked_ids  = {K}   # M at position K

# Insert K+1 lines at position K: verbatim copy of old[K:2K+1]
# = [M, N, UNIQ[K-1], UNIQ[K], …, UNIQ[2K-2]]
insert_lines = tuple(initial[K : K + (K + 1)])
assert len(insert_lines) == K + 1
ops = [Insert(pos=K, lines=insert_lines)]

# After insert, the new file looks like:
#   new[0:K]    = old[0:K]                 (unchanged prefix)
#   new[K:2K+1] = inserted copy            (K+1 fresh lines)
#   new[2K+1:]  = old[K:]                  (shifted original)
#
# old[0:2K+1] == new[0:2K+1]  →  SequenceMatcher block (a=0,b=0,size=2K+1=11)
# old_idx=K at i=K in that block:  m_before=K=5, m_after=K=5.


async def main():
    outcome = await run_with_inputs(
        seed=0,
        initial_lines=initial,
        initial_ids=initial_ids,
        marked_ids=marked_ids,
        ops=ops,
    )
    print("initial file:")
    for i, l in enumerate(initial):
        mark = " ← MARKED" if i == K else ""
        print(f"  [{i:2d}] {l}{mark}")

    print(f"\ninsert {len(insert_lines)} lines at pos {K}:")
    print(f"  {list(insert_lines)}")

    print(f"\nnew file ({len(outcome.new_lines)} lines):")
    for i, (l, nid) in enumerate(zip(outcome.new_lines, outcome.new_ids)):
        flag = " ← inserted copy" if nid not in initial_ids else (
               " ← ORIGINAL MARK (shifted)" if nid == K else "")
        print(f"  [{i:2d}] {l}  (id={nid}){flag}")

    print()
    print("FP rows:", outcome.fp_rows)
    print("FN ids: ", outcome.fn_ids)

    if outcome.has_fp:
        ln, bad_id = outcome.fp_rows[0]
        print(f"\n✗ FALSE POSITIVE confirmed at line_no={ln}, id={bad_id}")
        print(f"  That line was inserted — it was never reviewed.")
        print(f"  Original mark (id={K}) is now at line_no="
              f"{outcome.new_ids.index(K)+1} but lost its mark.")
        print(f"\nMechanism: insert copies old[{K}:{2*K+1}] at pos {K},")
        print(f"  creating block old[0:{2*K+1}]→new[0:{2*K+1}] (size {2*K+1}).")
        print(f"  old_idx={K} sits at i={K}: m_before={K}, m_after={K}.")
        print(f"  Guard 4 checks m < {K}, so {K} < {K} = False → passes.")
    else:
        print("\n✓ No false positive (K or guard may have been changed).")


if __name__ == "__main__":
    asyncio.run(main())
