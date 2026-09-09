"""Scan precedence: a deeper .gitignore overrides a shallower one, as git does.

scan_folder() used to break on the first matching spec while walking
active_specs outermost-first, so a `!negation` in a nested .gitignore could
never win and the file stayed invisible to the whole tool -- no files row, a
404 from GET /files/:path, nothing in the tree. Expectations here are what
`git check-ignore` reports for the same fixtures.
"""
from __future__ import annotations

import os
import tempfile

from auditview.core.scanner import scan_folder

_SHM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


def _tree(root, files):
    for rel, text in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text)


def _scan(files, exclusion_patterns=""):
    with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
        _tree(tmpdir, files)
        return set(scan_folder(tmpdir, exclusion_patterns))


def test_nested_gitignore_negation_reincludes():
    """git check-ignore: sub/keep.log tracked, sub/other.log and root.log ignored."""
    paths = _scan({
        ".gitignore": "*.log\n",
        "sub/.gitignore": "!keep.log\n",
        "sub/keep.log": "x\n",
        "sub/other.log": "x\n",
        "root.log": "x\n",
        "app.py": "a = 1\n",
    })
    assert "sub/keep.log" in paths
    assert "sub/other.log" not in paths
    assert "root.log" not in paths
    assert "app.py" in paths


def test_shallow_rule_still_applies_without_a_deeper_opinion():
    """A deeper .gitignore that says nothing about the path must not shadow the parent."""
    paths = _scan({
        ".gitignore": "*.log\n",
        "sub/.gitignore": "*.tmp\n",
        "sub/a.log": "x\n",
        "sub/a.tmp": "x\n",
        "sub/a.py": "a = 1\n",
    })
    assert "sub/a.log" not in paths
    assert "sub/a.tmp" not in paths
    assert "sub/a.py" in paths


def test_negation_within_one_file_takes_the_last_word():
    paths = _scan({
        ".gitignore": "*.log\n!keep.log\n",
        "keep.log": "x\n",
        "drop.log": "x\n",
    })
    assert "keep.log" in paths
    assert "drop.log" not in paths


def test_deeper_negation_cannot_reinclude_under_an_ignored_directory():
    """git: 'not possible to re-include a file if a parent directory is excluded'."""
    paths = _scan({
        ".gitignore": "build/\n",
        "build/.gitignore": "!keep.py\n",
        "build/keep.py": "a = 1\n",
        "app.py": "a = 1\n",
    })
    assert not any(p.startswith("build/") for p in paths)
    assert "app.py" in paths


def test_exclusion_patterns_outrank_a_gitignore_negation():
    """POST /purge appends a pattern to exclusion_patterns to keep a path out.

    A .gitignore negation must not be able to resurrect it, or a purge would be
    undone by a file inside the repository it purged from.
    """
    paths = _scan(
        {
            ".gitignore": "!secrets.env\n",
            "secrets.env": "TOKEN=1\n",
            "app.py": "a = 1\n",
        },
        exclusion_patterns="/secrets.env",
    )
    assert "secrets.env" not in paths
    assert "app.py" in paths


def test_default_excludes_survive_a_negation():
    paths = _scan({
        ".gitignore": "!*\n",
        "node_modules/pkg/index.js": "x\n",
        "app.py": "a = 1\n",
    })
    assert not any(p.startswith("node_modules/") for p in paths)
    assert "app.py" in paths


# path_excluded() answers for one path what scan_folder() answers for the tree.
# GET /files/:path uses it to tell "excluded" from "not scanned yet", so the two
# must never disagree, and only path_excluded() is reachable without a scan.
_FIXTURES = [
    ({".gitignore": "*.log\n", "sub/.gitignore": "!keep.log\n",
      "sub/keep.log": "x\n", "sub/other.log": "x\n", "root.log": "x\n", "app.py": "a\n"}, ""),
    ({".gitignore": "build/\n", "build/.gitignore": "!keep.py\n",
      "build/keep.py": "a\n", "build/deep/x.py": "a\n", "app.py": "a\n"}, ""),
    ({".gitignore": "*.log\n!keep.log\n", "keep.log": "x\n", "drop.log": "x\n"}, ""),
    ({"a/b/c.py": "a\n", "a/junk.log": "x\n", "secrets.env": "T=1\n"}, "*.log\n/secrets.env"),
    ({"node_modules/pkg/index.js": "x\n", "app.py": "a\n", "sub/.gitignore": "*\n",
      "sub/hidden.py": "a\n"}, ""),
]


def test_path_excluded_agrees_with_scan_folder():
    from auditview.core.scanner import path_excluded

    for files, patterns in _FIXTURES:
        with tempfile.TemporaryDirectory(dir=_SHM_DIR) as tmpdir:
            _tree(tmpdir, files)
            scanned = set(scan_folder(tmpdir, patterns))
            on_disk = []
            for dirpath, _dirnames, filenames in os.walk(tmpdir):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    on_disk.append(os.path.relpath(full, tmpdir).replace(os.sep, "/"))
            assert on_disk, "fixture produced no files"
            for rel in on_disk:
                # (scan_folder additionally drops symlinks resolving outside the
                # root, which path_excluded does not model; no fixture uses one.)
                assert path_excluded(tmpdir, rel, patterns) == (rel not in scanned), (
                    f"disagreement on {rel!r} with patterns {patterns!r}"
                )
