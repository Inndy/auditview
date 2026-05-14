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


def is_countable_line(line, ext, skip_comments=True):
    if not line.strip():
        return False
    if skip_comments:
        prefixes = _COMMENT_PREFIXES.get(ext, ())
        for pattern in prefixes:
            if re.match(pattern, line):
                return False
    return True


def compute_coverage(lines, ext, skip_comments=True):
    countable = sum(1 for l in lines if is_countable_line(l, ext, skip_comments))
    reviewed = sum(1 for l in lines if l.get("is_reviewed") and is_countable_line(l["content"], ext, skip_comments))
    return countable, reviewed
