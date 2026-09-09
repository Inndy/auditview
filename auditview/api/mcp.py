from typing import Optional

from mcp.server.fastmcp import FastMCP
from quart import Quart

from auditview import version_string

_INSTRUCTIONS = """
You are connected to auditview, a line-level code audit tool.

## Before doing anything else
Call `check_context` first. It returns the active session's label and root_path.
Verify that root_path matches the repository you are working in. If no session is
active, stop and tell the user to open the auditview web UI and activate a session.

## Workflow
1. `check_context` — confirm session and root path
2. `list_issues` — see existing issues. When fixing issues, pass
   `status="open"` to skip already resolved/dismissed ones. Omit `status`
   only when auditing history or looking for past decisions.
3. `list_notes` — browse existing notes/TODOs, optionally filtered by file;
   pass include_context=true to include the current code snippet (or original
   snapshot for orphaned notes)
4. `create_note` — attach a note or TODO to a line range in a file
5. `get_issue` — fetch a single issue with all of its attached notes;
   pass include_context=true for the code snippet at each note's range
6. `create_issue` — open a new issue (severity: P0=critical, P1=high, P2=medium)
7. `update_issue` — change title, severity, or status. Mark an issue
   `resolved` once its fix lands, or `dismissed` if it turns out to be a
   non-issue, so future `list_issues(status="open")` calls stay focused.

## Rules
- Always use relative file paths (relative to root_path)
- Notes must reference real line ranges in the file you are reviewing
- Prefer attaching notes to an existing issue via issue_id over creating duplicates
- Default to `list_issues(status="open")` when picking work to fix
""".strip()

mcp = FastMCP("auditview", instructions=_INSTRUCTIONS, stateless_http=True)

_quart_app: Quart = None


def setup_mcp(quart_app):
    global _quart_app
    _quart_app = quart_app


def get_mcp_handler():
    """Return the raw ASGI handler for /mcp requests.

    Initializes the session manager lazily (side effect of streamable_http_app).
    The caller is responsible for starting and stopping the session manager via
    mcp.session_manager.run() — see setup in app.py before_serving/after_serving.
    """
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp
    mcp.streamable_http_app()  # ensures _session_manager is created
    return StreamableHTTPASGIApp(mcp.session_manager)


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
async def check_context() -> str:
    """Check the active audit session and confirm your working context.

    Call this before using any other tool. Verify that the returned root_path
    matches the repository you are working in. If no session is active, stop
    and ask the user to activate one in the auditview web UI.
    """
    async with _quart_app.test_client() as client:
        resp = await client.get("/api/config")
    config = await resp.get_json() if resp.status_code == 200 else {}
    session = config.get("mcp_session")
    if session is None:
        return (
            f"NO ACTIVE SESSION (auditview {version_string()}). "
            "Ask the user to open the auditview web UI and activate a session before proceeding."
        )
    return (
        f"Session active.\n"
        f"  label     : {session['label']}\n"
        f"  root_path : {session['root_path']}\n"
        f"  version   : {version_string()}\n\n"
        f"Confirm this root_path matches the repository you are auditing before calling other tools."
    )


async def _fetch_file_lines(api: _SessionAPI, file_path: str) -> tuple[dict[int, str], Optional[str]]:
    """Return ({line_no: content}, error_msg). error_msg is None on success."""
    try:
        data = await api.get(f"/files/{file_path}")
        return {l["line_no"]: l["content"] for l in data["lines"]}, None
    except Exception as exc:
        return {}, str(exc)


def _code_block(lines: list[str], indent: str = "  ") -> list[str]:
    return [f"{indent}```", *[f"{indent}{l}" for l in lines], f"{indent}```"]


@mcp.tool()
async def list_notes(file_path: Optional[str] = None, include_context: bool = False) -> str:
    """List all audit notes and todos in the session, optionally filtered by file.

    Args:
        file_path: Filter notes to this relative file path
        include_context: Include the current code snippet for each note.
            For orphaned notes, shows the original snapshot instead.
    """
    api = await _session_api()
    notes = await api.get("/notes")

    if file_path:
        notes = [n for n in notes if n["file_path"] == file_path.strip()]
    if not notes:
        return "No notes found."

    file_cache: dict[str, dict[int, str]] = {}
    file_errors: dict[str, str] = {}
    if include_context:
        unique_files = {n["file_path"] for n in notes if not n["is_orphaned"]}
        for fp in unique_files:
            file_cache[fp], err = await _fetch_file_lines(api, fp)
            if err:
                file_errors[fp] = err

    lines = []
    for n in notes:
        kind = "TODO" if n["is_todo"] else "NOTE"
        tags = (" [ORPHANED]" if n["is_orphaned"] else "") + (f" [issue:#{n['issue_id']}]" if n.get("issue_id") else "")
        lines.append(f"[#{n['id']}] {kind}{tags}  {n['file_path']}:{n['start_line']}-{n['end_line']}")
        lines.append(f"  {n['content']}")

        if include_context:
            if n["is_orphaned"]:
                snapshot = (n.get("snapshot_text") or "").strip()
                if snapshot:
                    lines.append("  [original snapshot]")
                    lines.extend(_code_block(snapshot.split("\n")))
            else:
                err = file_errors.get(n["file_path"])
                if err:
                    lines.append(f"  [context unavailable: {err}]")
                else:
                    file_lines = file_cache.get(n["file_path"], {})
                    snippet = [file_lines[ln] for ln in range(n["start_line"], n["end_line"] + 1) if ln in file_lines]
                    if snippet:
                        lines.extend(_code_block(snippet))

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


_VALID_ISSUE_STATUSES = ("open", "resolved", "dismissed")


@mcp.tool()
async def list_issues(status: Optional[str] = None, file_path: Optional[str] = None) -> str:
    """List issues in the active audit session.

    When you are actively fixing issues, pass status="open" — this hides
    already resolved or dismissed items so you do not re-do completed work.
    Omit status only when you need the full history (e.g. auditing past
    decisions or rediscovering a dismissed report).

    Pass file_path to restrict results to issues that have at least one live
    note in that file. Useful before creating a new issue to check for
    duplicates scoped to the file you are reviewing.

    Args:
        status: Filter by status — 'open', 'resolved', or 'dismissed'.
            Omit for all. Recommended: 'open' when iterating on fixes.
        file_path: Relative path within the session root (e.g. 'src/main.py').
            When provided, only issues with a live note in that file are returned.
    """
    if status is not None and status not in _VALID_ISSUE_STATUSES:
        raise ValueError(
            f"status must be one of {_VALID_ISSUE_STATUSES} or omitted"
        )
    api = await _session_api()
    qs_parts = []
    if status:
        qs_parts.append(f"status={status}")
    if file_path:
        from urllib.parse import quote
        qs_parts.append(f"file_path={quote(file_path, safe='/')}")
    path = "/issues" + (f"?{'&'.join(qs_parts)}" if qs_parts else "")
    issues = await api.get(path)
    if not issues:
        scope_parts = []
        if status:
            scope_parts.append(f"status={status}")
        if file_path:
            scope_parts.append(f"file={file_path}")
        scope = (" (" + ", ".join(scope_parts) + ")") if scope_parts else ""
        return f"No issues found{scope}."
    header_parts = []
    if status:
        header_parts.append(f"status={status}")
    if file_path:
        header_parts.append(f"file={file_path}")
    header = ("Showing issues: " + ", ".join(header_parts)) if header_parts else "Showing all issues"
    body = "\n".join(f"[#{i['id']}] [{i['severity']}] [{i['status']}] {i['title']}" for i in issues)
    return f"{header}\n{body}"


@mcp.tool()
async def get_issue(issue_id: int, include_context: bool = False) -> str:
    """Get full detail for a single issue, including all notes attached to it.

    Use this when you need the complete picture for one issue — its metadata
    plus every note/TODO that references it — rather than scanning the full
    list. Useful for triaging a specific report before deciding to fix or
    dismiss it.

    Args:
        issue_id: The issue ID to fetch
        include_context: Include the current code snippet for each attached note.
            For orphaned notes, shows the original snapshot instead.
    """
    api = await _session_api()
    issue = await api.get(f"/issues/{issue_id}")
    notes = await api.get(f"/issues/{issue_id}/notes")

    lines = [
        f"[#{issue['id']}] [{issue['severity']}] [{issue['status']}] {issue['title']}",
        f"  created_at: {issue['created_at']}",
    ]
    description = (issue.get("description") or "").strip()
    if description:
        lines.append("")
        lines.append("Description:")
        for dl in description.splitlines():
            lines.append(f"  {dl}")

    if not notes:
        lines.append("")
        lines.append("No notes attached.")
        return "\n".join(lines)

    file_cache: dict[str, dict[int, str]] = {}
    file_errors: dict[str, str] = {}
    if include_context:
        unique_files = {n["file_path"] for n in notes if not n["is_orphaned"]}
        for fp in unique_files:
            file_cache[fp], err = await _fetch_file_lines(api, fp)
            if err:
                file_errors[fp] = err

    lines.append("")
    lines.append(f"Attached notes ({len(notes)}):")
    for n in notes:
        kind = "TODO" if n["is_todo"] else "NOTE"
        tag = " [ORPHANED]" if n["is_orphaned"] else ""
        lines.append(f"  [#{n['id']}] {kind}{tag}  {n['file_path']}:{n['start_line']}-{n['end_line']}")
        lines.append(f"    {n['content']}")

        if include_context:
            if n["is_orphaned"]:
                snapshot = (n.get("snapshot_text") or "").strip()
                if snapshot:
                    lines.append("    [original snapshot]")
                    lines.extend(_code_block(snapshot.split("\n"), indent="    "))
            else:
                err = file_errors.get(n["file_path"])
                if err:
                    lines.append(f"    [context unavailable: {err}]")
                else:
                    file_lines = file_cache.get(n["file_path"], {})
                    snippet = [file_lines[ln] for ln in range(n["start_line"], n["end_line"] + 1) if ln in file_lines]
                    if snippet:
                        lines.extend(_code_block(snippet, indent="    "))

    return "\n".join(lines)


@mcp.tool()
async def create_issue(
    title: str,
    severity: str,
    description: Optional[str] = None,
    note_ids: Optional[list[int]] = None,
    source: Optional[str] = None,
) -> str:
    """Create a new issue in the active audit session.

    Pass source='agents:<your-name>' to record authorship, e.g.
    source='agents:codeview-lens-concurrency'. This lets humans filter
    and triage issues by which lens or agent opened them.

    Pass note_ids to atomically attach existing notes to the issue in a
    single round-trip instead of calling create_note separately.

    Args:
        title: Issue title
        severity: P0=critical, P1=high, P2=medium
        description: Optional long-form markdown description (rendered in the UI)
        note_ids: Optional list of existing note IDs to attach to this issue
        source: Who is opening this issue (e.g. 'agents:codeview-lens-concurrency',
            'webui', 'editor:neovim')
    """
    api = await _session_api()
    payload: dict = {"title": title, "severity": severity}
    if description is not None:
        payload["description"] = description
    if note_ids:
        payload["note_ids"] = note_ids
    if source is not None:
        payload["source"] = source
    data = await api.post("/issues", payload)
    return f"Created issue #{data['id']}: [{data['severity']}] {data['title']}"


@mcp.tool()
async def update_issue(
    issue_id: int,
    title: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    description: Optional[str] = None,
    actor: Optional[str] = None,
) -> str:
    """Update an existing issue's title, severity, status, or description.

    When resolving or dismissing an issue, pass actor='agents:<your-name>'
    to record who closed it, e.g. actor='agents:codeview-lens-concurrency'.

    Args:
        issue_id: The issue ID to update
        title: New title
        severity: New severity (P0/P1/P2)
        status: New status (open/resolved/dismissed)
        description: New markdown description (pass an empty string to clear)
        actor: Who is making this status change (e.g. 'agents:codeview-lens-trust-boundary').
            Only recorded when status is changing to 'resolved' or 'dismissed'.
    """
    payload = {
        k: v
        for k, v in {
            "title": title,
            "severity": severity,
            "status": status,
            "description": description,
        }.items()
        if v is not None
    }
    if actor is not None and status in ("resolved", "dismissed"):
        payload["actor"] = actor
    if not payload:
        raise ValueError("At least one field to update is required")
    api = await _session_api()
    data = await api.patch(f"/issues/{issue_id}", payload)
    changes = ", ".join(f"{k}={v}" for k, v in payload.items())
    return f"Updated issue #{issue_id}: {changes}"
