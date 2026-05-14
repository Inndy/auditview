import os
import pathspec

_DEFAULT_EXCLUDES = [
    "**/__pycache__/**",
    "**/.git/**",
    "**/node_modules/**",
    "**/.venv/**",
    ".auditview.db",
    ".auditview.db-wal",
    ".auditview.db-shm",
    "**/static/assets/**",
]


def scan_folder(root, exclusion_patterns_str=""):
    patterns = list(_DEFAULT_EXCLUDES)

    gitignore_path = os.path.join(root, ".gitignore")
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line and not line.startswith("#"):
                    patterns.append(line)

    if exclusion_patterns_str:
        for line in exclusion_patterns_str.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)

    spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, root)
            rel_path = rel_path.replace(os.sep, "/")
            if not spec.match_file(rel_path):
                result.append(rel_path)

    return sorted(result)
