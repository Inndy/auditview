from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("mcp", __name__)

_TOOLS = [
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


def _api(method, path, data=None):
    client = current_app.test_client()
    fn = getattr(client, method)
    return fn(path, json=data) if data is not None else fn(path)


def _get_mcp_session():
    resp = _api("get", "/config")
    if resp.status_code != 200:
        return None
    return resp.get_json().get("mcp_session")


def _tool_list_notes(args, session):
    resp = _api("get", f"/sessions/{session['id']}/notes")
    if resp.status_code != 200:
        return _tool_error(resp.get_json().get("error", "failed to list notes"))
    notes = resp.get_json()

    file_path = (args.get("file_path") or "").strip()
    if file_path:
        notes = [n for n in notes if n["file_path"] == file_path]

    if not notes:
        return _tool_ok("No notes found.")

    output = []
    for n in notes:
        kind = "TODO" if n["is_todo"] else "NOTE"
        tags = ""
        if n["is_orphaned"]:
            tags += " [ORPHANED]"
        if n.get("issue_id"):
            tags += f" [issue:#{n['issue_id']}]"
        output.append(f"[#{n['id']}] {kind}{tags}  {n['file_path']}:{n['start_line']}-{n['end_line']}")
        output.append(f"  {n['content']}")
        output.append("")
    return _tool_ok("\n".join(output))


def _tool_create_note(args, session):
    resp = _api("post", f"/sessions/{session['id']}/notes", args)
    data = resp.get_json()
    if resp.status_code not in (200, 201):
        return _tool_error(data.get("error", "failed to create note"))
    kind = "todo" if data["is_todo"] else "note"
    return _tool_ok(f"Created {kind} #{data['id']} on {data['file_path']}:{data['start_line']}-{data['end_line']}")


def _tool_list_issues(args, session):
    url = f"/sessions/{session['id']}/issues"
    if args.get("status"):
        url += f"?status={args['status']}"
    resp = _api("get", url)
    if resp.status_code != 200:
        return _tool_error(resp.get_json().get("error", "failed to list issues"))
    issues = resp.get_json()

    if not issues:
        return _tool_ok("No issues found.")

    output = [f"[#{i['id']}] [{i['severity']}] [{i['status']}] {i['title']}" for i in issues]
    return _tool_ok("\n".join(output))


def _tool_create_issue(args, session):
    resp = _api("post", f"/sessions/{session['id']}/issues", args)
    data = resp.get_json()
    if resp.status_code not in (200, 201):
        return _tool_error(data.get("error", "failed to create issue"))
    return _tool_ok(f"Created issue #{data['id']}: [{data['severity']}] {data['title']}")


def _tool_update_issue(args, session):
    issue_id = args.get("issue_id")
    if not isinstance(issue_id, int):
        return _tool_error("issue_id must be an integer")
    payload = {k: v for k, v in args.items() if k != "issue_id"}
    resp = _api("patch", f"/sessions/{session['id']}/issues/{issue_id}", payload)
    data = resp.get_json()
    if resp.status_code != 200:
        return _tool_error(data.get("error", "failed to update issue"))
    changes = ", ".join(f"{k}={v}" for k, v in payload.items())
    return _tool_ok(f"Updated issue #{issue_id}: {changes}")


_TOOL_HANDLERS = {
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

        session = _get_mcp_session()
        if session is None:
            return _ok(req_id, _tool_error(
                "No MCP session is active. A human must activate a session in the web UI first."
            ))

        try:
            result = handler(args, session)
            return _ok(req_id, result)
        except Exception as e:
            return _ok(req_id, _tool_error(f"Internal error: {e}"))

    return _err(req_id, -32601, f"Method not found: {method}")
