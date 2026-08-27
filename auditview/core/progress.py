async def session_exists(conn, session_id):
    cur = await conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
    return await cur.fetchone() is not None


async def file_progress(conn, session_id):
    cur = await conn.execute(
        "SELECT rel_path, countable_lines FROM files WHERE session_id = ? ORDER BY rel_path",
        (session_id,),
    )
    file_rows = await cur.fetchall()
    countable_map = {r["rel_path"]: r["countable_lines"] for r in file_rows}

    cur = await conn.execute(
        "SELECT file_path, COUNT(*) AS cnt FROM reviewed_lines WHERE session_id = ? GROUP BY file_path",
        (session_id,),
    )
    reviewed_map = {r["file_path"]: r["cnt"] for r in await cur.fetchall()}

    cur = await conn.execute(
        "SELECT file_path, "
        "SUM(CASE WHEN is_todo=0 THEN 1 ELSE 0 END) AS notes_cnt, "
        "SUM(CASE WHEN is_todo=1 THEN 1 ELSE 0 END) AS todos_cnt "
        "FROM notes WHERE session_id = ? AND is_orphaned=0 GROUP BY file_path",
        (session_id,),
    )
    notes_map = {r["file_path"]: (r["notes_cnt"] or 0, r["todos_cnt"] or 0) for r in await cur.fetchall()}

    cur = await conn.execute(
        "SELECT n.file_path, "
        "MIN(CASE i.severity WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 END) AS sev_rank, "
        "COUNT(DISTINCT i.id) AS open_count "
        "FROM notes n JOIN issues i ON n.issue_id = i.id AND i.session_id = n.session_id "
        "WHERE n.session_id = ? AND n.is_orphaned = 0 AND i.status = 'open' "
        "GROUP BY n.file_path",
        (session_id,),
    )
    _rank_to_sev = {0: "P0", 1: "P1", 2: "P2"}
    severity_map = {}
    open_issue_map = {}
    for r in await cur.fetchall():
        if r["sev_rank"] is not None:
            severity_map[r["file_path"]] = _rank_to_sev.get(r["sev_rank"])
        open_issue_map[r["file_path"]] = r["open_count"] or 0

    result = []
    for rel_path, countable_raw in countable_map.items():
        countable = countable_raw or 0
        reviewed = min(reviewed_map.get(rel_path, 0), countable)
        coverage = reviewed / countable if countable > 0 else 0.0
        notes_c, todos_c = notes_map.get(rel_path, (0, 0))

        if countable == 0:
            status = "empty"
        elif reviewed == 0:
            status = "not_viewed"
        elif reviewed >= countable:
            status = "reviewed"
        else:
            status = "partial"

        result.append({
            "rel_path": rel_path,
            "countable_lines": countable,
            "reviewed_lines": reviewed,
            "coverage": coverage,
            "status": status,
            "notes_count": notes_c,
            "todos_count": todos_c,
            "max_severity": severity_map.get(rel_path),
            "open_issue_count": open_issue_map.get(rel_path, 0),
        })
    return result


async def session_coverage(conn, session_id):
    cur = await conn.execute(
        "SELECT COUNT(*) AS total_files, COALESCE(SUM(countable_lines), 0) AS total_countable "
        "FROM files WHERE session_id = ? AND countable_lines IS NOT NULL",
        (session_id,),
    )
    file_agg = await cur.fetchone()

    # Per-file: clamp reviewed to countable so a stale reviewed_lines row
    # (e.g. a line that has become non-countable since it was marked, or
    # that belongs to a file no longer tracked) can't push the total over
    # 100%.
    cur = await conn.execute(
        "SELECT COALESCE(SUM(MIN(rl_cnt, f.countable_lines)), 0) AS total_reviewed "
        "FROM files f "
        "JOIN ("
        "  SELECT file_path, COUNT(*) AS rl_cnt FROM reviewed_lines "
        "  WHERE session_id = ? GROUP BY file_path"
        ") rl ON rl.file_path = f.rel_path "
        "WHERE f.session_id = ? AND f.countable_lines IS NOT NULL",
        (session_id, session_id),
    )
    rl_agg = await cur.fetchone()

    total_countable = file_agg["total_countable"]
    total_reviewed = rl_agg["total_reviewed"]

    return {
        "total_files": file_agg["total_files"],
        "total_countable_lines": total_countable,
        "total_reviewed_lines": total_reviewed,
        "coverage": total_reviewed / total_countable if total_countable > 0 else 0.0,
    }


async def issue_counts(conn, session_id):
    cur = await conn.execute(
        "SELECT status, severity, COUNT(*) AS cnt FROM issues "
        "WHERE session_id = ? GROUP BY status, severity",
        (session_id,),
    )
    counts = {}
    for r in await cur.fetchall():
        counts.setdefault(r["status"], {})[r["severity"]] = r["cnt"]
    return counts


async def active_session(conn):
    cur = await conn.execute("SELECT value FROM app_config WHERE key = 'mcp_session_id'")
    row = await cur.fetchone()
    if not row:
        return None
    session_id = int(row["value"])
    cur = await conn.execute(
        "SELECT id, label, root_path FROM sessions WHERE id = ?", (session_id,)
    )
    srow = await cur.fetchone()
    if not srow:
        return None
    return {"id": srow["id"], "label": srow["label"], "root_path": srow["root_path"]}
