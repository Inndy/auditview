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
uv run auditview [--debug] [--lsp] <path> # run server against a directory
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

**A watcher-driven reload holds the view still** - when `file_changed` names the open file,
`CodeViewer.captureViewAnchor()` records the cursor line's identity plus its pixel offset from the
top of the scroll container, and `restoreViewAnchor()` puts that line back at the same offset
afterwards and re-selects it. Line numbers are useless here — the edit that triggered the reload is
usually what moved them — so `ui/src/utils/lineAnchor.js` re-finds the line by content, falling back
from (`line_hash` + `context_hash`) to `line_hash` alone, because an edit to a *neighbour* breaks
the context hash of a line that did not itself change. With no cursor set the topmost visible row is
the anchor instead, so a plain scroll position survives too; if the anchor line is gone from the new
content, nothing is restored. Two things must stay true. The reload passes `quiet: true` to
`loadFile()`, which suppresses the `Loading…` placeholder: rendering it unmounts the table, collapses
the container to zero height, and destroys the scroll offset before it can be read back. And a
cursor that moved while the reload was in flight — a note click, `?line=` in the URL, a
go-to-definition jump — outranks the restore, which is why `restoreViewAnchor()` bails when
`cursorLine` no longer matches what was captured. That guard keys off the cursor specifically, so it
is blind to an interaction that moves the viewport *without* moving the cursor: a wheel or
right-stick scroll landing inside the reload window snaps back to the captured offset. The window is
tens of milliseconds and the result is recoverable by scrolling again, which is why there is no
input-source plumbing here to widen the guard.

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

**LSP is a client in `core/lsp.py`, opt-in, and never trusted about `.vue`** -
`--lsp` spawns language servers found on `PATH` as subprocesses, keyed by
**(server, resolved project root)** rather than by extension: a Vue project's
`.js` and `.vue` share one `jsconfig.json`, so splitting them by glob would hand
the halves inconsistent type views. `LspService` mirrors `WatcherService`'s
lifecycle (inert construction, `start(loop)`, one `run_worker()`, teardown) but
holds no DB connection - it is pure transport, and all path policy lives in
`api/lsp.py`.

Three things about this are counter-intuitive enough to be worth stating, all
established empirically (see `scripts/lsp-spike/README.md`, which is the
reference implementation and the record of how each was found):

- **`@vue/language-server` advertises `definitionProvider: true` and cannot
  answer it.** Only CSS and JSON stand behind it; TypeScript semantics come from
  `vtsls` with `@vue/typescript-plugin` loaded. A capability-driven router gets
  `[]` forever with nothing in the handshake to warn it. auditview therefore does
  not run the Vue server at all - which also avoids its `tsserver/request`
  bridge, whose promise has no timeout and deadlocks *every* request if the
  client does not implement it.
- **vtsls must be configured with `useSyntaxServer: "never"`.** It otherwise
  runs a syntax-only tsserver beside the semantic one, and that one answers the
  first query before the project has loaded - returning the position of the
  import specifier itself instead of the target. A wrong answer, not an empty
  one, and there is no readiness signal to wait on.
- **Positions stay in UTF-16 code units end to end.** A browser DOM text-node
  offset already is one, and so is LSP's default. Converting to a byte offset
  anywhere breaks every line containing non-ASCII text.

**Out-of-root definitions can never enter the coverage ledger** - most `gd`
targets in real work live in a dependency, a stdlib or a toolchain's own type
definitions. `GET /lsp/preview` reads them, and is structurally incapable of
polluting coverage: no hashes, no `is_reviewed`, no `is_countable`, no writes. It
serves only paths a definition query in that session actually returned, because
there is no authentication and an endpoint that read any absolute path handed to
it would be an arbitrary-file reader.

**A definition jump is a history entry; the URL is the jump list** - `?file=` +
`?line=` already encode the whole position of the code view, so `onGotoLocation()`
is the one navigation in that view that `push`es instead of `replace`ing. Back,
`Ctrl-O`, and a mouse's back button then all return to the jump origin with no
jump-stack state to keep in sync, and `Ctrl-I` goes forward again. Three things
hold this together:

- **Everything else still replaces.** Opening a file, moving the cursor and
  clicking a note rewrite the current entry, so arrow-key file browsing cannot
  bury the jump origin under a hundred entries — roughly the distinction vim draws
  between a motion and a jump. A note click is the one arguable omission; it would
  become a jump by routing `onNoteJump()` through `onGotoLocation()`.
- **A same-file jump pushes too**, so it is recoverable; that is why the route,
  not `jumpToRange()`, is the only way a definition target reaches the viewer.
  Because a cursor move also writes the route, `CodeView`'s `$route.query` watcher
  has to be *idempotent* rather than flag-guarded: it applies a jump only when the
  viewer's range is not already there. The `_writingFromCursor` boolean it replaced
  was order-dependent — two route writes coalescing into one watcher run left the
  flag set and swallowed the next real jump.
- **`CodeViewer.onSymbolClick()` moves the line cursor to the clicked line before
  the definition request goes out.** Ctrl/Cmd+click otherwise leaves the cursor
  alone, so the entry being left behind would record a stale cursor line, or no
  line at all. Writing it through the cursor — which `onSelectionChange` already
  mirrors into the query — keeps this to a single navigation: an explicit
  `replace`-then-`push` pair races, and the loser is the origin.

`JUMP_BACK` refuses to move below the `window.history.state.position` recorded when
`CodeView` mounted, which is what keeps `Ctrl-O` from stepping out of the review
view or off the site entirely on a deep link. It no-ops instead of declining to
run: an action that returns false hands the key back to the browser, and Ctrl-O
there opens a file picker over the review.

**No `gd`/`gr` keybinding, deliberately** - the code cursor is line-only
(`cursorLine`/`anchorLine`), so a keyboard chord cannot say *which* symbol on the
line is meant, and most lines hold several. Ctrl/Cmd+click carries an exact
column for free via `caretRangeFromPoint` plus a text-node walk
(`ui/src/utils/textPosition.js`), leaving the highlight pipeline untouched. The
`g` prefix stays free for a later keyboard pass, which would want a real column
cursor and `w`/`b`/`e` motions with it.

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
