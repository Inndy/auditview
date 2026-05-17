---
description: Review the nvim client's local cache vs server state — no SSE, manual/autocmd-only invalidation, visual-mark timing, modified-buffer guard. Use when touching nvim/lua/auditview/buffer.lua, marks.lua, session.lua, or any autocmd in plugin/auditview.lua.
allowed-tools: Read, Glob, Grep
---

# Lens: nvim cache drift & client/server consistency

**Why this matters for this codebase:** The nvim plugin keeps a per-buffer cache of `{line_hash, context_hash, is_reviewed}` plus the notes array, fetched at `BufReadPost`/`BufWritePost` and cleared at `BufUnload`. It does **not** subscribe to SSE. Any external change — web UI marks, another editor saves, a teammate's MCP note — is invisible until the user runs `:AuditviewRefresh`. On top of that, visual-mode mark operations exit visual, then read `'<`/`'>` positions — values that *can* be stale if the user moves between exit and read. The contract "what the client believes about a line" diverges from "what the server believes" much more easily than a user would expect.

## Start at

- `nvim/lua/auditview/buffer.lua`:
  - `cache[bufnr] = {rel_path, lines, notes, fetched_at}` (line ~10) — global table, no TTL, no staleness check.
  - `fetch()`, `refresh()`, `invalidate()`.
  - Extmark placement: `ns_reviewed`, `ns_notes_sign`, `ns_notes_vt`.
- `nvim/lua/auditview/marks.lua`:
  - Visual-range capture (`getpos("'<")`, `getpos("'>")`) — *after* `vim.cmd('normal! \27')`.
  - Modified-buffer guard.
  - Rejection handling on POST `/lines/mark`.
- `nvim/lua/auditview/session.lua`:
  - `state.session`, `state.files_listed`, `state.project_root`, `state.project_root_searched` — global, callback-mutated.
- `nvim/plugin/auditview.lua`:
  - Autocmds: `BufReadPost`, `BufWritePost`, `BufUnload`, `CursorMoved`, `CursorHold`.
- `nvim/lua/auditview/http.lua` — synchronous `vim.system(...):wait()`, no retry, blocking.

## Follow

Three traces:

1. **Visual mark of N lines**: user enters Visual-Line, selects lines 10–15, types `<leader>am`. Command exits visual, reads `'<`/`'>`, builds POST body from `cache[bufnr].lines[10..15]` (hashes from prior fetch), POSTs, awaits, refreshes on success. Where can each step go wrong?

2. **External edit invisible**: web UI marks line 42 as reviewed. nvim buffer is open, cache says line 42 is unreviewed. User runs `<leader>am` on line 42. What does the server do? What does the client show?

3. **External file write under nvim's feet**: the file on disk changes (git checkout). nvim doesn't autoread by default. Cache holds hashes from before the change. User runs mark on a line whose hash no longer matches the file. Server rejects with `stale_hash`. What does the user see, and what is the recovery path?

## Look for

- **Stale visual marks**: between `\27` (exit visual) and `getpos("'<")`, anything that moves the cursor or re-enters visual will overwrite the marks. Confirm `marks.lua` and `notes.lua` capture marks *before* exiting, or that exit is atomic with the read.
- **Modified-buffer guard bypass**: every code path that POSTs hashes must check `vim.bo[bufnr].modified` — otherwise the user marks lines that *they* changed locally but haven't saved, and the hashes in the cache no longer match the file on disk. Grep every POST site.
- **`fetched_at` written but never read**: the field exists for a reason that no longer applies, or it should drive a TTL. Flag as either "delete" or "implement" — leaving it is a future-trap.
- **No external-change detection**: README acknowledges the gap and suggests `:AuditviewRefresh`. Decide: is the right answer (a) SSE in nvim, (b) autoread + `BufReadPost` re-fetch, (c) mtime poll on `CursorHold`, (d) accept the limitation explicitly. The current state is "accept implicitly," which is the finding.
- **`session.state` race on parallel `BufReadPost`**: two buffers open near-simultaneously both call `resolve()` and `ensure_files_listed()`. Callbacks may interleave, and the second caller may see partially-mutated `state`. Inspect whether `resolve` deduplicates in-flight calls.
- **Orphan-note rendering**: server marks notes `is_orphaned=true` when anchor changes. Confirm orphans are *not* placed at the old line (would mislead the user) — they should appear only in the list view per the survey.
- **Hash divergence on rejection**: when `/lines/mark` returns `rejected[{reason: "stale_hash", ...}]`, the plugin refetches but doesn't show *why*. The operator's natural reaction is to retry, which succeeds (now hashes match) and leaves them confused about what just happened. Recommend surfacing the snapshot or a clear "the file changed since you opened it" message — see [[codeview-lens-error-propagation]].
- **Global cache unbounded growth**: `cache[bufnr]` only cleared on `BufUnload`. If the user uses `:bwipeout` (which fires BufUnload — good) vs `:bdelete` (also fires) vs `:enew` overwriting — confirm all paths clear. A long-running session with many opened files can grow indefinitely; bound by Vim's buffer count, but still worth measuring.
- **`vim.system():wait()` blocking on slow backend**: every API call freezes nvim. If the server is processing a large reconcile, the user UI hangs. Consider whether async (`on_exit` callback) is justified for at least the visible commands.
- **Severity sign fallback**: `buffer.lua` reads `severity_map = config.options.severity_sign_hl or {}`. If user config is missing a key, the note keeps a default highlight with no warning. Decide: silent-default vs warn-once.
- **Visual mark + multi-line range hash assembly**: the POST body's per-line `line_hash`/`context_hash` come from the *cache*, not from re-hashing the buffer. The cache may be stale relative to the buffer (modified-buffer guard should block) — but is it ever stale relative to the *file*? Cross-link [[codeview-lens-line-identity]].

## Diagnostic heuristic

When you read a cache access in this codebase, ask: *what is the worst that happens if this entry is exactly one edit behind reality?* If the answer is "the user is confused and the server silently rejects," that's the finding; if it's "data corruption," escalate.

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

## Related lenses

- The hash schema that both sides must agree on: [[codeview-lens-line-identity]].
- How rejections and offline-server are surfaced (or aren't): [[codeview-lens-error-propagation]].
- Why nvim is asymmetric vs the web UI on live updates: [[codeview-lens-sse-lifecycle]].
