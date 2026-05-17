---
description: Review concurrency in the backend — WatcherService coordinating watchdog threads, asyncio worker, and request handlers over shared dicts; aiosqlite autocommit with partial BEGIN/COMMIT coverage. Use when touching watcher.py, any DB write path, or anything that registers SSE clients.
allowed-tools: Read, Glob, Grep
---

# Lens: concurrency & shared state

**Why this matters for this codebase:** Three execution contexts touch the same data — (1) **watchdog observer threads** (filesystem events), (2) the **asyncio event loop's worker task** (`run_worker`), (3) **per-request async handlers**. They coordinate via a `threading.Lock`, an `asyncio.Queue`, a thread-safe scheduling call (`loop.call_soon_threadsafe`), and several shared dicts. On top of that, the DB connection is opened with `isolation_level=None` (autocommit); only some write paths wrap in explicit `BEGIN`/`COMMIT`. Bugs here are timing-dependent, won't show in tests, and corrupt review state silently.

## Start at

- `auditview/core/watcher.py` — read the whole file with the contexts annotated in mind:
  - `_clients: dict[session_id, list[Queue]]` (line ~78–101, guarded by `_lock`).
  - `_work_queue: asyncio.Queue` (line ~70, loop-only).
  - `_pending_paths: set` (debounce buffer, loop-only).
  - `_scan_cache: dict[session_id, …]` (line ~103, guarded by `_lock`; invalidation by setting to `None`).
  - `_session_specs: dict[session_id, (root_path, spec)]` (line ~111, guarded by `_lock`).
  - `_Handler.on_modified/_created/_deleted` → `_handle_change` → `loop.call_soon_threadsafe(_enqueue_path, …)`.
  - `run_worker()` consumes `_work_queue` → `_do_process_change()` → `reconcile_file()` → `broadcast()`.
- `auditview/db/connection.py` — confirm `isolation_level=None` and `journal_mode=WAL`.
- Every DB write site (grep for `await conn.execute("INSERT"|"UPDATE"|"DELETE"`): `auditview/api/notes.py`, `auditview/api/lines.py`, `auditview/api/issues.py`, `auditview/api/files.py`, `auditview/core/watcher.py`, `auditview/core/reconciler.py`.

## Follow

For each shared structure, build a 2-column table in your head: **who reads / who writes**, annotated with **execution context**. Then for each DB write site, check whether it's wrapped in an explicit transaction or relies on autocommit. Then trace one full event: filesystem write → watchdog thread → `call_soon_threadsafe` → loop → debounce → worker → reconcile → broadcast → SSE client queue → request-context generator yield.

## Look for

- **Watchdog-thread mutation without `_lock`**: any access to `_clients`, `_scan_cache`, or `_session_specs` from `_Handler` or `_handle_change` that doesn't take the lock. Watchdog threads run concurrently with the loop — unlocked dict mutation can corrupt or raise.
- **Lock held across blocking work**: `_lock` is `threading.Lock`. If it is held across an `await`, an `asyncio.to_thread`, an executor `scan_folder`, or any I/O, the lock can serialize all SSE clients and request handlers. Specifically check `get_scan()` (~line 103–111).
- **Autocommit write races**: when multiple async handlers run unwrapped writes (e.g. `notes.py:98` INSERT), aiosqlite executes them serially per connection, but each route opens its own connection. Two concurrent notes creations can both pass a "max id" check and both INSERT — find any read-then-write that should be wrapped in BEGIN/COMMIT.
- **Reconciliation atomicity vs concurrent route writes**: `reconcile_file()` does BEGIN/COMMIT over many rows. A concurrent `/mark` request opening its own connection can observe partial state (WAL gives consistent snapshots, but post-commit ordering still matters — the route may write hashes that the reconciler has already migrated, leaving an orphan). Trace whether routes serialize against in-flight reconciliation for the same file (likely they don't — that's the finding).
- **Queue overflow as silent drop**: `broadcast()` uses `put_nowait` and swallows `QueueFull` (~line 101). Maxsize is 128. If any event is semantically must-deliver (e.g. shutdown), this is a bug; see [[codeview-lens-sse-lifecycle]] for the client-side consequences.
- **`call_soon_threadsafe` after loop close**: during shutdown, the watchdog observer may still be running and post one more change. Confirm `_Handler` checks loop state, or that the observer is stopped *before* the loop closes.
- **`_scan_cache` invalidation by `None`**: the convention is "`is not None`" rather than `del`. A second writer can set it to `None` between a reader's `if x is not None` and the subsequent use — annotate the lock window.
- **`run_worker` bare `except Exception`** (~line 75): which exceptions are *expected* (file missing, permission denied) vs *bug-induced* (KeyError, TypeError)? Bare except hides both equally — see [[codeview-lens-error-propagation]] for the visibility consequence.
- **MCP loopback under load**: `mcp.py` calls `quart_app.test_client()` inside a route. Test clients construct ASGI scope; under concurrent calls, confirm no shared state leaks between the outer and the looped-back request. Cross-link [[codeview-lens-trust-boundary]] for the *who* axis.
- **Ownership documentation absent**: there is no doc-comment that says "field X is only mutated on the loop; field Y only under `_lock`". The absence is itself the finding — flag any new shared field that ships without that note.

## Diagnostic heuristic

For each shared mutable: if you can't write a one-line ownership rule ("only mutated from the loop"; "always read+written under `_lock`"), the field is the bug.

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
