from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("auditview", stateless_http=True)

_quart_app = None


def setup_mcp(quart_app):
    global _quart_app
    _quart_app = quart_app


def get_mcp_asgi():
    return mcp.streamable_http_app()


class _SessionAPI:
    """Scoped API client for the active MCP session."""

    def __init__(self, session):
        self._base = f"/api/sessions/{session['id']}"

    async def _call(self, method, path, data=None, ok=(200,)):
        async with _quart_app.test_client() as client:
            fn = getattr(client, method)
            resp = await (fn(path, json=data) if data is not None else fn(path))
        body = await resp.get_json()
        if resp.status_code not in ok:
            raise RuntimeError(body.get("error", f"request failed ({resp.status_code})"))
        return body

    async def get(self, path, **kw):
        return await self._call("get", self._base + path, **kw)

    async def post(self, path, data, **kw):
        return await self._call("post", self._base + path, data, ok=(200, 201), **kw)

    async def patch(self, path, data, **kw):
        return await self._call("patch", self._base + path, data, **kw)


async def _session_api() -> _SessionAPI:
    async with _quart_app.test_client() as client:
        resp = await client.get("/api/config")
    config = await resp.get_json()
    session = config.get("mcp_session") if resp.status_code == 200 else None
    if session is None:
        raise ValueError("No MCP session is active. A human must activate a session in the web UI first.")
    return _SessionAPI(session)


@mcp.tool()
async def list_notes(file_path: Optional[str] = None) -> str:
    """List all audit notes and todos in the session, optionally filtered by file."""
    api = await _session_api()
    notes = await api.get("/notes")

    if file_path:
        notes = [n for n in notes if n["file_path"] == file_path.strip()]
    if not notes:
        return "No notes found."

    lines = []
    for n in notes:
        kind = "TODO" if n["is_todo"] else "NOTE"
        tags = (" [ORPHANED]" if n["is_orphaned"] else "") + (f" [issue:#{n['issue_id']}]" if n.get("issue_id") else "")
        lines.append(f"[#{n['id']}] {kind}{tags}  {n['file_path']}:{n['start_line']}-{n['end_line']}")
        lines.append(f"  {n['content']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def create_note(
    file_path: str,
    start_line: int,
    end_line: int,
    content: str,
    is_todo: bool = False,
    issue_id: Optional[int] = None,
) -> str:
    """Create an audit note or todo on a specific range of lines in a file.

    Args:
        file_path: Relative file path within the session root
        start_line: First line number (1-indexed)
        end_line: Last line number (1-indexed, inclusive)
        content: The note text
        is_todo: Mark as a todo/action item
        issue_id: Attach to an existing issue by ID
    """
    api = await _session_api()
    payload = {"file_path": file_path, "start_line": start_line, "end_line": end_line, "content": content, "is_todo": is_todo}
    if issue_id is not None:
        payload["issue_id"] = issue_id
    data = await api.post("/notes", payload)
    kind = "todo" if data["is_todo"] else "note"
    return f"Created {kind} #{data['id']} on {data['file_path']}:{data['start_line']}-{data['end_line']}"


@mcp.tool()
async def list_issues(status: Optional[str] = None) -> str:
    """List issues in the active audit session.

    Args:
        status: Filter by status — 'open', 'resolved', or 'dismissed' (omit for all)
    """
    api = await _session_api()
    path = "/issues" + (f"?status={status}" if status else "")
    issues = await api.get(path)
    if not issues:
        return "No issues found."
    return "\n".join(f"[#{i['id']}] [{i['severity']}] [{i['status']}] {i['title']}" for i in issues)


@mcp.tool()
async def create_issue(title: str, severity: str) -> str:
    """Create a new issue in the active audit session.

    Args:
        title: Issue title
        severity: P0=critical, P1=high, P2=medium
    """
    api = await _session_api()
    data = await api.post("/issues", {"title": title, "severity": severity})
    return f"Created issue #{data['id']}: [{data['severity']}] {data['title']}"


@mcp.tool()
async def update_issue(
    issue_id: int,
    title: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """Update an existing issue's title, severity, or status.

    Args:
        issue_id: The issue ID to update
        title: New title
        severity: New severity (P0/P1/P2)
        status: New status (open/resolved/dismissed)
    """
    payload = {k: v for k, v in {"title": title, "severity": severity, "status": status}.items() if v is not None}
    if not payload:
        raise ValueError("At least one field to update is required")
    api = await _session_api()
    data = await api.patch(f"/issues/{issue_id}", payload)
    changes = ", ".join(f"{k}={v}" for k, v in payload.items())
    return f"Updated issue #{issue_id}: {changes}"
