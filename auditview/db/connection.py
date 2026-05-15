from contextlib import asynccontextmanager
import aiosqlite


@asynccontextmanager
async def open_db(path):
    async with aiosqlite.connect(path, isolation_level=None) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        yield conn
