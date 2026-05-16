import asyncio


def _read_lines_sync(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


async def read_file_lines(path):
    return await asyncio.to_thread(_read_lines_sync, path)
