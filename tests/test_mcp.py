"""Tests for MCP-to-REST request translation."""

import pytest

from auditview.api.mcp import _fetch_file_lines


class _RecordingAPI:
    def __init__(self):
        self.path = None

    async def get(self, path):
        self.path = path
        return {"lines": [{"line_no": 1, "content": "hello"}]}


@pytest.mark.asyncio
async def test_fetch_file_lines_quotes_reserved_path_characters():
    api = _RecordingAPI()

    lines, error = await _fetch_file_lines(api, "dir/a file?#%.py")

    assert error is None
    assert lines == {1: "hello"}
    assert api.path == "/files/dir/a%20file%3F%23%25.py"
