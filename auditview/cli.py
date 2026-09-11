import argparse
import asyncio
import json
import os
import sys

from auditview import version_string
from auditview.db.connection import open_db
from auditview.core.progress import (
    active_session,
    file_progress,
    issue_counts,
    session_coverage,
    session_exists,
)

SUBCOMMANDS = ("context", "stats", "files")

_STATUSES = ("not_viewed", "partial", "reviewed", "empty", "unreviewable")
_SORTS = ("coverage", "path", "size")


class CliError(Exception):
    pass


def _find_db(explicit):
    if explicit:
        path = os.path.abspath(explicit)
        if not os.path.isfile(path):
            raise CliError(f"database not found: {path}")
        return path

    env = os.environ.get("AUDITVIEW_DB")
    if env:
        path = os.path.abspath(env)
        if not os.path.isfile(path):
            raise CliError(f"AUDITVIEW_DB points at a missing file: {path}")
        return path

    cur = os.getcwd()
    while True:
        candidate = os.path.join(cur, ".auditview.db")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            raise CliError(
                "no .auditview.db found in this directory or any parent. "
                "Pass --db, set AUDITVIEW_DB, or run from inside an audited repository."
            )
        cur = parent


async def _all_sessions(conn):
    cur = await conn.execute(
        "SELECT id, label, root_path FROM sessions ORDER BY id"
    )
    return [dict(r) for r in await cur.fetchall()]


async def _resolve_session(conn, explicit):
    if explicit is not None:
        if not await session_exists(conn, explicit):
            raise CliError(f"session {explicit} does not exist in this database")
        cur = await conn.execute(
            "SELECT id, label, root_path FROM sessions WHERE id = ?", (explicit,)
        )
        return dict(await cur.fetchone())

    session = await active_session(conn)
    if session is not None:
        return session

    sessions = await _all_sessions(conn)
    if len(sessions) == 1:
        return sessions[0]
    if not sessions:
        raise CliError("this database has no sessions yet")
    listing = "\n".join(f"  {s['id']}  {s['label']}  {s['root_path']}" for s in sessions)
    raise CliError(
        "NO ACTIVE SESSION and this database has several. Ask the user to activate one "
        "in the auditview web UI, or pass --session:\n" + listing
    )


def _emit(as_json, payload, render):
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        render(payload)


async def _cmd_context(conn, session, args, db_path):
    payload = {
        "session_id": session["id"],
        "label": session["label"],
        "root_path": session["root_path"],
        "db_path": db_path,
        "version": version_string(),
    }

    def render(p):
        print(f"session #{p['session_id']}  {p['label']!r}")
        print(f"  root_path : {p['root_path']}")
        print(f"  db_path   : {p['db_path']}")
        print(f"  version   : {p['version']}")
        print()
        print("Confirm this root_path matches the repository you are working in "
              "before acting on anything below.")

    _emit(args.json, payload, render)


async def _cmd_stats(conn, session, args, db_path):
    coverage = await session_coverage(conn, session["id"])
    issues = await issue_counts(conn, session["id"])
    payload = {
        "session_id": session["id"],
        "label": session["label"],
        "root_path": session["root_path"],
        **coverage,
        "issues": issues,
    }

    def render(p):
        print(f"session #{p['session_id']}  {p['label']!r}  {p['root_path']}")
        print(f"  files            : {p['total_files']}")
        print(f"  countable lines  : {p['total_countable_lines']}")
        print(f"  reviewed lines   : {p['total_reviewed_lines']}")
        print(f"  coverage         : {p['coverage'] * 100:.1f}%")
        for status in sorted(p["issues"]):
            by_sev = p["issues"][status]
            detail = " ".join(f"{sev}={by_sev[sev]}" for sev in sorted(by_sev))
            print(f"  issues {status:<10}: {detail}")

    _emit(args.json, payload, render)


async def _cmd_files(conn, session, args, db_path):
    rows = await file_progress(conn, session["id"])

    if args.status:
        wanted = set(args.status)
        rows = [r for r in rows if r["status"] in wanted]

    if args.sort == "coverage":
        rows.sort(key=lambda r: (r["coverage"], -r["countable_lines"], r["rel_path"]))
    elif args.sort == "size":
        rows.sort(key=lambda r: (-r["countable_lines"], r["rel_path"]))

    if args.limit is not None:
        rows = rows[: args.limit]

    def render(p):
        if not p:
            print("no files match.")
            return
        print(f"{'STATUS':<11} {'COV':>5}  {'REVIEWED/TOTAL':>16}  {'N':>3} {'T':>3} {'ISS':>4} {'SEV':>4}  PATH")
        for r in p:
            ratio = f"{r['reviewed_lines']}/{r['countable_lines']}"
            print(
                f"{r['status']:<11} {r['coverage'] * 100:4.0f}%  {ratio:>16}  "
                f"{r['notes_count']:>3} {r['todos_count']:>3} {r['open_issue_count']:>4} "
                f"{r['max_severity'] or '':>4}  {r['rel_path']}"
            )
        print()
        print(f"{len(p)} files.  N=notes T=todos ISS=open issues SEV=highest open severity")

    _emit(args.json, rows, render)


_HANDLERS = {
    "context": _cmd_context,
    "stats": _cmd_stats,
    "files": _cmd_files,
}


def _add_global_flags(p, suppress):
    default = argparse.SUPPRESS if suppress else None
    p.add_argument("--db", metavar="FILE", default=default,
                   help="Database file (default: $AUDITVIEW_DB, else search upward for .auditview.db)")
    p.add_argument("--session", type=int, metavar="ID", default=default,
                   help="Session to query (default: the session activated in the web UI)")
    p.add_argument("--json", action="store_true",
                   default=argparse.SUPPRESS if suppress else False,
                   help="Emit raw JSON")


def _build_parser():
    p = argparse.ArgumentParser(
        prog="auditview",
        description="Query review progress from an auditview database (read-only).",
    )
    _add_global_flags(p, suppress=False)

    # Repeated on every subparser with SUPPRESS defaults so the flags work on
    # either side of the subcommand without clobbering the global value.
    common = argparse.ArgumentParser(add_help=False)
    _add_global_flags(common, suppress=True)

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("context", parents=[common],
                   help="Show which session and repository root these commands act on")
    sub.add_parser("stats", parents=[common],
                   help="Show session-wide review coverage and issue counts")

    files = sub.add_parser("files", parents=[common], help="List per-file review progress")
    files.add_argument("--status", action="append", choices=_STATUSES,
                       help="Only show files with this status (repeatable)")
    files.add_argument("--sort", choices=_SORTS, default="path",
                       help="Sort order (default: path)")
    files.add_argument("--limit", type=int, metavar="N", help="Show at most N files")
    return p


async def _run(args):
    db_path = _find_db(args.db)
    async with open_db(db_path) as conn:
        session = await _resolve_session(conn, args.session)
        await _HANDLERS[args.command](conn, session, args, db_path)


def run(argv):
    args = _build_parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except CliError as exc:
        print(f"auditview: {exc}", file=sys.stderr)
        return 1
    return 0
