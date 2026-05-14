# auditview — API Contract

All endpoints are under `/api`. Request/response bodies are JSON unless noted.
Errors return `{"error": "<message>"}` with an appropriate HTTP status.

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

Create a new session.

**Request body**
```json
{
  "label": "First pass",
  "root_path": "/home/user/myproject",
  "exclusion_patterns": "*.log\nbuild/"
}
```
- `label`: required, non-empty string
- `root_path`: required, absolute path that must exist on disk
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
- `400` — missing/invalid fields, root_path does not exist

---

## Files

### GET /api/sessions/:id/files

List all tracked files with per-file coverage.

**Response 200**
```json
[
  {
    "rel_path": "src/main.py",
    "countable_lines": 120,
    "reviewed_lines": 45,
    "coverage": 0.375
  }
]
```
- `coverage` is `reviewed_lines / countable_lines`; `0` if `countable_lines == 0`
- Files are sorted by `rel_path` ascending

**Errors**
- `404` — session not found

---

### GET /api/sessions/:id/files/:path

Get full line state + notes for a single file.
`:path` is the relative path within the session root, e.g. `src/main.py`.

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
      "created_at": "2026-05-14T10:05:00Z"
    }
  ]
}
```

- `line_hash`: SHA-256 hex of the line's content string
- `context_hash`: SHA-256 hex of `prev_content + "\n" + curr_content + "\n" + next_content` (empty string for missing prev/next)
- `is_countable`: false for blank lines; false for comment-only lines when skip_comments mode is on (skip_comments follows the session default — always `true` for now; a future toggle may override this per-request via a query param `?skip_comments=0`)
- `is_reviewed`: true if a matching `(line_hash, context_hash)` pair exists in `reviewed_lines` for this session+file
- Notes include both live and orphaned notes for this file

**Errors**
- `404` — session not found, or file not tracked in this session

---

## Lines

### POST /api/sessions/:id/lines/mark

Mark or unmark a batch of lines as reviewed.

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
- `lines`: array of line identity objects
- `reviewed`: `true` to mark, `false` to unmark

**Response 200**
```json
{ "updated": 3 }
```
- `updated`: number of rows inserted or deleted

**Errors**
- `400` — missing fields
- `404` — session not found

---

## Notes

### GET /api/sessions/:id/notes

Get all notes (live and orphaned) for the session, across all files.

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
    "created_at": "2026-05-14T10:05:00Z"
  }
]
```

**Errors**
- `404` — session not found

---

### POST /api/sessions/:id/notes

Create a new note anchored to a line range.

**Request body**
```json
{
  "file_path": "src/main.py",
  "start_line": 3,
  "end_line": 5,
  "content": "Check this logic",
  "is_todo": false
}
```
- `file_path`: relative path within session root
- `start_line`, `end_line`: 1-based line numbers; `start_line <= end_line`
- `content`: non-empty string
- `is_todo`: boolean

Backend derives `start_hash`, `end_hash`, and `snapshot_text` from the current file content at creation time.

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
  "created_at": "2026-05-14T10:05:00Z"
}
```

**Errors**
- `400` — missing/invalid fields, line range out of bounds
- `404` — session or file not found

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
  "coverage": 0.4204,
  "supports_checkpoints": true
}
```
- `coverage` is `total_reviewed_lines / total_countable_lines`; `0` if denominator is zero
- `supports_checkpoints`: `true` if apsw is available and session extension works

**Errors**
- `404` — session not found

---

## Checkpoints

### GET /api/sessions/:id/checkpoints

List all checkpoints for the session, newest first.

**Response 200**
```json
[
  {
    "id": 42,
    "label": "reconcile:src/main.py",
    "created_at": "2026-05-14T10:10:00Z"
  }
]
```

**Errors**
- `404` — session not found

---

### POST /api/sessions/:id/checkpoints/:cid/revert

Revert to the state captured in checkpoint `cid` by applying the inverted changeset.

**Request body**: empty (`{}` or no body)

**Response 200**
```json
{ "reverted": true }
```

**Errors**
- `404` — session or checkpoint not found
- `409` — apsw not available (checkpoints not supported)
- `500` — changeset application failed

---

## Events (SSE)

### GET /api/sessions/:id/events

Server-Sent Events stream. Keep-alive with periodic heartbeats.

**Response**: `Content-Type: text/event-stream`, chunked transfer

**Event types**

```
event: heartbeat
data: {}

event: file_changed
data: {"rel_path": "src/main.py"}
```

- `heartbeat`: sent every 15 s to keep the connection alive
- `file_changed`: sent after reconciliation completes for a file; frontend should re-fetch `/api/sessions/:id/files/:path` for the named `rel_path`

**Errors**
- `404` — session not found (returned before the stream is opened)

---

## Common Conventions

- All timestamps are ISO-8601 UTC strings: `"2026-05-14T10:00:00Z"`
- `:id` and `:cid` are integers
- `:path` in file endpoints is a URL-encoded relative path; forward slashes in the path are part of the URL segment (Flask `<path:path>` capture)
- Successful mutations return the created/updated resource or a minimal acknowledgement object
- Unknown session `:id` always returns `404`
