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


def _gitignore_verdict(full_path, active_specs, suffix=""):
    """Ask the .gitignore chain about one path: (ignored, deciding_dir).

    Git's precedence is that a pattern in a deeper .gitignore overrides one in a
    shallower file, so the chain is consulted deepest-first and the first file
    with an opinion decides; pathspec gives the last matching pattern *within*
    one file the last word, which is the other half of git's rule. Returns
    (False, None) when no file in the chain has an opinion.

    check_file() rather than match_file() because only it separates "this file
    says nothing" (include is None) from "this file re-includes the path with a
    !pattern" (include is False) — match_file() collapses both to False, which
    made a shallower rule win and left `!keep.log` in a nested .gitignore inert.
    """
    for spec_dir, spec in reversed(active_specs):
        rel = os.path.relpath(full_path, spec_dir).replace(os.sep, "/") + suffix
        result = spec.check_file(rel)
        if result.include is not None:
            return result.include, spec_dir
    return False, None


def path_excluded(root, rel_path, exclusion_patterns_str=""):
    """Would scan_folder() skip this one path? Answered without walking the tree.

    scan_folder() can only answer this by scanning everything, and callers cache
    its result per session — so a file created since the last scan is absent
    from that list for two very different reasons, and "not in the scan" cannot
    tell them apart. This applies the same two filters in the same order to a
    single path: base_spec, then the .gitignore chain from the root down to the
    file's own directory, deepest opinion winning.

    Distinct from api.util.is_excluded(), which asks only whether the session's
    own exclusion_patterns cover a path — no filesystem access, no .gitignore —
    because the write paths that call it must not consult a .gitignore.
    """
    base_spec = _base_spec(exclusion_patterns_str)
    parts = [p for p in rel_path.strip("/").split("/") if p and p != "."]
    if not parts:
        return True

    # Mirrors scan_folder's walk: at each level the directory's own .gitignore
    # joins the chain before its children are judged, and an excluded directory
    # is never descended into (so nothing below it can be re-included).
    active_specs = []
    for depth, name in enumerate(parts):
        dirpath = os.path.join(root, *parts[:depth]) if depth else root
        gi_path = os.path.join(dirpath, ".gitignore")
        if os.path.isfile(gi_path):
            patterns = _load_gitignore_patterns(gi_path)
            if patterns:
                active_specs.append(
                    (dirpath, pathspec.PathSpec.from_lines("gitwildmatch", patterns))
                )

        suffix = "" if depth == len(parts) - 1 else "/"
        rel_child = "/".join(parts[:depth + 1]) + suffix
        if base_spec.match_file(rel_child):
            return True
        ignored, _spec_dir = _gitignore_verdict(
            os.path.join(dirpath, name), active_specs, suffix=suffix
        )
        if ignored:
            return True

    return False


def scan_folder(root, exclusion_patterns_str=""):
    """Every reviewable path under `root`, relative and slash-separated.

    Two filters, in this order. base_spec (the built-in excludes plus the
    session's exclusion_patterns) is unconditional and is checked first: POST
    /purge keeps a path out of future scans by appending a pattern to
    exclusion_patterns, so a .gitignore must not be able to re-include it. The
    nested .gitignore chain decides everything base_spec does not care about,
    with git's own precedence (see _gitignore_verdict).
    """
    real_root = os.path.realpath(root)
    base_spec = _base_spec(exclusion_patterns_str)

    # Only specs whose directory is an ancestor of (or equal to) the current
    # dirpath apply. Because os.walk is topdown and visits siblings
    # independently, we prune to ancestors at the start of each iteration so
    # specs from already-visited sibling subtrees do not leak. Order is
    # shallowest-first, which _gitignore_verdict relies on.
    active_specs = []

    result = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        active_specs = [
            (d, s) for d, s in active_specs
            if dirpath == d or dirpath.startswith(d + os.sep)
        ]

        gi_path = os.path.join(dirpath, ".gitignore")
        if os.path.isfile(gi_path):
            patterns = _load_gitignore_patterns(gi_path)
            if patterns:
                active_specs.append(
                    (dirpath, pathspec.PathSpec.from_lines("gitwildmatch", patterns))
                )

        for fname in filenames:
            full_path = os.path.join(dirpath, fname)

            rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")

            if base_spec.match_file(rel_path):
                logger.debug('path %s ignored by base_spec rule %r', rel_path, base_spec)
                continue

            ignored, spec_dir = _gitignore_verdict(full_path, active_specs)
            if ignored:
                logger.debug('path %s ignored by .gitignore in %s', rel_path, spec_dir)
                continue

            # Skip symlinks that resolve outside the project root (checked last, it's rare)
            real_path = os.path.realpath(full_path)
            if not real_path.startswith(real_root + os.sep) and real_path != real_root:
                continue

            result.append(rel_path)

        # An ignored directory is not descended into, which is also how git
        # arrives at "a file cannot be re-included if a parent is excluded".
        kept = []
        for d in dirnames:
            full_d = os.path.join(dirpath, d)
            rel_d = os.path.relpath(full_d, root).replace(os.sep, "/") + "/"
            if base_spec.match_file(rel_d):
                continue
            ignored, _spec_dir = _gitignore_verdict(full_d, active_specs, suffix="/")
            if not ignored:
                kept.append(d)
        dirnames[:] = kept

    return sorted(result)
