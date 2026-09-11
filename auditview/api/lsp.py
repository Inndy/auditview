import os

from quart import Blueprint, jsonify, request, current_app

from auditview.db.connection import open_db
from auditview.core.io_utils import file_is_large, is_binary_file, read_file_lines
from auditview.core.lsp import LspError, uri_to_path
from auditview.api.util import get_json_object, safe_path, is_excluded

bp = Blueprint("lsp", __name__)

# How much of an out-of-root file to hand back around the target line. A preview
# exists so the reviewer can see what a dependency does, not to read it whole.
_PREVIEW_CONTEXT = 80


def partition_targets(locations, root_path, exclusion_patterns):
    """Split raw LSP locations into in-root and out-of-root targets.

    Every step here is a response to something a real server actually returned
    (see scripts/lsp-spike/README.md):

    * URIs arrive percent-encoded, so they are decoded before any comparison.
    * Non-`file:` URIs (Volar's virtual documents) are dropped -- nothing can
      open them.
    * Duplicates occur; the Options-API case returned one location twice.
    * A definition can come back alongside unrelated hits in the toolchain's own
      stdlib, so in-root and out-of-root are kept apart rather than interleaved.
    * In-root hits may point at paths the session excludes -- basedpyright
      returned six references inside `build/lib/...` for this very repo.

    Returns `(in_root, out_of_root)`. Line numbers are converted from LSP's
    0-based to auditview's 1-based here, at the boundary; `character` stays
    0-based and in UTF-16 code units, exactly as the browser computed it.
    """
    real_root = os.path.realpath(root_path)
    seen = set()
    in_root = []
    out_of_root = []
    for loc in locations:
        path = uri_to_path(loc.get("uri", ""))
        if path is None:
            continue
        real = os.path.realpath(path)
        key = (real, loc.get("line", 0), loc.get("character", 0))
        if key in seen:
            continue
        seen.add(key)
        target = {
            "line": loc.get("line", 0) + 1,
            "character": loc.get("character", 0),
        }
        # safe_path answers containment for an absolute path too: os.path.join
        # discards the root when the second argument is absolute.
        if safe_path(root_path, real) is not None:
            rel = os.path.relpath(real, real_root)
            if is_excluded(exclusion_patterns, rel):
                continue
            in_root.append({"file_path": rel, **target})
        else:
            out_of_root.append({"path": real, **target})
    return in_root, out_of_root


async def _session_row(conn, session_id):
    cur = await conn.execute(
        "SELECT id, root_path, exclusion_patterns FROM sessions WHERE id = ?",
        (session_id,),
    )
    return await cur.fetchone()


@bp.route("/sessions/<int:session_id>/lsp/definition", methods=["POST"])
async def definition(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        row = await _session_row(conn, session_id)
        if row is None:
            return jsonify({"error": "Session not found"}), 404
        root_path = row["root_path"]
        exclusions = row["exclusion_patterns"]

        data = await get_json_object()
        file_path = data.get("file_path")
        line = data.get("line")
        character = data.get("character")
        if not isinstance(file_path, str) or not file_path:
            return jsonify({"error": "file_path must be a non-empty string"}), 400
        if line is None or character is None:
            return jsonify({"error": "file_path, line, and character are required"}), 400
        if (
            not isinstance(line, int) or isinstance(line, bool) or
            not isinstance(character, int) or isinstance(character, bool)
        ):
            return jsonify({"error": "line and character must be integers"}), 400
        if line < 1 or character < 0:
            return jsonify({"error": "invalid position"}), 400

        full_path = safe_path(root_path, file_path)
        if full_path is None:
            return jsonify({"error": "Invalid path"}), 400
        if not os.path.isfile(full_path):
            return jsonify({"error": "File not found"}), 404
        if is_excluded(exclusions, file_path):
            return jsonify({"error": "File is excluded from this session"}), 409

    lsp = current_app.lsp
    if lsp is None:
        return jsonify({"provider": None, "reason": "disabled",
                        "in_root": [], "out_of_root": []})

    spec = lsp.spec_for(file_path)
    if spec is None:
        ext = os.path.splitext(file_path)[1] or file_path
        return jsonify({"provider": None, "reason": "no_provider", "detail": ext,
                        "in_root": [], "out_of_root": []})

    try:
        # LSP positions are 0-based; auditview line numbers are 1-based.
        locations = await lsp.definition(root_path, file_path, line - 1, character)
    except LspError as exc:
        current_app.logger.warning("lsp: definition failed: %s", exc)
        return jsonify({"error": str(exc), "provider": spec["name"]}), 503

    in_root, out_of_root = partition_targets(locations or [], root_path, exclusions)
    if out_of_root:
        lsp.remember_previewable(session_id, [t["path"] for t in out_of_root])
    return jsonify({"provider": spec["name"], "reason": None,
                    "in_root": in_root, "out_of_root": out_of_root})


@bp.route("/sessions/<int:session_id>/lsp/status", methods=["GET"])
async def status(session_id):
    async with open_db(current_app.config["DB_PATH"]) as conn:
        if await _session_row(conn, session_id) is None:
            return jsonify({"error": "Session not found"}), 404
    lsp = current_app.lsp
    if lsp is None:
        return jsonify({"enabled": False, "servers": []})
    return jsonify({"enabled": True, "servers": lsp.status()})


@bp.route("/sessions/<int:session_id>/lsp/preview", methods=["GET"])
async def preview(session_id):
    """Read-only window onto a file outside the session root.

    Deliberately returns no `line_hash`, no `context_hash`, no `is_reviewed` and
    no `is_countable`, and writes nothing: an out-of-root file must not be
    markable, or review coverage stops meaning "a human read this project".

    Only paths a definition query actually returned are served. auditview ships
    no authentication, so an endpoint that read any absolute path handed to it
    would be an arbitrary-file reader for anyone who can reach the port.
    """
    async with open_db(current_app.config["DB_PATH"]) as conn:
        if await _session_row(conn, session_id) is None:
            return jsonify({"error": "Session not found"}), 404

    path = request.args.get("path")
    if not path:
        return jsonify({"error": "path is required"}), 400

    lsp = current_app.lsp
    if lsp is None or not lsp.is_previewable(session_id, path):
        return jsonify({"error": "Path is not previewable in this session"}), 403

    if not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    try:
        if is_binary_file(path):
            return jsonify({"error": "Binary file detected", "reason": "binary"}), 422
        if file_is_large(path):
            return jsonify({"error": "File is too large", "reason": "large",
                            "size": os.path.getsize(path)}), 422
        lines = await read_file_lines(path)
    except OSError:
        return jsonify({"error": "Could not read file"}), 500

    try:
        center = int(request.args.get("line", 1))
    except ValueError:
        center = 1
    start = max(1, center - _PREVIEW_CONTEXT // 2)
    end = min(len(lines), start + _PREVIEW_CONTEXT - 1)
    return jsonify({
        "path": path,
        "start_line": start,
        "total_lines": len(lines),
        "reviewable": False,
        "lines": [
            {"line_no": n, "content": lines[n - 1]}
            for n in range(start, end + 1)
        ],
    })
