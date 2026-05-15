import os
from flask import Blueprint, request, jsonify, current_app
from auditview.db.connection import open_db
from auditview.core.hashing import line_hash, context_hash
from auditview.core.coverage import is_countable_line
from auditview.core.reconciler import reconcile_file
from auditview.api.util import safe_path

bp = Blueprint("mcp", __name__)

_TOOLS = [
    {
        "name": "list_files",
        "description": "List all files in the active audit session with their review coverage stats and note/todo counts.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_file",
        "description": "Read a file's content with line numbers from the active audit session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file within the session root"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_notes",
        "description": "List all audit notes and todos in the session, optionally filtered by file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Filter notes to this relative file path"},
            },
        },
    },
    {
        "name": "create_note",
        "description": "Create an audit note or todo on a specific range of lines in a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative file path within the session root"},
                "start_line": {"type": "integer", "description": "First line number (1-indexed)"},
                "end_line": {"type": "integer", "description": "Last line number (1-indexed, inclusive)"},
                "content": {"type": "string", "description": "The note text"},
                "is_todo": {"type": "boolean", "description": "Mark as a todo/action item (default: false)"},
                "issue_id": {"type": "integer", "description": "Attach to an existing issue by ID"},
            },
            "required": ["file_path", "start_line", "end_line", "content"],
        },
    },
    {
        "name": "list_issues",
        "description": "List issues in the active audit session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved", "dismissed"],
                    "description": "Filter by status (omit for all)",
                },
            },
        },
    },
    {
        "name": "create_issue",
        "description": "Create a new issue in the active audit session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title"},
                "severity": {
                    "type": "string",
                    "enum": ["P0", "P1", "P2"],
                    "description": "P0=critical, P1=high, P2=medium",
                },
            },
            "required": ["title", "severity"],
        },
    },
    {
        "name": "update_issue",
        "description": "Update an existing issue's title, severity, or status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "integer", "description": "The issue ID to update"},
                "title": {"type": "string"},
                "severity": {"type": "string", "enum": ["P0", "P1", "P2"]},
                "status": {"type": "string", "enum": ["open", "resolved", "dismissed"]},
            },
            "required": ["issue_id"],
        },
    },
]


def _ok(req_id, result):
    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})


def _err(req_id, code, message):
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _tool_error(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _tool_ok(text):
    return {"content": [{"type": "text", "text": str(text)}]}


def _get_mcp_session(conn):
    is_apsw = getattr(conn, '_is_apsw', False)
    row = conn.cursor().execute(
        "SELECT value FROM app_config WHERE key = 'mcp_session_id'"
    ).fetchone()
    if not row:
        return None
    session_id = int(row[0] if is_apsw else row["value"])
    srow = conn.cursor().execute(
        "SELECT id, label, root_path, exclusion_patterns FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not srow:
        return None
    if is_apsw:
        return {"id": srow[0], "label": srow[1], "root_path": srow[2], "exclusion_patterns": srow[3]}
    return {"id": srow["id"], "label": srow["label"], "root_path": srow["root_path"], "exclusion_patterns": srow["exclusion_patterns"]}


def _tool_list_files(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]
    root_path = session["root_path"]
    exclusion_patterns = session["exclusion_patterns"]

    rel_paths = current_app.watcher.get_scan(session_id, root_path, exclusion_patterns)
    rel_path_set = set(rel_paths)

    for rp in rel_paths:
        cur.execute(
            "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (session_id, rp),
        )

    file_rows = cur.execute(
        "SELECT rel_path, countable_lines FROM files WHERE session_id = ?", (session_id,)
    ).fetchall()
    countable_map = {}
    uncached = []
    for r in file_rows:
        rp = r[0] if is_apsw else r["rel_path"]
        cl = r[1] if is_apsw else r["countable_lines"]
        countable_map[rp] = cl
        if cl is None and rp in rel_path_set:
            uncached.append(rp)

    for rp in uncached:
        ext = os.path.splitext(rp)[1].lower()
        full_path = os.path.join(root_path, rp)
        countable = 0
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    countable = sum(1 for line in f.read().splitlines() if is_countable_line(line, ext))
            except OSError:
                pass
        cur.execute(
            "UPDATE files SET countable_lines = ? WHERE session_id = ? AND rel_path = ?",
            (countable, session_id, rp),
        )
        countable_map[rp] = countable

    reviewed_rows = cur.execute(
        "SELECT file_path, COUNT(*) FROM reviewed_lines WHERE session_id = ? GROUP BY file_path",
        (session_id,),
    ).fetchall()
    reviewed_map = {(r[0] if is_apsw else r["file_path"]): (r[1] if is_apsw else r[1]) for r in reviewed_rows}

    note_rows = cur.execute(
        "SELECT file_path, "
        "SUM(CASE WHEN is_todo=0 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN is_todo=1 THEN 1 ELSE 0 END) "
        "FROM notes WHERE session_id = ? AND is_orphaned=0 GROUP BY file_path",
        (session_id,),
    ).fetchall()
    notes_map = {(r[0] if is_apsw else r["file_path"]): (
        (r[1] if is_apsw else r[1]) or 0,
        (r[2] if is_apsw else r[2]) or 0,
    ) for r in note_rows}

    lines = [f"Session: {session['label']} ({len(rel_paths)} files)\n"]
    lines.append("path | reviewed/countable | notes | todos")
    lines.append("-" * 60)
    for rp in rel_paths:
        countable = countable_map.get(rp) or 0
        reviewed = reviewed_map.get(rp, 0)
        coverage = f"{reviewed}/{countable}" if countable > 0 else "empty"
        notes_c, todos_c = notes_map.get(rp, (0, 0))
        lines.append(f"{rp} | {coverage} | {notes_c} | {todos_c}")

    return _tool_ok("\n".join(lines))


def _tool_read_file(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]
    root_path = session["root_path"]

    path = (args.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")

    full_path = safe_path(root_path, path)
    if full_path is None:
        raise ValueError("invalid path")
    if not os.path.isfile(full_path):
        raise ValueError(f"file not found: {path}")

    cur.execute(
        "INSERT INTO files (session_id, rel_path) VALUES (?, ?) ON CONFLICT DO NOTHING",
        (session_id, path),
    )

    file_row = cur.execute(
        "SELECT last_mtime FROM files WHERE session_id = ? AND rel_path = ?",
        (session_id, path),
    ).fetchone()
    current_mtime = os.path.getmtime(full_path)
    stored_mtime = (file_row[0] if is_apsw else file_row["last_mtime"]) if file_row else None
    if stored_mtime is None or abs(stored_mtime - current_mtime) > 1e-6:
        reconcile_file(conn, session_id, path, root_path)

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        file_lines = f.read().splitlines()

    output = [f"File: {path} ({len(file_lines)} lines)\n"]
    for i, line in enumerate(file_lines):
        output.append(f"{i + 1:5d} | {line}")

    return _tool_ok("\n".join(output))


def _tool_list_notes(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]

    file_path = (args.get("file_path") or "").strip()
    if file_path:
        rows = cur.execute(
            "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, created_at, issue_id "
            "FROM notes WHERE session_id = ? AND file_path = ? ORDER BY start_line",
            (session_id, file_path),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, file_path, start_line, end_line, content, is_todo, is_orphaned, created_at, issue_id "
            "FROM notes WHERE session_id = ? ORDER BY file_path, start_line",
            (session_id,),
        ).fetchall()

    if not rows:
        return _tool_ok("No notes found.")

    output = []
    for r in rows:
        if is_apsw:
            nid, fp, sl, el, content, is_todo, is_orphaned, created_at, issue_id = r[0], r[1], r[2], r[3], r[4], bool(r[5]), bool(r[6]), r[7], r[8]
        else:
            nid, fp, sl, el, content, is_todo, is_orphaned, created_at, issue_id = r["id"], r["file_path"], r["start_line"], r["end_line"], r["content"], bool(r["is_todo"]), bool(r["is_orphaned"]), r["created_at"], r["issue_id"]

        kind = "TODO" if is_todo else "NOTE"
        tags = ""
        if is_orphaned:
            tags += " [ORPHANED]"
        if issue_id:
            tags += f" [issue:#{issue_id}]"
        output.append(f"[#{nid}] {kind}{tags}  {fp}:{sl}-{el}")
        output.append(f"  {content}")
        output.append("")

    return _tool_ok("\n".join(output))


def _tool_create_note(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]
    root_path = session["root_path"]

    file_path = (args.get("file_path") or "").strip()
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    content = (args.get("content") or "").strip()
    is_todo = bool(args.get("is_todo", False))
    issue_id = args.get("issue_id")

    if not file_path:
        raise ValueError("file_path is required")
    if not content:
        raise ValueError("content is required")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        raise ValueError("start_line and end_line must be integers")
    if start_line < 1 or start_line > end_line:
        raise ValueError("invalid line range")

    full_path = safe_path(root_path, file_path)
    if full_path is None:
        raise ValueError("invalid path")
    if not os.path.isfile(full_path):
        raise ValueError(f"file not found: {file_path}")

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        file_lines = f.read().splitlines()

    if start_line > len(file_lines) or end_line > len(file_lines):
        raise ValueError(f"line range out of bounds (file has {len(file_lines)} lines)")

    start_idx = start_line - 1
    end_idx = end_line - 1
    start_hash = line_hash(file_lines[start_idx])
    end_hash = line_hash(file_lines[end_idx])
    snapshot_text = "\n".join(file_lines[start_idx:end_idx + 1])

    if issue_id is not None:
        issue_row = cur.execute(
            "SELECT id FROM issues WHERE id = ? AND session_id = ?", (issue_id, session_id)
        ).fetchone()
        if issue_row is None:
            raise ValueError(f"issue #{issue_id} not found")

    cur.execute(
        "INSERT INTO notes (session_id, file_path, start_line, end_line, start_hash, end_hash, snapshot_text, content, is_todo, issue_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, file_path, start_line, end_line, start_hash, end_hash, snapshot_text, content, int(is_todo), issue_id),
    )
    new_id = conn.last_insert_rowid() if is_apsw else cur.lastrowid
    kind = "todo" if is_todo else "note"
    return _tool_ok(f"Created {kind} #{new_id} on {file_path}:{start_line}-{end_line}")


def _tool_list_issues(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]

    status = args.get("status")
    if status and status not in ("open", "resolved", "dismissed"):
        raise ValueError("status must be open, resolved, or dismissed")

    if status:
        rows = cur.execute(
            "SELECT id, title, severity, status, created_at FROM issues "
            "WHERE session_id = ? AND status = ? ORDER BY severity, created_at",
            (session_id, status),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, title, severity, status, created_at FROM issues "
            "WHERE session_id = ? ORDER BY severity, created_at",
            (session_id,),
        ).fetchall()

    if not rows:
        return _tool_ok("No issues found.")

    output = []
    for r in rows:
        if is_apsw:
            iid, title, severity, istatus = r[0], r[1], r[2], r[3]
        else:
            iid, title, severity, istatus = r["id"], r["title"], r["severity"], r["status"]
        output.append(f"[#{iid}] [{severity}] [{istatus}] {title}")

    return _tool_ok("\n".join(output))


def _tool_create_issue(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]

    title = (args.get("title") or "").strip()
    severity = (args.get("severity") or "").strip()
    if not title:
        raise ValueError("title is required")
    if severity not in ("P0", "P1", "P2"):
        raise ValueError("severity must be P0, P1, or P2")

    cur.execute(
        "INSERT INTO issues (session_id, title, severity) VALUES (?, ?, ?)",
        (session_id, title, severity),
    )
    new_id = conn.last_insert_rowid() if is_apsw else cur.lastrowid
    return _tool_ok(f"Created issue #{new_id}: [{severity}] {title}")


def _tool_update_issue(args, conn, session):
    is_apsw = getattr(conn, '_is_apsw', False)
    cur = conn.cursor()
    session_id = session["id"]

    issue_id = args.get("issue_id")
    if not isinstance(issue_id, int):
        raise ValueError("issue_id must be an integer")

    row = cur.execute(
        "SELECT id FROM issues WHERE id = ? AND session_id = ?", (issue_id, session_id)
    ).fetchone()
    if row is None:
        raise ValueError(f"issue #{issue_id} not found")

    updates = {}
    if args.get("title"):
        updates["title"] = args["title"].strip()
    if "severity" in args:
        if args["severity"] not in ("P0", "P1", "P2"):
            raise ValueError("severity must be P0, P1, or P2")
        updates["severity"] = args["severity"]
    if "status" in args:
        if args["status"] not in ("open", "resolved", "dismissed"):
            raise ValueError("status must be open, resolved, or dismissed")
        updates["status"] = args["status"]

    if not updates:
        raise ValueError("nothing to update — provide title, severity, and/or status")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    cur.execute(f"UPDATE issues SET {set_clause} WHERE id = ?", (*updates.values(), issue_id))
    changes = ", ".join(f"{k}={v}" for k, v in updates.items())
    return _tool_ok(f"Updated issue #{issue_id}: {changes}")


_TOOL_HANDLERS = {
    "list_files": _tool_list_files,
    "read_file": _tool_read_file,
    "list_notes": _tool_list_notes,
    "create_note": _tool_create_note,
    "list_issues": _tool_list_issues,
    "create_issue": _tool_create_issue,
    "update_issue": _tool_update_issue,
}


@bp.route("/mcp", methods=["POST"])
def mcp_endpoint():
    body = request.get_json(force=True, silent=True)
    if not body:
        return _err(None, -32700, "Parse error"), 400

    method = body.get("method", "")
    params = body.get("params") or {}

    # Notifications have no id and require no response
    if "id" not in body:
        return "", 202

    req_id = body.get("id")

    if method == "initialize":
        client_version = params.get("protocolVersion", "2024-11-05")
        version = client_version if client_version in ("2024-11-05", "2025-03-26") else "2024-11-05"
        return _ok(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "auditview", "version": "1.0.0"},
        })

    if method == "ping":
        return _ok(req_id, {})

    if method == "tools/list":
        return _ok(req_id, {"tools": _TOOLS})

    if method == "tools/call":
        name = (params.get("name") or "").strip()
        args = params.get("arguments") or {}

        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _ok(req_id, _tool_error(f"Unknown tool: {name}"))

        conn = open_db(current_app.config["DB_PATH"])
        session = _get_mcp_session(conn)
        if session is None:
            return _ok(req_id, _tool_error(
                "No MCP session is active. A human must activate a session in the web UI first."
            ))

        try:
            result = handler(args, conn, session)
            return _ok(req_id, result)
        except ValueError as e:
            return _ok(req_id, _tool_error(str(e)))
        except Exception as e:
            return _ok(req_id, _tool_error(f"Internal error: {e}"))

    return _err(req_id, -32601, f"Method not found: {method}")
