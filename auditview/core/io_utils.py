import asyncio
import os
import re

MAX_REVIEWABLE_FILE_BYTES = 1 << 20  # 1 MiB

# Real line terminators only. str.splitlines() additionally breaks on \f, \v,
# \x1c-\x1e, \x85, U+2028 and U+2029, and nothing else that consumes auditview's
# line numbers does: LSP servers, editors, git and the nvim client all split on
# newlines alone. A form feed -- a page separator in real C and Python -- would
# otherwise shift every later line number in the file away from what the user
# sees, silently and for the rest of the file.
#
# The open() below uses universal newlines, so \r and \r\n are already collapsed
# to \n before this runs; the alternation keeps _split_lines correct on its own
# terms rather than relying on the caller's open mode.
_LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")


def is_binary_file(path: str, sample: int = 8192) -> bool:
    with open(path, "rb") as f:
        return b"\x00" in f.read(sample)


def file_is_large(path: str) -> bool:
    return os.path.getsize(path) > MAX_REVIEWABLE_FILE_BYTES


def unreviewable_reason(path: str) -> str | None:
    """Return why the normal review pipeline must not read *path* in full."""
    if file_is_large(path):
        return "large"
    if is_binary_file(path):
        return "binary"
    return None


def _split_lines(text):
    """Split text into lines on \\r\\n, \\r and \\n, matching str.splitlines() elsewhere.

    A trailing terminator ends the last line rather than starting an empty new
    one, and empty text yields no lines -- both matching splitlines(), and both
    load-bearing: a phantom trailing line would inflate the line count of
    essentially every file in every repository.
    """
    if not text:
        return []
    lines = _LINE_SPLIT_RE.split(text)
    if lines[-1] == "":
        lines.pop()
    return lines


def _read_lines_sync(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return _split_lines(f.read())


async def read_file_lines(path):
    return await asyncio.to_thread(_read_lines_sync, path)
