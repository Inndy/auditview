---
description: Review the line-identity contract — content-based hashing, reconciliation, and the wire format that backend, MCP, web UI, and nvim plugin all rely on. Use when reviewing reconciler/hashing changes, or any change to mark/note payload shape.
allowed-tools: Read, Glob, Grep
---

# Lens: line-identity contract

**Why this matters for this codebase:** Reviewed state and note anchoring are *never* tied to line numbers — every persisted row is keyed by `line_hash` (SHA-256 of the line) + `context_hash` (SHA-256 of prev+curr+next). The reconciler migrates rows across edits using `difflib.SequenceMatcher` with a context-hash fallback. If the hashing schema, the reconciler's mapping rules, or the wire payload drifts between backend / MCP / nvim, reviewed marks and notes are silently lost, duplicated, or misattributed — and the data model gives the user no way to detect it.

## Start at

- `auditview/core/hashing.py` — canonical hash definitions (`line_hash`, `context_hash`).
- `auditview/core/reconciler.py`:
  - `build_line_map()` — SequenceMatcher-driven old→new line mapping.
  - `_reconcile_reviewed()` (~line 63) — applies the map to `reviewed_lines`.
  - `_reconcile_notes()` — applies the map to notes; sets `is_orphaned`.
  - `ensure_snapshot()` (~line 144) — owns the dual-mode invariant (line-map vs context-hash fallback).
  - `reconcile_file()` (~line 178) — top-level entry, wraps everything in BEGIN/COMMIT.
- `auditview/api/lines.py` — POST `/mark` payload shape (what hashes the client sends).
- `auditview/api/notes.py` — note create/update; how anchor lines are bound.
- `auditview/api/mcp.py` — MCP `create_note` path; does it re-hash server-side or trust client hashes?
- `nvim/lua/auditview/buffer.lua` — client-side `lines[line_no] = {line_hash, context_hash, …}` cache.
- `nvim/lua/auditview/marks.lua` — `/lines/mark` POST body construction (which hashes get sent, from where).

## Follow

Trace a single line through its full lifecycle:

1. **Ingest** — scanner reads file → hashing.py computes `line_hash` + `context_hash` (note neighbor selection) → DB row.
2. **Edit** — file modified → watcher → `reconcile_file()` → `build_line_map()` → row migration or deletion. Watch what happens at **file boundaries** (first/last line context), at **duplicate identical lines** with identical neighbors, and when `prev_line_hashes` is absent (first reconcile).
3. **Client → server** — nvim builds POST body from its cache, *not* from re-hashing the buffer; UI does similarly. Server validates the hash matches its current DB. Watch for any path where the client computes its own hash and the algorithm could diverge from `hashing.py`.
4. **Notes** — multi-line range. Compare how the start anchor and the end anchor are handled in `_reconcile_notes()` and `is_orphaned` logic — is the rule symmetric?

## Look for

- **Boundary cases in `context_hash`**: what `prev` is used for line 0? what `next` for the last line? An empty-string sentinel vs `None` mismatch silently changes the hash on the very lines users most often mark.
- **Tie-breaker collapse**: two identical lines with identical neighbors yield identical `(line_hash, context_hash)` keys. In `_reconcile_reviewed`, key collisions can drop one side silently — confirm the loser is logged or merged, not just overwritten.
- **Dual-mode reconciliation invariant**: `_reconcile_*` switches between line-map mode and context-hash fallback based on whether `prev_line_hashes` was previously stored. The condition lives in `ensure_snapshot()` docstring (line ~145), not in code. Trace every call site to confirm the snapshot is written *before* the next reconcile depends on it. A skipped/failed `ensure_snapshot` traps a session permanently in fallback mode.
- **Client-supplied vs server-recomputed hashes**: `/mark` accepts hashes from the client and trusts them as keys. If the client cache is stale (file changed on disk under the editor, see [[codeview-lens-nvim-cache-drift]]), the client may insert rows that don't match the file's current content — the row will look valid until the next reconcile, then evaporate.
- **MCP `create_note` schema parity**: confirm MCP and HTTP create_note take the same fields and either both server-hash or both client-hash. A mismatch here means MCP-created notes orphan on the next edit but HTTP-created ones don't (or vice-versa).
- **Schema migration vs reconciliation**: if the hash algorithm ever changes, every existing row's keys become unverifiable. Check `auditview/db/schema.py` for any algorithm version column — its absence is itself the finding.
- **Note range invariants**: a note with `start_line > end_line` after reconciliation, or with one anchor migrated and the other orphaned, can leave inconsistent state. Look for the asymmetry.
- **The reader-context smell**: someone reviewing `_reconcile_reviewed` cannot tell whether the dual-mode logic is sound without simultaneously holding `ensure_snapshot`, `build_line_map`, and the schema in mind. Flag this as a design issue, not just a documentation issue.

## Universal review principles

Apply these across every lens, in addition to the lens-specific items above:

- A defensive guard (`if err`, boundary check, type-assertion guard) is a question, not an answer: *is this patching a symptom, or is the data model wrong?*
- Find the **root shape of a bug class**, not individual instances.
- Code that forces the reader to hold context across distant locations is a design smell, not just a readability issue.
- Absence of a structure is a finding: concurrency without a documented ownership model, an API without a documented error shape, a cache without a documented invalidation rule.
- If a name needs a comment to clarify its meaning, the name is wrong. Identifiers that leak implementation detail, lie about scope, or force a reader to look elsewhere are bugs.
- Distinguish *validating* illegal state from *preventing* it. A guard against an "impossible" state is a sign the type or data model should make the state unrepresentable.
- A function that can't be described without "and" is doing more than one thing — composition candidate, not refactor target.
- Question every abstraction that adds indirection without reducing complexity. More code is more surface, not more safety; flag wrappers harder to reason about than what they wrap.

## What is *not* in scope for this lens

Concurrency around reconciliation (lock scope, asyncio races) → [[codeview-lens-concurrency]].
What happens when the nvim client cache disagrees with the file on disk → [[codeview-lens-nvim-cache-drift]].
