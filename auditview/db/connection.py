from contextlib import asynccontextmanager
import os
from pathlib import Path

import aiosqlite


@asynccontextmanager
async def open_db(path):
    async with aiosqlite.connect(path, isolation_level=None) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA foreign_keys=ON")
        yield conn


@asynccontextmanager
async def open_db_readonly(path):
    """Open an existing database without writes or persistent PRAGMA changes.

    A WAL database normally needs writable `-wal`/`-shm` sidecars even from a
    read-only connection. Prefer that live view, then fall back to SQLite's
    immutable snapshot mode when a genuinely read-only mount prevents it.
    """
    resolved = Path(path).resolve()
    base_uri = resolved.as_uri()
    # Avoid even attempting WAL sidecars when the containing snapshot is
    # visibly read-only. The exception fallback covers ACLs/mount flags that
    # os.access cannot predict.
    immutable = not os.access(resolved.parent, os.W_OK)
    query = "mode=ro&immutable=1" if immutable else "mode=ro"
    conn = None
    try:
        try:
            conn = await aiosqlite.connect(
                f"{base_uri}?{query}", uri=True, isolation_level=None
            )
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA query_only=ON")
        except aiosqlite.OperationalError as exc:
            if conn is not None:
                await conn.close()
            message = str(exc).lower()
            if "readonly" not in message and "unable to open" not in message:
                raise
            if immutable:
                raise
            conn = await aiosqlite.connect(
                f"{base_uri}?mode=ro&immutable=1", uri=True, isolation_level=None
            )
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA query_only=ON")

        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        if conn is not None:
            await conn.close()
