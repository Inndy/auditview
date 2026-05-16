import re

_COMMENT_PREFIXES = {
    ".c": (r"^\s*//", r"^\s*\*"),
    ".cpp": (r"^\s*//", r"^\s*\*"),
    ".cs": (r"^\s*//", r"^\s*\*"),
    ".go": (r"^\s*//", r"^\s*\*"),
    ".h": (r"^\s*//", r"^\s*\*"),
    ".java": (r"^\s*//", r"^\s*\*"),
    ".js": (r"^\s*//", r"^\s*\*"),
    ".jsx": (r"^\s*//", r"^\s*\*"),
    ".py": (r"^\s*#",),
    ".ts": (r"^\s*//", r"^\s*\*"),
    ".tsx": (r"^\s*//", r"^\s*\*"),
}


def is_countable_line(line, ext):
    if not line.strip():
        return False
    prefixes = _COMMENT_PREFIXES.get(ext, ())
    for pattern in prefixes:
        if re.match(pattern, line):
            return False
    return True
