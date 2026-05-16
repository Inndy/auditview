import os
import pathspec
import logging
from functools import lru_cache

logger = logging.getLogger("auditview")

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


@lru_cache(maxsize=32)
def _base_spec(exclusion_patterns_str: str) -> pathspec.PathSpec:
    patterns = list(_DEFAULT_EXCLUDES)
    for line in exclusion_patterns_str.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


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
    real_root = os.path.realpath(root)
    base_spec = _base_spec(exclusion_patterns_str)

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
                logger.debug('path %s ignored by base_spec rule %r', rel_path, base_spec)
                continue

            excluded = False
            for spec_dir, spec in dir_specs.items():
                spec_dir_prefix = spec_dir.rstrip(os.sep) + os.sep
                if not full_path.startswith(spec_dir_prefix):
                    continue
                rel_to_spec = os.path.relpath(full_path, spec_dir).replace(os.sep, "/")
                if spec.match_file(rel_to_spec):
                    logger.debug('path %s ignored by dir_spec %s rule %r', rel_path, spec_dir, spec)
                    excluded = True
                    break

            if excluded:
                continue

            # Skip symlinks that resolve outside the project root (checked last, it's rare)
            real_path = os.path.realpath(full_path)
            if not real_path.startswith(real_root + os.sep) and real_path != real_root:
                continue

            result.append(rel_path)

        kept = []
        for d in dirnames:
            full_d = os.path.join(dirpath, d)
            rel_d = os.path.relpath(full_d, root).replace(os.sep, "/") + "/"
            if base_spec.match_file(rel_d):
                continue
            dir_excluded = False
            for spec_dir, spec in dir_specs.items():
                spec_dir_prefix = spec_dir.rstrip(os.sep) + os.sep
                if not full_d.startswith(spec_dir_prefix):
                    continue
                rel_to_spec = os.path.relpath(full_d, spec_dir).replace(os.sep, "/") + "/"
                if spec.match_file(rel_to_spec):
                    dir_excluded = True
                    break
            if not dir_excluded:
                kept.append(d)
        dirnames[:] = kept

    return sorted(result)
