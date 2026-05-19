import asyncio
import os

_LARGE_FILE_BYTES = 1 << 20  # 1 MB


def is_binary_file(path: str, sample: int = 8192) -> bool:
    with open(path, "rb") as f:
        return b"\x00" in f.read(sample)


def file_is_large(path: str) -> bool:
    return os.path.getsize(path) > _LARGE_FILE_BYTES


def _read_lines_sync(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


async def read_file_lines(path):
    return await asyncio.to_thread(_read_lines_sync, path)
