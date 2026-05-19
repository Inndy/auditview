# auditview — Specification

> **Deprecated.** This was an early design spec written before the current implementation.
> It references stale technologies (Flask → Quart, apsw → aiosqlite) and some details no longer
> match the codebase. Authoritative sources: `README.md` (purpose/use cases), `CLAUDE.md`
> (architecture + design philosophy), `API.md` (API contract). A rewrite is planned.
> This file is kept for historical context.

## Purpose

A line-level code review tool targeting **security audit and vibe coding review**.
Primary goal: track 100% line coverage across a folder, with notes/todos, surviving live code edits.

---

## Core Concepts

### Review Session

A session binds to a root folder path. Everything (file tracking, line states, notes, checkpoints) lives under a session. Multiple sessions can exist for the same folder (e.g. different reviewers or passes).

### Line Identity

Line review state is **content-based, not line-number based**. Line numbers are derived/display values only.

When a file changes, `difflib.SequenceMatcher` aligns old lines to new lines:
- Matched lines carry their review state forward; stored line numbers are updated to new positions.
- Unmatched new lines (insert/replace) are unreviewed.
- Deleted reviewed lines are removed from state.

For duplicate lines (e.g. repeated `pass` or closing braces), a **context hash** (SHA-256 of prev + current + next line) is stored alongside the line hash as a tiebreaker. SequenceMatcher naturally preserves relative order, which is good enough for most cases.

### Coverage

Coverage = reviewed lines / countable lines.

**Countable line rules:**
- Blank lines (whitespace-only or empty) are always excluded.
- Comment-only lines are excluded when the "skip comments" toggle is on.
- Comment detection is heuristic per extension (lines matching `^\s*#`, `^\s*//`, `^\s*\*`, etc.); no full AST parsing.

### File Change Reconciliation

On every file change event from watchdog:
1. Read old line state from DB.
2. Read new file content.
3. Run `build_line_map(old_lines, new_lines) → dict[old_lineno, new_lineno | None]`.
4. Migrate reviewed_lines and notes using the map.
5. Write changes inside a single DB transaction, wrapped by a checkpoint (see Checkpoints).
6. Broadcast SSE event to all connected clients.

### Note Anchoring and Orphaning

Notes are anchored to a line range `[start, end]` using **boundary-based identity**: the content hash of the start line and the end line are stored at creation time. The full text of the anchored range is also snapshotted at creation time.

Reconciliation rule:
- If both boundary lines survive (matched in line_map) → note stays alive, line numbers updated.
- If either boundary line is deleted or modified (line_map value is None or content hash changed) → note becomes **orphaned**.
- Lines changing *within* the range do not trigger orphaning.

Orphaned notes are displayed in a dedicated panel with their original snapshot text, separately from live notes.

---

## Tech Stack

### Backend

- **Language:** Python, managed with `uv`
- **Web framework:** Flask
- **Push:** Server-Sent Events (SSE); WebSocket is not needed because all client→server actions are regular HTTP calls (mark, note, etc.)
- **Database:** SQLite via **apsw** (primary), with automatic fallback to stdlib `sqlite3`
- **File watching:** `watchdog`
- **Exclusion patterns:** `pathspec` (gitignore syntax)

SSE implementation: watchdog thread puts events into a `queue.Queue` per connected client; the SSE generator yields from the queue. Serve with `waitress` or `cheroot`, not Flask dev server.

### Frontend

- **Vue 3, Options API only** — Composition API is intentionally avoided.
- **Package manager:** pnpm
- **Syntax highlighting:** highlight.js (client-side, language auto-detect)
- Built as static assets, served by Flask.

### Core / Frontend Separation

All business logic (reconciler, scanner, session management, DB) is **frontend-agnostic Python**. Flask+Vue is one possible frontend. The same Python core should be trivially usable from a future Neovim plugin or CLI by swapping the presentation layer only.

---

## Database

SQLite. Schema migrations tracked by a `schema_version` table.

**WAL mode enabled at startup:**
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
```

### Checkpoints (apsw session extension)

Every reconciliation is wrapped in an apsw session changeset:
1. `session.attach()` on `reviewed_lines` and `notes` before any writes.
2. Perform all DB mutations.
3. Call `session.changeset()` → store the binary blob in `checkpoints` table with a label (e.g. `reconcile:src/main.py`).
4. Auto-prune: keep last 1000 checkpoints per session.

Revert = apply the inverted changeset (`apsw` handles inversion). The changeset blob is a standalone artifact: can be inspected or applied externally via apsw tooling without the app.

**Stdlib fallback:** if apsw is not installed, `checkpoint_begin/save/revert` are no-ops or raise clearly. Core review functionality still works; checkpoint protection is disabled. `supports_checkpoints() → bool` lets the UI surface a warning.

The DB backend is selected once at startup; the rest of the codebase calls through a thin protocol so the choice is invisible to business logic.

### Exclusions

Two sources, merged:
1. Session-level patterns (stored in DB, gitignore syntax via `pathspec`).
2. `.gitignore` at the root (auto-loaded if present).

Default excludes always applied: `**/__pycache__/**`, `**/.git/**`, `**/node_modules/**`, `**/.venv/**`.

### Git Integration

Out of scope for now. Potential future addition: `git blame` display per line. No current design commitment.

---

## Web UI Behaviour

### Line Selection

Click and drag on the **line number gutter** to select a range. Keyboard shortcuts apply to the current selection:

| Key | Action |
|-----|--------|
| `m` | Mark selected lines as reviewed |
| `u` | Unmark selected lines |
| `t` | Add TODO note on selected range |
| `n` | Add note on selected range |
| `Esc` | Clear selection |

Mark semantics on a mixed selection: if all lines are reviewed → unmark all; otherwise → mark all (fill in the gaps).

### Real-time Updates

When the backend detects a file change and reconciles, an SSE event is pushed. The frontend re-fetches that file's line state. No full page reload.

---

## Packaging

- Final package published to PyPI via `uv build`.
- Vue frontend is built (`pnpm build`) and the resulting static assets are included in the Python package (e.g. as package data under `auditview/static/`).
- Entry point: `auditview <path>` starts the Flask server and opens (or prints) the URL.
- Developer initialises `pyproject.toml` and the `web-ui` node package manually; scaffolding is out of scope for the agent.

---

## Design Philosophy

*Carried from the author's broader engineering philosophy:*

- **Composability over convenience, repairability over foolproofing.** The system should be transparent enough that a power user can understand and manually fix any state. Do not design a sealed black box.
- **Escape hatches over hard failures.** Corner cases should be handleable with minimal intervention. The checkpoint system exists specifically so that a reconciler bug does not permanently destroy review history — the user can revert at the DB level even without the app.
- **Thin abstractions, not speculative ones.** The DB protocol layer exists to isolate the apsw dependency, not for abstract flexibility. Do not add abstraction layers without a concrete reason present in this spec.
- **Target: power user.** The tool assumes the user understands the system's concepts. Guardrails should not obscure behaviour or hide state.
