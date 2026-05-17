---
description: Trace where failures vanish across backend → API → UI/nvim. Use when reviewing error-handling code, when failure modes feel underspecified, or after touching anything that catches an exception or returns an error response.
allowed-tools: Read, Glob, Grep
---

# Lens: error propagation

**Why this matters for this codebase:** A failure should land somewhere a human will see — a log, a notification, a status indicator, an error response. Auditview's stack has several silent-swallow points: the watcher's `run_worker` bare `except Exception` (continues without surfacing), `broadcast()` queue-full dropping events with `put_nowait`, `reconcile_file()` IO failures returning early, UI per-component `catch(console.error)`, and nvim's `vim.notify` without retry. Each is defensible alone; together they create a stack where a partial outage looks identical to "everything is fine."

## Start at

- **Backend**:
  - `auditview/core/watcher.py` → `run_worker`, `_do_process_change` — bare `except Exception` (~line 75); does the failure reach SSE clients or only the log?
  - `auditview/core/reconciler.py` → `reconcile_file()` early returns on `read_file_lines` failure (~line 182).
  - Grep `jsonify({"error"` across `auditview/api/` — the response shape, the missing HTTP codes, whether any structured error code accompanies the string.
  - `auditview/api/events.py` — SSE error frames (do any exist?).
- **UI**:
  - `ui/src/api/client.js` → `apiFetch` — what `Error` it throws, whether HTTP status survives.
  - Every `catch` block in `ui/src/views/IssuesView.vue`, `SessionListView.vue`, `CodeView.vue`, and modal components — what they do beyond `console.error`.
  - Optimistic update sites in `IssuesView.vue` — what happens if the API call fails mid-edit.
- **Nvim**:
  - `nvim/lua/auditview/http.lua` — every `vim.notify` call.
  - `nvim/lua/auditview/marks.lua` rejection handler — how `rejected[]` reasons are surfaced.

## Follow

Pick a single induced failure and trace it across the stack. Example: backend hits `PermissionError` while reading a file during reconciliation. Where does that failure surface? Log only? An SSE error frame? An HTTP 500 on the next request? Or nowhere?

Repeat for: (a) DB constraint violation during note insert, (b) malformed mark POST from the client, (c) SSE disconnect mid-stream, (d) MCP loopback to a deleted session, (e) nvim curl exit non-zero, (f) UI route load racing a session deletion.

## Look for

- **Bare excepts hiding bug-induced exceptions**: `run_worker`'s `except Exception` should distinguish between *expected* OS-level errors (file vanished, permission denied — log and continue) and *unexpected* programming errors (`KeyError`, `TypeError` — log loudly, ideally surface). The current shape treats both identically. Suggest narrowing the catch.
- **Inconsistent error response shape**: some routes return `{error: "message"}`, some return only an HTTP status, some return 200 with `{ok: false, …}`. Inventory the shapes; recommend one. Without an error *code*, clients can't program against errors — they can only show text.
- **`apiFetch` discards HTTP status**: confirm whether the thrown `Error` carries `status`/`code` properties. If callers can only access `.message`, they can't differentiate "permission denied" from "resource gone".
- **Per-component `console.error` only**: identify catches where the user gets no UI signal — silent failure. The IssuesView optimistic update paths are the highest-risk: state diverges from server with no banner, no retry, no rollback.
- **SSE never reports backend failures**: `reconcile_file` failure → `_do_process_change` swallows → broadcast not emitted → UI sees the file as "unchanged." Should there be an `{type: "error", rel_path: …}` event for this case? Frame it as a question, not a prescription.
- **`broadcast()` queue-full as silent loss**: see [[codeview-lens-sse-lifecycle]] for the mechanism; the *propagation* finding here is that neither side knows about the drop.
- **Nvim mark rejection without diff**: server returns `rejected[]` with reasons (`stale_hash`, `not_found`, …). Plugin's `marks.lua` warns via `vim.notify` and refetches — but never shows *why* the line was rejected. The operator who edited the file externally has no signal. Recommend including the line snapshot or a hint to run `:AuditviewRefresh`.
- **Nvim backend-offline UX**: every action retries from scratch with a fresh curl. No status indicator, no "server unreachable" banner. The operator sees N error toasts per operation. Cross-link [[codeview-lens-nvim-cache-drift]].
- **Optimistic updates without compensation**: IssuesView's title/severity edits update local state, then submit. If the API fails, the edit stays in the UI but is not on the server. Field-by-field rollback would require holding pre-edit state — confirm whether it does.
- **Failure timing across boundaries**: when reconciliation fails partway through (BEGIN, some inserts, then exception), `ROLLBACK` reverts the DB but the SSE broadcast may have already fired *before* the commit. Verify broadcast happens after commit, not before.
- **The detection gap as a finding**: list every place where a failure exists but no observer can detect it. That list is the deliverable of this lens.

## Diagnostic heuristic

For every `except`, `catch`, `pcall`, `... ok then`, ask: *if this swallowed an error right now, who would notice, and how soon?* If the answer is "no one" or "next person who looks at the log," the call site is a finding — propose the surfacing channel.

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

- Channel mechanics of SSE delivery: [[codeview-lens-sse-lifecycle]].
- Bare-except categorization in the worker: also relevant to [[codeview-lens-concurrency]].
