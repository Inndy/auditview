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


def _load_gitignore_patterns(path):
    patterns = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line and not line.startswith("#"):
                    patterns.append(line)
    except OSError:
        pass
    return patterns


def scan_folder(root, exclusion_patterns_str=""):
    base_patterns = list(_DEFAULT_EXCLUDES)
    if exclusion_patterns_str:
        for line in exclusion_patterns_str.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                base_patterns.append(line)
    base_spec = pathspec.PathSpec.from_lines("gitwildmatch", base_patterns)

    # Map of abs_dir → PathSpec built from that dir's .gitignore
    dir_specs = {}

    result = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        gi_path = os.path.join(dirpath, ".gitignore")
        if os.path.isfile(gi_path):
            patterns = _load_gitignore_patterns(gi_path)
            if patterns:
                dir_specs[dirpath] = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")

            if base_spec.match_file(rel_path):
                continue

            excluded = False
            for spec_dir, spec in dir_specs.items():
                rel_to_spec = os.path.relpath(full_path, spec_dir).replace(os.sep, "/")
                if spec.match_file(rel_to_spec):
                    excluded = True
                    break

            if not excluded:
                result.append(rel_path)

        # Prune dirnames so os.walk skips excluded directories early
        dirnames[:] = [
            d for d in dirnames
            if not base_spec.match_file(
                os.path.relpath(os.path.join(dirpath, d), root).replace(os.sep, "/") + "/"
            )
        ]

    return sorted(result)
