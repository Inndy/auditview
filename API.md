# auditview — API Contract

All endpoints are under `/api`. Request/response bodies are JSON unless noted.
Request bodies shown as objects reject missing fields and values of the wrong
scalar type with `400`; malformed or non-object JSON is treated as having no
fields, rather than causing an internal server error.
Errors return `{"error": "<message>"}` with an appropriate HTTP status.

The server is bound to a single `root_path` and `db_path` chosen at startup
(see `GET /api/config`). Session creation does **not** accept `root_path` from
the request — it is always taken from the running process configuration.

---

## Sessions

### GET /api/sessions

List all sessions.

**Response 200**
```json
[
  {
    "id": 1,
    "label": "First pass",
    "root_path": "/home/user/myproject",
    "exclusion_patterns": "*.log\nbuild/",
    "created_at": "2026-05-14T10:00:00Z"
  }
]
```

---

### POST /api/sessions

Create a new session. `root_path` is taken from the server's startup config;
clients cannot override it.

**Request body**
```json
{
  "label": "First pass",
  "exclusion_patterns": "*.log\nbuild/"
}
```
- `label`: required, non-empty string
- `exclusion_patterns`: optional (default `""`), gitignore-syntax patterns separated by newlines

**Response 201**
```json
{
  "id": 1,
  "label": "First pass",
  "root_path": "/home/user/myproject",
  "exclusion_patterns": "*.log\nbuild/",
  "created_at": "2026-05-14T10:00:00Z"
}
```

**Errors**
- `400` — missing/invalid fields, or an `exclusion_patterns` value that does not
  compile (validated before storing, for the reason given under `PATCH`)

---

### PATCH /api/sessions/:id

Update a session's `label` and/or `exclusion_patterns`. At least one field must
be present. This is the supported way to change what a session tracks after the
review has started.

Changing `exclusion_patterns` alone does not remove already-tracked files — call
`POST /api/sessions/:id/rescan?force=1` afterwards.

**Request body**
```json
{
  "label": "Second pass",
  "exclusion_patterns": "*.log\nbuild/"
}
```
- `label`: optional, non-empty string
- `exclusion_patterns`: optional, gitignore-syntax patterns separated by newlines

**Response 200**: the updated session row, same shape as `GET /api/sessions`.

**Errors**
- `400` — no updatable field, empty `label`, non-string `exclusion_patterns`, or
  an `exclusion_patterns` value that does not compile. Patterns are validated
  before they are stored: an unparseable pattern would otherwise raise on every
  subsequent scan with no way to correct it through the API.
- `404` — session not found

---

## Files

### GET /api/sessions/:id/files

List all tracked files with per-file coverage and counts.

**This endpoint never scans the filesystem.** It reports the `files` table as it
stands, so a file created since the last scan is absent from the response and
`GET /files/:path` returns 404 for it. `POST /api/sessions/:id/rescan` is the
only endpoint that adopts a new file; a client whose job is to display current
state (a file tree, a progress list) should call that instead of this.

**Response 200**
```json
[
  {
    "rel_path": "src/main.py",
    "countable_lines": 120,
    "reviewed_lines": 45,
    "coverage": 0.375,
    "status": "partial",
    "notes_count": 2,
    "todos_count": 1,
    "max_severity": "P1",
    "open_issue_count": 3
  }
]
```
- `coverage` is `reviewed_lines / countable_lines`; `0` if `countable_lines == 0`
- `status` is one of `"empty"` (no countable lines), `"unreviewable"` (large,
  binary, missing during the scan, or unreadable), `"not_viewed"` (none reviewed),
  `"partial"` (some reviewed), or `"reviewed"` (all countable lines reviewed)
- `reviewed_lines` counts only marks on countable lines (a marked blank or
  comment-only line is stored but not counted), and is clamped to
  `countable_lines` so stale rows can't push it above 100%
- `notes_count` / `todos_count` count only **live** (non-orphaned) notes
- `max_severity` is `"P0"` | `"P1"` | `"P2"` | `null` — the highest severity among
  **open** issues attached to any live note in this file. `null` when no open
  issues touch the file. Resolved/dismissed issues are excluded.
- `open_issue_count` is the number of **distinct open** issues attached to any
  live note in this file (`0` when none). Resolved/dismissed issues are excluded.
  An issue with multiple notes in the same file is counted once.
- Files are sorted by `rel_path` ascending

**Errors**
- `404` — session not found

---

### POST /api/sessions/:id/rescan

Re-scan the session root: insert newly-discovered files, drop files that no
longer exist (orphaning their notes and removing their reviewed-line rows),
and backfill `countable_lines` for any new entries. Returns the same shape as
`GET /api/sessions/:id/files`.
Files over 1 MiB and binary or unreadable files remain tracked but receive
`status: "unreviewable"`; rescan does not read them in full. They contribute
neither lines nor files to aggregate coverage.


**Request body**: empty (`{}` or no body)

**Query parameters**

| Param | Effect |
|---|---|
| `force=1` | Bypass the cached scan and re-walk the tree from disk. Required to pick up edits to `exclusion_patterns` or to any nested `.gitignore`. |
| `purge=1` | Hard-delete the notes of files dropped **because they are now excluded**. Implies `force`. |

Without `force`, the result is served from a per-session scan cache. The cache
exists because clients rescan on every SSE event; an unforced rescan will not
see filesystem or pattern changes.

`purge=1` distinguishes the two reasons a tracked file can go stale:

- **newly excluded** — its notes are deleted outright and the database is
  `VACUUM`ed, so the stored line snapshots are no longer recoverable from the file
- **merely missing from disk** (a `git checkout`, a cleaned build directory) —
  its notes are orphaned as usual and stay recoverable

That distinction is deliberate: `purge=1` must not destroy review state for a
file that is only temporarily absent.

**Response 200**: same shape as `GET /api/sessions/:id/files` — always a bare
array, regardless of query parameters.

A forced rescan that actually changed the tracked set broadcasts one
`file_changed` with `rel_path: null`. Unforced rescans never broadcast, since
clients rescan in response to that event.

**Errors**
- `404` — session not found

---

### POST /api/sessions/:id/purge-preview

Dry run for a purge: which tracked files it would hard-delete, and how much
review progress each one carries. Mutates nothing — the candidate scan
deliberately bypasses the watcher's scan cache so patterns that are never saved
cannot leak into it.

**Request body** — one of:
```json
{ "exclusion_patterns": "*.log\nbuild/" }
```
```json
{ "path": "config/secrets.yaml" }
```
- `exclusion_patterns`: candidate pattern set. Defaults to the session's stored
  value. Files that would fall outside it are reported.
- `path`: single file or directory subtree, validated as for `POST .../purge`.

**Response 200**
```json
{
  "purge_files": [
    {"rel_path": "config/secrets.yaml", "reviewed_lines": 12, "notes_count": 2, "todos_count": 1}
  ],
  "orphan_paths": ["deleted_upstream.py"],
  "at_risk_count": 1,
  "total_reviewed_lines": 12,
  "total_notes": 2,
  "total_todos": 1
}
```
- `purge_files`: paths that would be hard-deleted, with what each would destroy
- `orphan_paths`: paths that are stale only because they are missing from disk.
  These are orphaned, never purged, so their notes stay recoverable.
- `at_risk_count`: how many entries in `purge_files` carry any reviewed line,
  note, or todo. `0` means the purge destroys no review progress.

**Errors**
- `400` — `exclusion_patterns` not a string or not compilable; invalid `path`
- `404` — session not found

---

### POST /api/sessions/:id/purge

Permanently remove a file, or a directory subtree, from the session and keep it
out of future scans.

Unlike a stale-path drop, this **hard-deletes the notes** rather than orphaning
them, then `VACUUM`s. That matters because `notes.snapshot_text` stores raw line
content: for a file holding credentials, orphaning leaves the secret in the
database. `reviewed_lines` and `files.prev_line_hashes` hold only hashes.

The path is appended to the session's `exclusion_patterns` as an anchored,
escaped gitignore pattern, in the same transaction as the deletes. Purging a path
that is not currently tracked still records the pattern.

Issues are **not** deleted. An issue is a finding, not a file, and survives with
zero attached notes. Note that `issues.title` and `issues.description` are
free-form text this endpoint does not touch — if a credential was pasted there,
delete the issue separately.

**Request body**
```json
{ "path": "config/secrets.yaml" }
```
- `path`: required, relative to the session root. Matches that exact file plus
  everything beneath it if it is a directory.

**Response 200**
```json
{
  "purged_paths": ["config/secrets.yaml"],
  "purged_files": 1,
  "purged_notes": 3,
  "purged_reviewed_lines": 12,
  "exclusion_patterns": "*.log\n/config/secrets.yaml",
  "vacuumed": true,
  "files": []
}
```
- `files`: the rebuilt file list, same shape as `GET /api/sessions/:id/files`
- `vacuumed`: `false` if the reclaim was skipped or contended. The rows are gone
  either way, but the freed pages may still hold the old content on disk.

Broadcasts one `file_changed` with the purged root path. No `annotation_changed`
is sent — that event carries a per-note `kind`/`action`/`id` payload a bulk purge
cannot supply, and clients refresh off `file_changed`.

**Errors**
- `400` — missing `path`; a path that escapes the session root; or a path
  containing a newline, carriage return, or leading/trailing whitespace.
  `exclusion_patterns` is newline-separated and each line is stripped before
  being compiled, so such a path cannot be expressed as a pattern.
- `404` — session not found

**Not exposed over MCP.** Every MCP tool is additive; purge is irreversible, so
it stays human-only.

---

### GET /api/sessions/:id/files/:path

Get full line state + notes for a single file.
`:path` is the relative path within the session root, e.g. `src/main.py`.

If the file's on-disk mtime has changed since the last scan, reconciliation
runs before the response is built.

**Query parameters**
- `force=1` — bypass the large-file and binary guards described below

**Response 200**
```json
{
  "lines": [
    {
      "line_no": 1,
      "content": "import os",
      "line_hash": "abc123...",
      "context_hash": "def456...",
      "is_reviewed": false,
      "is_countable": true
    }
  ],
  "notes": [
    {
      "id": 7,
      "start_line": 3,
      "end_line": 5,
      "content": "Check this logic",
      "is_todo": false,
      "is_orphaned": false,
      "snapshot_text": "line3\nline4\nline5",
      "created_at": "2026-05-14T10:05:00Z",
      "issue_id": 12,
      "issue_severity": "P1"
    }
  ]
}
```

- `line_hash`: SHA-256 hex of the line's content string
- `context_hash`: SHA-256 hex of `prev_content + "\n" + curr_content + "\n" + next_content` (empty string for missing prev/next)
- `is_countable`: false for blank lines and comment-only lines (skip-comments is always on for now)
- `is_reviewed`: true if a matching `(line_hash, context_hash)` pair exists in `reviewed_lines` for this session+file.
  A non-countable line can be reviewed; it just does not contribute to `countable_lines` or to coverage
- `issue_id` / `issue_severity`: present when the note is attached to an issue; both `null` otherwise
- Notes include both live and orphaned notes for this file, ordered by `start_line`

**Errors**
- `400` — invalid path (escapes session root)
- `404` — session not found, or file not on disk (`{"error": "Session not found"}` /
  `{"error": "File not found"}`, no `reason`)
- `404` with a `reason` — the file is on disk but has no `files` row, for one of
  two reasons the caller must tell apart:
  ```json
  { "error": "File is not scanned yet — POST /api/sessions/1/rescan", "reason": "untracked" }
  { "error": "File is excluded from this session by exclusion_patterns or a .gitignore", "reason": "excluded" }
  ```
  - `untracked` — created since the last scan. One `POST /rescan` adopts it and
    the retried request succeeds.
  - `excluded` — no rescan will ever help. The fix is a human one: edit
    `exclusion_patterns` (`PATCH /sessions/:id`) or the `.gitignore`, then
    `POST /rescan?force=1`. Clients must not retry on this reason.

  The verdict is computed per path from `exclusion_patterns` plus the
  `.gitignore` chain, not from the session's cached scan, so it is correct even
  when the watcher never saw the file appear.
- `422` — file exceeds 1 MB or contains binary content; retry with `?force=1` to override
  ```json
  { "error": "File is too large", "reason": "large", "size": 2097152 }
  { "error": "Binary file detected", "reason": "binary" }
  ```

---

## Lines

### POST /api/sessions/:id/lines/mark

Mark or unmark a batch of lines as reviewed. Each request line is validated
against the **current** file content; stale entries are rejected rather than
silently written.

**Request body**
```json
{
  "file_path": "src/main.py",
  "lines": [
    {
      "line_hash": "abc123...",
      "context_hash": "def456...",
      "line_no": 1
    }
  ],
  "reviewed": true
}
```
- `file_path`: relative path within session root
- `lines`: array of line identity objects; each requires `line_hash`, `context_hash`, and `line_no`
- `reviewed`: `true` to mark, `false` to unmark

**Response 200**
```json
{
  "updated": 2,
  "accepted": [
    { "line_hash": "abc123...", "context_hash": "def456...", "line_no": 1 }
  ],
  "rejected": [
    {
      "line_hash": "ghi789...",
      "context_hash": "jkl012...",
      "line_no": 4,
      "reason": "stale content: line not found in current file"
    }
  ]
}
```
- `updated`: number of rows inserted (when `reviewed=true`) or deleted (when `reviewed=false`)
- `accepted` / `rejected`: per-line breakdown; `reason` explains why a line was skipped
- When marking (`reviewed=true`), a stale hash/context/line_no triple is rejected.
  A line whose `is_countable` is false (blank or comment-only) is accepted and
  stored, but its row is flagged non-countable and never enters the coverage
  ledger — so a client may submit a whole range without filtering it first.
  When unmarking, validation against current content is skipped;
  the matching `(line_hash, context_hash, line_no)` row is deleted. Each visible line is its own row, so two lines that happen to share the same `(line_hash, context_hash)` (e.g. consecutive identical lines or repeating blocks) can be marked and unmarked independently.
- When `reviewed=true` and at least one line was accepted, the file's checkpoint snapshot is refreshed.

**Errors**
- `400` — missing `file_path`/`lines`/`reviewed`, invalid path, or `lines` not an array
- `404` — session not found or file not on disk
- `409` — the file is excluded by the session's `exclusion_patterns`. The file
  still exists on disk, so this guard is what stops a stale client from
  resurrecting a purged file (both write paths upsert a `files` row).
- `500` — could not read file from disk

---

## Notes

### GET /api/sessions/:id/notes

Get all notes (live and orphaned) for the session, across all files, ordered
by `file_path` then `start_line`.

**Response 200**
```json
[
  {
    "id": 7,
    "file_path": "src/main.py",
    "start_line": 3,
    "end_line": 5,
    "content": "Check this logic",
    "is_todo": false,
    "is_orphaned": false,
    "snapshot_text": "line3\nline4\nline5",
    "created_at": "2026-05-14T10:05:00Z",
    "issue_id": null,
    "issue_severity": null
  }
]
```

- `issue_id` / `issue_severity`: present when the note is attached to an issue; both `null` otherwise

**Errors**
- `404` — session not found

---

### POST /api/sessions/:id/notes

Create a new note anchored to a line range, optionally attached to an issue.

**Request body**
```json
{
  "file_path": "src/main.py",
  "start_line": 3,
  "end_line": 5,
  "content": "Check this logic",
  "is_todo": false,
  "issue_id": 12
}
```
- `file_path`: relative path within session root
- `start_line`, `end_line`: 1-based integers; `start_line <= end_line`
- `content`: required unless `issue_id` is set (an issue-only attachment can omit content)
- `is_todo`: optional boolean (default `false`)
- `issue_id`: optional integer; if set, the issue must exist in this session

Backend derives `start_hash`, `end_hash`, and `snapshot_text` from the current
file content at creation time and refreshes the file's checkpoint snapshot.

**Response 201**
```json
{
  "id": 7,
  "file_path": "src/main.py",
  "start_line": 3,
  "end_line": 5,
  "content": "Check this logic",
  "is_todo": false,
  "is_orphaned": false,
  "snapshot_text": "line3\nline4\nline5",
  "created_at": "2026-05-14T10:05:00Z",
  "issue_id": 12,
  "issue_severity": "P1"
}
```

**Errors**
- `400` — missing/invalid fields, line range out of bounds, invalid path
- `404` — session not found, file not on disk, or referenced issue not found
- `409` — the file is excluded by the session's `exclusion_patterns`. The file
  still exists on disk, so this guard is what stops a stale client from
  resurrecting a purged file (both write paths upsert a `files` row).

---

### PATCH /api/sessions/:id/notes/:note_id

Update a note's `content` and/or `is_todo`. Other fields (line range, hashes,
snapshot, issue attachment) are not editable through this endpoint.

**Request body**
```json
{
  "content": "Updated text",
  "is_todo": true
}
```
At least one of `content` / `is_todo` must be present.

**Response 200**: the updated note row (same shape as the `POST /notes` response).

**Errors**
- `400` — empty content, or no fields to update
- `404` — session or note not found

---

### DELETE /api/sessions/:id/notes/:note_id

Permanently delete a note.

**Response 200**
```json
{ "deleted": true }
```

**Errors**
- `404` — session or note not found

---

### PUT /api/sessions/:id/notes/:note_id/issue

Attach a note to an issue (or move it to a different issue). To detach, use
PATCH on the issue or delete the note — there is no explicit detach endpoint.

**Request body**
```json
{ "issue_id": 12 }
```

**Response 200**
```json
{ "attached": true }
```

**Errors**
- `400` — missing `issue_id`
- `404` — note or issue not found in this session

---

## Issues

### GET /api/sessions/:id/issues

List issues for the session, newest first.

**Query params**
- `status`: optional, one of `open` / `resolved` / `dismissed`; filters by status
- `file_path`: optional, relative path within session root (e.g. `src/main.py`); when provided, only issues that have at least one live (non-orphaned) note in that file are returned

**Response 200**
```json
[
  {
    "id": 12,
    "session_id": 1,
    "title": "Path traversal in file handler",
    "description": "User input from `req.path` is joined with the upload dir without normalization…",
    "severity": "P1",
    "status": "open",
    "source": "agents:codeview-lens-trust-boundary",
    "closed_by": null,
    "created_at": "2026-05-14T10:15:00Z"
  }
]
```
- `description` is a free-form markdown string (empty by default). The UI renders it as sanitized HTML.
- `source`: free-form string identifying who opened the issue (`null` if not recorded). Convention: `"webui"`, `"editor:neovim"`, `"agents:<name>"`.
- `closed_by`: free-form string identifying who last resolved or dismissed the issue (`null` when open or not recorded). Cleared to `null` when the issue is reopened.

---

### GET /api/sessions/:id/issues/:issue_id

Fetch a single issue.

**Response 200**: same shape as a list entry above.

**Errors**
- `404` — issue not found in this session

---

### POST /api/sessions/:id/issues

Create a new issue, optionally attaching existing notes to it atomically.

**Request body**
```json
{
  "title": "Path traversal in file handler",
  "description": "User input from `req.path` is joined with the upload dir without normalization…",
  "severity": "P1",
  "note_ids": [7, 8]
}
```
- `title`: required, non-empty string
- `description`: optional string (default `""`); free-form markdown rendered as sanitized HTML in the UI
- `severity`: one of `P0` / `P1` / `P2` (default `P2`); `P0`=critical, `P1`=high, `P2`=medium
- `note_ids`: optional array of integers; all referenced notes must exist in this session
- `source`: optional string; who is opening the issue (e.g. `"webui"`, `"editor:neovim"`, `"agents:codeview-lens-concurrency"`)

**Response 201**: the created issue (same shape as a list entry, including `source` and `closed_by`).

**Errors**
- `400` — missing/invalid `title`, invalid `severity`, non-string `description`, malformed `note_ids`, or some `note_ids` do not exist (response includes `"missing": [...]`)
- `404` — session not found

---

### PATCH /api/sessions/:id/issues/:issue_id

Update one or more of `title`, `description`, `severity`, `status`.

**Request body**
```json
{
  "status": "resolved"
}
```
- `title`: optional, non-empty when provided
- `description`: optional string (markdown); pass `""` to clear
- `severity`: optional, one of `P0` / `P1` / `P2`
- `status`: optional, one of `open` / `resolved` / `dismissed`
- `actor`: optional string; who is making this status change. Stored as `closed_by` when `status` is `"resolved"` or `"dismissed"`; ignored otherwise. Cleared to `null` automatically when `status` is `"open"`.

**Response 200**: the updated issue (same shape as a list entry, including `source` and `closed_by`).

**Errors**
- `400` — invalid value, empty title, non-string description, or no fields to update
- `404` — issue not found

---

### DELETE /api/sessions/:id/issues/:issue_id

Permanently delete an issue. Attached notes are kept; their `issue_id` is
cleared to `NULL` so they survive as standalone notes.

**Response 200**
```json
{ "deleted": true }
```

**Errors**
- `404` — issue not found

---

### GET /api/sessions/:id/issues/:issue_id/notes

List all notes attached to a specific issue, ordered by `created_at` ascending, then by `id`. `created_at` is only second-granular, so the `id` tiebreak is what guarantees insertion order — clients that build ordered walkthroughs (an agent attaching one note per step) rely on it.

**Response 200**: array of note objects (same shape as `GET /notes`; every entry has the issue's `issue_id` and `issue_severity` populated).

---

## Coverage

### GET /api/sessions/:id/coverage

Aggregate coverage statistics for the session.

**Response 200**
```json
{
  "total_files": 12,
  "total_countable_lines": 980,
  "total_reviewed_lines": 412,
  "coverage": 0.4204
}
```
- Files whose `countable_lines` has not been computed, including files reported
  as `unreviewable`, are excluded from the totals
- `total_reviewed_lines` counts only marks on countable lines, and clamps each file's reviewed count to its `countable_lines` so stale rows can't push coverage above 100%
- `coverage` is `total_reviewed_lines / total_countable_lines`; `0` if denominator is zero

**Errors**
- `404` — session not found

---

## Symbol navigation (LSP)

Off unless the server was started with `--lsp`. When enabled, auditview acts as
an LSP *client*, spawning language servers found on `PATH` as subprocesses — one
per (server, resolved project root). A missing binary is reported, never fatal.

Positions on these routes follow the rest of this document: `line` is 1-based.
`character` is a 0-based offset in **UTF-16 code units**, which is what a
browser's DOM text-node offset already is — clients must not convert it to a
byte offset.

Because auditview never edits files, documents are always exactly the bytes on
disk; there is no document-sync protocol for clients to participate in.

### POST /api/sessions/:id/lsp/definition

Resolve the definition of the symbol at a position.

**Request body**
```json
{ "file_path": "ui/src/components/LineRow.vue", "line": 29, "character": 7 }
```
- `file_path`: relative path within the session root
- `line`: 1-based line number
- `character`: 0-based UTF-16 offset within that line

**Response 200**
```json
{
  "provider": "vtsls",
  "reason": null,
  "in_root": [
    { "file_path": "ui/src/components/LineGutter.vue", "line": 1, "character": 0 }
  ],
  "out_of_root": [
    { "path": "/tools/lsp/node_modules/typescript/lib/lib.es5.d.ts", "line": 1550, "character": 4 }
  ]
}
```
- `provider`: the server that answered, or `null` when none did
- `reason`: `null` on success; `"disabled"` when the server was started without
  `--lsp`; `"no_provider"` when no configured server matches the file, with the
  unmatched extension in `detail`. Both are `200` with empty target lists — an
  unsupported language is information, not an error
- `in_root`: targets inside the session root, ordered as the server returned
  them, with duplicates removed and paths matching the session's
  `exclusion_patterns` dropped
- `out_of_root`: targets outside the session root — a dependency, a stdlib, a
  toolchain's own type definitions. Common rather than exceptional. Returning a
  path here is what makes it readable via `/lsp/preview`; nothing else does
- Non-`file:` URIs (a language server's virtual documents) are discarded

**Errors**
- `400` — missing/invalid `file_path`, `line` or `character`, or a path escaping the session root
- `404` — session not found, or the file is not on disk
- `409` — the file is excluded by the session's `exclusion_patterns`
- `503` — the language server timed out, crashed, or returned an error. `provider` names it

---

### GET /api/sessions/:id/lsp/status

What the LSP layer is actually doing, so a client can explain an empty result
rather than presenting it as a failure.

**Response 200**
```json
{
  "enabled": true,
  "servers": [
    {
      "name": "vtsls",
      "command": "vtsls",
      "available": true,
      "match": ["**/*.vue", "**/*.js"],
      "instances": [
        { "root": "/home/user/myproject/ui", "state": "ready", "detail": null,
          "definition_provider": true }
      ]
    }
  ]
}
```
- `enabled`: `false` (with `servers: []`) when started without `--lsp`
- `available`: whether the binary was found on `PATH`
- `instances`: currently running processes; empty until a matching file is queried
- `state`: `spawning` | `warming` | `ready` | `missing` | `crashed` | `stopped`
- Idle instances are shut down after ten minutes and disappear from this list

**Errors**
- `404` — session not found

---

### GET /api/sessions/:id/lsp/preview

Read a window of a file **outside** the session root, so a definition in a
dependency can be read without leaving the tool.

Query parameters: `path` (absolute), and optionally `line` to centre the window.

**Response 200**
```json
{
  "path": "/tools/lsp/node_modules/typescript/lib/lib.es5.d.ts",
  "start_line": 1510,
  "total_lines": 4023,
  "reviewable": false,
  "lines": [ { "line_no": 1510, "content": "interface Array<T> {" } ]
}
```
- Deliberately carries **no** `line_hash`, `context_hash`, `is_reviewed` or
  `is_countable`, and writes nothing. An out-of-root file must not be markable,
  or review coverage stops meaning "a human read this project"
- `reviewable` is always `false`; it exists so a client can render the
  distinction rather than infer it from absent fields
- Serves **only** paths a definition query in this session already returned.
  auditview ships no authentication, so an endpoint that read any absolute path
  given to it would be an arbitrary-file reader for anyone who can reach the port

**Errors**
- `400` — `path` missing
- `403` — the path is not one this session's definition results produced
- `404` — session not found, or the file is no longer on disk
- `422` — binary (`reason: "binary"`) or too large (`reason: "large"`, with `size`)
- `500` — the file could not be read

---

## Config

The config endpoints expose process-level state shared across sessions, plus
the "active" MCP session that drives the MCP server's tool context.

### GET /api/config

**Response 200**
```json
{
  "root_path": "/home/user/myproject",
  "db_path": "/home/user/myproject/.auditview.db",
  "version": "0.1.3",
  "commit": "59a7348aa17b5a763610fd9b443d5d90617761ff",
  "mcp_session": {
    "id": 1,
    "label": "First pass",
    "root_path": "/home/user/myproject"
  }
}
```
- `mcp_session`: `null` if no session has been pinned for MCP use
- `version`: the installed distribution's version. `"0.0.0+unknown"` when running
  from a source tree that was never installed
- `commit`: full 40-character git commit the running build was made from, stamped
  into the package at build time. `null` when the build carried no stamp — a
  `git archive` tarball or a vendored copy, for instance. Slice it yourself for
  display; the server does not shorten it

---

### PUT /api/config/mcp-session

Pin a session as the active MCP context. The chosen session is what
`check_context` returns to MCP clients.

**Request body**
```json
{ "session_id": 1 }
```

**Response 200**
```json
{
  "mcp_session": {
    "id": 1,
    "label": "First pass",
    "root_path": "/home/user/myproject"
  }
}
```

**Errors**
- `400` — missing or non-integer `session_id`
- `404` — session not found

---

### DELETE /api/config/mcp-session

Clear the pinned MCP session.

**Response 200**
```json
{ "mcp_session": null }
```

---

### POST /api/config/resolve-path

Resolve an absolute or relative path against the active MCP session's
`root_path`. Used by editor integrations to normalize paths they hand to the
API.

**Request body**
```json
{ "path": "/home/user/myproject/src/main.py" }
```

**Response 200**
```json
{
  "rel_path": "src/main.py",
  "abs_path": "/home/user/myproject/src/main.py"
}
```

**Errors**
- `400` — no MCP session active, missing `path`, or path escapes the session root

---

## Events (SSE)

### GET /api/sessions/:id/events

Server-Sent Events stream. Sends an immediate heartbeat on connect and a
heartbeat every 15 s while idle.

**Response**: `Content-Type: text/event-stream`, chunked transfer

**Event types**

```
event: heartbeat
data: {}

event: file_changed
data: {"rel_path": "src/main.py"}

event: annotation_changed
data: {"kind": "note", "action": "create", "note": {<full note row>}}

event: annotation_changed
data: {"kind": "note", "action": "update", "note": {<full note row>}}

event: annotation_changed
data: {"kind": "note", "action": "delete", "id": 42, "file_path": "src/main.py"}

event: annotation_changed
data: {"kind": "issue", "action": "create", "issue": {<full issue row>}}

event: annotation_changed
data: {"kind": "issue", "action": "update", "issue": {<full issue row>}}

event: annotation_changed
data: {"kind": "issue", "action": "delete", "id": 12}

event: shutdown
data: {}
```

- `heartbeat`: keep-alive; one is sent immediately on connect, then every 15 s
- `file_changed`: emitted after reconciliation completes for a file; clients should re-fetch `/api/sessions/:id/files/:path`
  - `rel_path: null` means the *tracked set* moved rather than one file's
    content: a path with no `files` row was created, deleted or moved (a new
    file, most often), or a forced rescan changed what the session tracks. There
    is nothing to re-fetch per file — call `POST /api/sessions/:id/rescan`
    (unforced is enough; the server has already invalidated its cached scan).
    Without this event a new file stays invisible until some unrelated tracked
    file happens to change.
- `annotation_changed`: emitted after a note or issue is created/updated/deleted
  - `kind`: `"note"` or `"issue"`
  - `action`: `"create"`, `"update"`, or `"delete"`
  - `note` / `issue`: the full row (same shape as the corresponding REST response) on create and update. Consumers apply the row to local state directly — no refetch is required.
  - `id` + `file_path` (for `note/delete`) or `id` (for `issue/delete`): just enough to remove the record from local state.
  - Cascades emit one event per affected record (no `id: null` placeholders):
    - `POST /issues` with `note_ids`: one `issue/create` followed by one `note/update` per attached note (each carrying the note's full new row, including the new `issue_id` and `issue_severity`).
    - `DELETE /issues/:id`: one `issue/delete` followed by one `note/update` per note whose `issue_id` was cleared.
    - `PATCH /issues/:id` with `severity` change: one `issue/update` followed by one `note/update` per attached note (so colour overlays in CodeView refresh).
    - `PUT /notes/:id/issue`: one `note/update` with the note's new row.
  - Clients should debounce reactions (250 ms trailing edge is suggested) to coalesce bursts (e.g. bulk creation via MCP).
- `shutdown`: emitted once when the server begins graceful shutdown; the stream terminates after this event

**Errors**
- `404` — session not found (returned before the stream is opened)

---

## MCP

`/mcp` serves the auditview MCP server over Streamable HTTP (JSON-RPC 2.0).
This is a separate ASGI handler mounted at the path prefix `/mcp`, not part of
the `/api` blueprint set. Tool implementations call the REST endpoints above
internally through Quart's test client. See `auditview/api/mcp.py` for the
tool catalog (`check_context`, `list_issues`, `list_notes`, `create_note`,
`get_issue`, `create_issue`, `update_issue`).

---

## Common Conventions

- All timestamps are ISO-8601 UTC strings: `"2026-05-14T10:00:00Z"`
- `:id`, `:note_id`, `:issue_id` are integers
- `:path` in file endpoints is a URL-encoded relative path; forward slashes in the path are part of the URL segment (Quart `<path:fpath>` capture)
- Successful mutations return the created/updated resource or a minimal acknowledgement object (`{"deleted": true}`, `{"attached": true}`)
- Unknown session `:id` always returns `404`
- Paths that escape the session root return `400 "Invalid path"`
