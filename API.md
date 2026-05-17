# auditview — API Contract

All endpoints are under `/api`. Request/response bodies are JSON unless noted.
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
- `400` — missing/invalid fields

---

## Files

### GET /api/sessions/:id/files

List all tracked files with per-file coverage and counts.

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
    "todos_count": 1
  }
]
```
- `coverage` is `reviewed_lines / countable_lines`; `0` if `countable_lines == 0`
- `status` is one of `"empty"` (no countable lines), `"not_viewed"` (none reviewed),
  `"partial"` (some reviewed), `"reviewed"` (all countable lines reviewed)
- `reviewed_lines` is clamped to `countable_lines` so stale rows can't push it above 100%
- `notes_count` / `todos_count` count only **live** (non-orphaned) notes
- Files are sorted by `rel_path` ascending

**Errors**
- `404` — session not found

---

### POST /api/sessions/:id/rescan

Re-scan the session root: insert newly-discovered files, drop files that no
longer exist (orphaning their notes and removing their reviewed-line rows),
and backfill `countable_lines` for any new entries. Returns the same shape as
`GET /api/sessions/:id/files`.

**Request body**: empty (`{}` or no body)

**Response 200**: same shape as `GET /api/sessions/:id/files`.

**Errors**
- `404` — session not found

---

### GET /api/sessions/:id/files/:path

Get full line state + notes for a single file.
`:path` is the relative path within the session root, e.g. `src/main.py`.

If the file's on-disk mtime has changed since the last scan, reconciliation
runs before the response is built.

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
- `is_reviewed`: true if a matching `(line_hash, context_hash)` pair exists in `reviewed_lines` for this session+file
- `issue_id` / `issue_severity`: present when the note is attached to an issue; both `null` otherwise
- Notes include both live and orphaned notes for this file, ordered by `start_line`

**Errors**
- `400` — invalid path (escapes session root)
- `404` — session not found, file not on disk, or file not tracked in this session (caller should hit `GET /files` or `POST /rescan` first)

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
- When marking (`reviewed=true`), a stale hash/context/line_no triple is rejected. When unmarking, validation against current content is skipped (the row is deleted by hash regardless).
- When `reviewed=true` and at least one line was accepted, the file's checkpoint snapshot is refreshed.

**Errors**
- `400` — missing `file_path`/`lines`/`reviewed`, invalid path, or `lines` not an array
- `404` — session not found or file not on disk
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
    "issue_id": null
  }
]
```

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
  "issue_id": 12
}
```

**Errors**
- `400` — missing/invalid fields, line range out of bounds, invalid path
- `404` — session not found, file not on disk, or referenced issue not found

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
    "created_at": "2026-05-14T10:15:00Z"
  }
]
```
- `description` is a free-form markdown string (empty by default). The UI renders it as sanitized HTML.

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

**Response 201**: the created issue (same shape as a list entry).

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

**Response 200**: the updated issue.

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

List all notes attached to a specific issue, ordered by `created_at` ascending.

**Response 200**: array of note objects (same shape as `GET /notes`, without `issue_id`).

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
- Files whose `countable_lines` has not yet been computed are excluded from the totals
- `total_reviewed_lines` clamps each file's reviewed count to its `countable_lines` so stale rows can't push coverage above 100%
- `coverage` is `total_reviewed_lines / total_countable_lines`; `0` if denominator is zero

**Errors**
- `404` — session not found

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
  "mcp_session": {
    "id": 1,
    "label": "First pass",
    "root_path": "/home/user/myproject"
  }
}
```
- `mcp_session`: `null` if no session has been pinned for MCP use

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
data: {"kind": "note", "action": "create", "id": 42, "file_path": "src/main.py", "is_todo": false}

event: shutdown
data: {}
```

- `heartbeat`: keep-alive; one is sent immediately on connect, then every 15 s
- `file_changed`: emitted after reconciliation completes for a file; clients should re-fetch `/api/sessions/:id/files/:path`
- `annotation_changed`: emitted after a note or issue is created/updated/deleted
  - `kind`: `"note"` or `"issue"`
  - `action`: `"create"`, `"update"`, or `"delete"`
  - `id`: integer id of the affected record, or `null` for cascade events that touch many records
  - `file_path`: notes only — the file the note belongs to; `null` for cascade events (issue create/delete touching multiple notes, severity update affecting all attached notes) where consumers should reload conservatively
  - `is_todo`: notes only, optional — present on create/update
  - Cascades: `create_issue` with `note_ids` emits one `issue/create` followed by one `note/update` with `id: null, file_path: null`. `delete_issue` emits one `issue/delete` followed by one `note/update` with `id: null, file_path: null` if any notes had their `issue_id` cleared. `PATCH issue` with `severity` change emits one `issue/update` followed by one `note/update` cascade (so coloured-line overlays in CodeView refresh).
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
