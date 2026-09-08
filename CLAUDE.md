# CLAUDE.md

> This file is also symlinked as `AGENTS.md` for compatibility with other coding agents.

## Documentation map

| You want to know about … | Read |
|---|---|
| Project purpose and use cases | README.md |
| Architecture, core concepts, design philosophy | CLAUDE.md (here) |
| HTTP API routes, shapes, status codes | API.md |
| Neovim plugin | nvim/README.md |
| Future plans | ROADMAP.md |

### Where to add new information

| Type of change | Update this file |
|---|---|
| New route or changed response shape | `API.md` — in the same commit as the code change |
| New architectural decision or constraint | `CLAUDE.md` §Architecture |
| Design philosophy note | `CLAUDE.md` §Design philosophy |
| New planned feature | `ROADMAP.md` |
| Project-level vision or use case | `README.md` |

## Development Commands

**Backend** (Python, managed with `uv`):
```bash
uv run auditview [--debug] <path> # run server against a directory
```

**Read-only CLI** (queries `.auditview.db` directly; no server required):
```bash
auditview context                                  # active session + repository root
auditview stats                                    # session-wide coverage, issue counts
auditview files --status not_viewed --sort size --json
```

**Frontend** (Vue 3, use `pnpm`):
```bash
cd ui
pnpm run build
pnpm run lint
pnpm run dev
```

**Dev server (for AI agent):**
- To pick up code changes, run `./scripts/dev-restart.sh`. It signals the running supervisors to relaunch in place.
- If it errors with "not running", start your own background server - do **not** invoke `./scripts/dev-start.sh`. That script is for a human in tmux only; it splits the current pane and would hijack your terminal.

## Documentation

When modifying backend code under `auditview/api/` (or anything else that changes request/response shapes, status codes, error codes, or routes), update `API.md` in the same change. `API.md` is the source of truth for clients (frontend, Neovim plugin, MCP integrations) and drifts silently otherwise.

## Architecture

### Overview

Auditview is a line-level code review/audit tool: a Quart (async) JSON API backend with a Vue 3 SPA frontend, served as static files from the same process. `auditview/static/` is gitignored — it is populated from `ui/dist/` before publishing. Agents do not need to copy build output there.

- auditview/core/ - business logic - no Quart imports here
- auditview/api/ - one Quart blueprint per resource (sessions, files, lines, …)
- auditview/db/ - aiosqlite wrapper (`open_db` async context manager)
- auditview/cli.py - read-only query subcommands, dispatched from `__main__.py`
- ui/src/api/ - fetch wrappers, file-per-resource mirrors backend
- ui/src/input/ - action registry + keyboard and gamepad input sources

### Key Design Decisions

**Content-based line identity** - reviewed state is never tied to line numbers. Each `reviewed_lines` row stores `line_hash` (SHA-256 of content) + `context_hash` (SHA-256 of prev+curr+next) as a tiebreaker for duplicate lines. When a file changes, `reconciler.py` uses `difflib.SequenceMatcher` to map old line positions to new ones, migrating or deleting rows accordingly. The hard safety invariant: **never migrate a mark onto a line with different content or context**. Content-identical migrations are always acceptable — diff output is not unique, and the same edit can produce multiple valid patches that land a mark on a different physical instance of the same line; that is correct behaviour, not a bug. A line is split on `\r\n`, `\r` or `\n` and nothing else (`io_utils._split_lines`): `str.splitlines()` also breaks on `\f`, `\v`, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029, and every other consumer of these numbers — editors, git, the nvim client, an LSP server — splits on newlines alone, so a form feed (a page separator in real C and Python) would shift every later line number in the file away from what the user sees. A trailing terminator ends the last line rather than starting an empty one, and an empty file has zero lines; both match `splitlines()` and a phantom trailing line would inflate the line count of essentially every file.

**aiosqlite with autocommit** - `open_db()` opens a connection with `isolation_level=None` (autocommit). Code that needs atomic writes uses explicit `await conn.execute("BEGIN")` / `await conn.commit()` / `await conn.rollback()`. All rows are `aiosqlite.Row` (dict-accessible by column name).

**SSE for real-time** - no WebSockets. `WatcherService` holds one `asyncio.Queue` per connected client; `events.py` yields from the queue with a 15-second heartbeat. Client→server is always plain HTTP (mark, note actions).

**Vue Options API for components (personal preference)** - keep all new `.vue` components in Options API style. Composition API may be mixed in non-component modules (e.g. `ui/src/api/events.js` exposes `sseClient.status` as a `ref()`) when it yields a more elegant architecture — for example, a singleton service whose reactive state is consumed by components via a computed.

**One action registry, two input sources** - `ui/src/input/actions.js` is the single table of user actions in the review view: label, key bindings, gamepad bindings, and a `run(targets, params)` thunk. `keyboard.js` resolves a `KeyboardEvent` to an action id (it owns the vim count buffer and the `z`/`[`/`]`/`g` prefix timeout, which have no gamepad analogue); `gamepad.js` polls the Gamepad API in `requestAnimationFrame` and resolves a button/axis to an action id. Both call `dispatch()`, which applies the shared guards (a dialog is open → only `context: 'modal'` actions; a text field has focus; `requiresSelection`). Held-input behavior (`padRepeat` / `padContinuous`) belongs to the action rather than the physical input, so the same button may repeat ordinary navigation without repeating a modifier chord such as pane switching. `CodeView` is the only input host: it registers the `$refs` the actions operate on via `setTargets()` and owns which pane has gamepad focus. `KeyboardHelpModal` renders its table from the registry, so documentation cannot drift from the bindings.

Gamepad support targets the W3C **standard** mapping (Xbox layout) only. A Steam Controller or Steam Deck reports that mapping through Steam Input, which also consumes the touchpads before the browser sees them — pad coordinates are not readable from a browser, and the right pad arrives as ordinary mouse movement. `/gamepad` is a live input dump for checking an unfamiliar pad; both the action→button map and the physical input map are overridable from `localStorage` (`auditview:gamepad:bindings`, `auditview:gamepad:inputs`).

**`WatcherService` uses asyncio.Queue for thread→async bridging** - watchdog runs file observer threads that post paths via `loop.call_soon_threadsafe`. An async worker task consumes and does all DB work. Each operation opens its own short-lived aiosqlite connection.

The handler must implement `on_moved` alongside create/modify/delete: inotify pairs `IN_MOVED_FROM`/`IN_MOVED_TO` into a single move event whenever both ends are inside the watched tree, so an atomic save (write temp, rename over the target) — what editors, `sed -i`, and `git checkout` all do — arrives *only* as `on_moved`. Dropping it leaves `reviewed_lines` and `countable_lines` frozen at pre-edit values, so a fully reviewed file keeps reporting 100% until something else forces a reconcile.

**`core/progress.py` is the single source for coverage queries** - `file_progress()`,
`session_coverage()`, `issue_counts()` and `active_session()` take a bare connection and are
called by `api/files.py`, `api/coverage.py`, `api/config.py` and `cli.py` alike. Adding a fourth
consumer means calling these, never re-writing the SQL. Response shapes in `API.md` are these
functions' return values verbatim.

**The CLI is read-only, and reads to agents / writes through MCP** - `auditview context|stats|files`
resolve the DB (`--db` → `$AUDITVIEW_DB` → search upward for `.auditview.db`) and the session
(`--session` → `app_config.mcp_session_id` → sole session), then query. Agents read coverage this
way because it needs no running server and no port discovery; they write via the MCP tools, which
handle reconciliation and SSE broadcast. `__main__.main()` routes to the CLI when any argument is
exactly a subcommand name; `auditview serve <path>` is the escape hatch for a directory that
shares one of those names.

**Coverage is the human's ledger; agents must never mark lines reviewed** - a reviewed line means
a person read it. If an agent writes `reviewed_lines`, the metric stops meaning anything and every
recommendation built on it becomes circular. The CLI exposes no marking subcommand, and the
`audit-triage` / `audit-explain` skills state the prohibition explicitly. Agents record what they
find as notes and issues instead.

**Walkthrough issues use a `source` convention, not a schema flag** - an issue whose `source`
starts with `agents:explain` is a code walkthrough rather than a defect: `IssuesView.vue` shows a
`flow` badge and dims the severity, and its notes render `snapshot_text` inline via
`NoteSnippet.vue`. `GET /issues/:id/notes` orders by `created_at, id`, so an agent creating notes in
flow order produces the reading order for free — there is no explicit step column. The `id`
tiebreak is load-bearing: `created_at` is second-granular, so a burst of inserts would otherwise
fall back to index order (by `file_path`) and scramble the walkthrough.

**MCP endpoint** - `/mcp` serves JSON-RPC 2.0. Tool handlers call existing REST endpoints internally via Quart's async test client.

### Design philosophy

- **Composability over convenience, repairability over foolproofing.** The system should be transparent enough that a power user can understand and manually fix any state. No sealed black boxes.
- **Escape hatches over hard failures.** Corner cases should be handleable with minimal intervention. (A changeset-based undo system existed under the old apsw backend and was dropped during the Quart migration; this goal is currently unmet at the DB layer.)
- **Thin abstractions, not speculative ones.** Do not add abstraction layers without a concrete reason present in the current codebase.
- **Target: power user.** The tool assumes the user understands the system's concepts. Guardrails should not obscure behaviour or hide state.

### Tests

Pytest + pytest-asyncio (strict mode) live under `tests/`. Install dev deps with `uv sync --group dev`, then run with `uv run pytest`.

The first test is a **reconciler fuzzer** (`tests/test_reconciler_fuzz.py`): it generates synthetic files + random edit patches with ID-tracked ground truth, runs the real `reconcile_file`, and reports migration outcomes. The reconciler is content-based: migrating a mark to a line with identical content and identical context (prev+curr+next) is semantically correct even if the line was freshly inserted — the fuzzer reports these as informational "FP" counts but does not fail on them. False unmarks (dropped marks) are counted and acceptable. When an ID-based FP is found, the harness shrinks the case and writes a minimal repro to `tests/fuzz/saved_seeds/fp_<sha8>.json`. **Treat anything committed under `tests/fuzz/saved_seeds/` as a documentation fixture** — examples of known content-identical migration patterns.

Flags: `--fuzz-iters=N` (default 100), `--fuzz-seed=N` (default 0), `--fuzz-save-fn` (also save a capped sample of false-unmark cases for later classification).

When writing a test or fuzzer harness that spins up a temporary SQLite DB per iteration, probe for `/dev/shm` and use it as the temp dir base when present — this keeps the DB on tmpfs and avoids fsync/journal I/O overhead:

```python
import os, tempfile
def _tmp_root():
    return "/dev/shm" if os.path.isdir("/dev/shm") else None

with tempfile.TemporaryDirectory(dir=_tmp_root()) as tmp:
    ...
```

Fall back to the system default (`None`) when `/dev/shm` is absent (macOS, some containers).
