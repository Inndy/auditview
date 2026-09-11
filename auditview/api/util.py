import os
from quart import request


async def get_json_object():
    """Return the request JSON object, or an empty object for invalid shapes.

    Route-level required-field validation then produces its existing 400 error
    without every endpoint having to defend `.get()` from arrays or scalars.
    """
    data = await request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def safe_path(root_path, rel_path):
    """Return resolved absolute path if rel_path stays within root_path, else None."""
    root = os.path.realpath(root_path)
    target = os.path.realpath(os.path.join(root_path, rel_path))
    if target != root and not target.startswith(root + os.sep):
        return None
    return target


def is_excluded(exclusion_patterns, rel_path):
    """True if rel_path is filtered out of the session by its exclusion patterns.

    Write paths consult this so a purged file cannot be resurrected: the file is
    still on disk, so an existing-but-stale client (an open nvim buffer, an MCP
    agent) can otherwise mark or annotate it and ensure_snapshot's UPSERT puts
    the files row straight back.

    Fails open — a pattern set that will not compile should not block marking.
    """
    from auditview.core.scanner import _base_spec
    try:
        return _base_spec(exclusion_patterns or "").match_file(rel_path)
    except Exception:
        return False
