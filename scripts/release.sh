#!/bin/bash
# Build release artifacts for the version in pyproject.toml, verify the commit
# stamp embedded in them, then tag the commit.
#
# Does not push and does not publish -- it prints those commands for you to run.
# Bump the version first with `uv version --bump patch` (which also refreshes
# uv.lock) and commit that, then run this.
#
# Usage: ./scripts/release.sh [--allow-dirty] [--skip-tests] [-y|--yes]

# Unlike the dev-* supervisors, a release must not continue past a failed step.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DIR")"
cd "$ROOT"

ALLOW_DIRTY=0
SKIP_TESTS=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --allow-dirty) ALLOW_DIRTY=1 ;;
        --skip-tests)  SKIP_TESTS=1 ;;
        -y|--yes)      ASSUME_YES=1 ;;
        *) echo "Error: unknown argument: $arg" >&2; exit 2 ;;
    esac
done

die()  { echo "Error: $*" >&2; exit 1; }
step() { echo "-- $* --"; }

# -- Preflight: tools -------------------------------------------------------
for tool in uv git python3; do
    command -v "$tool" >/dev/null || die "$tool is not on PATH."
done
# node/pnpm are release-critical, not optional: setup.py's
# _require_static_bundle() silently reuses a stale auditview/static/ when they
# are missing, so a release built without them ships an old frontend with
# nothing but a printed warning.
for tool in node pnpm; do
    command -v "$tool" >/dev/null \
        || die "$tool is not on PATH; the UI would not be rebuilt and this release would ship a stale auditview/static/."
done
[ -d "$ROOT/ui" ] || die "$ROOT/ui is missing; the UI would not be rebuilt."

# -- Preflight: identity ----------------------------------------------------
git rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout."
HEAD_SHA="$(git rev-parse HEAD)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
VERSION="$(uv version --short --frozen)"
[ -n "$VERSION" ] || die "uv version --short returned nothing."
case "$VERSION" in
    *+*) die "version $VERSION carries a local segment; PyPI would reject it." ;;
esac
TAG="v$VERSION"

# `cmd && die ...` would abort the script under `set -e` on the *success* path
# (tag absent -> non-zero), so every guard is written as an if.
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    die "tag $TAG already exists (at $(git rev-parse --short "$TAG")). Bump the version, or delete the tag."
fi
# A tag already pushed to a remote is the expensive mistake. Best effort:
# GIT_TERMINAL_PROMPT=0 so an unreachable or authenticated remote fails fast
# instead of blocking on a credential prompt.
for remote in $(git remote); do
    if ! out="$(GIT_TERMINAL_PROMPT=0 git ls-remote --tags "$remote" "refs/tags/$TAG" 2>/dev/null)"; then
        echo "Warning: could not reach remote '$remote' to check for $TAG." >&2
        continue
    fi
    [ -z "$out" ] || die "tag $TAG already exists on remote '$remote'."
done

# -- Preflight: tree state --------------------------------------------------
# Tracked files only, matching the DIRTY rule in setup.py: dist/ and the
# .claude/worktrees/ copies live inside the tree and are not real dirtiness.
if [ "$ALLOW_DIRTY" -eq 0 ]; then
    dirty="$(git status --porcelain --untracked-files=no)"
    if [ -n "$dirty" ]; then
        echo "$dirty" >&2
        die "working tree has uncommitted changes (commit the version bump first, or pass --allow-dirty)."
    fi
fi
# The hole that tracked-only dirtiness leaves: an untracked .py under auditview/
# would be packaged by build_py's glob, and an untracked source under ui/ could
# be bundled by Vite, without either file being in the tagged commit.
# auditview/static/, ui/dist/, node_modules/ and _build_info.py are gitignored,
# so anything reported in these source trees is stray.
stray="$(git status --porcelain --untracked-files=all -- auditview ui | grep '^??' || true)"
if [ -n "$stray" ]; then
    echo "$stray" >&2
    die "untracked files under auditview/ or ui/ would be packaged; commit or remove them."
fi

# uv.lock drifted behind pyproject on both prior releases (see 0fa09f7).
step "checking uv.lock against pyproject.toml"
uv lock --check || die "uv.lock is out of date with pyproject.toml (run 'uv lock' and commit it)."

step "installing frozen UI dependencies"
pnpm --dir "$ROOT/ui" install --frozen-lockfile \
    || die "UI dependencies do not match ui/pnpm-lock.yaml."

step "checking third-party license notices"
pnpm --dir "$ROOT/ui" licenses:check \
    || die "THIRD_PARTY_LICENSES.txt is stale (run 'pnpm --dir ui licenses:generate' and commit it)."

if [ "$SKIP_TESTS" -eq 0 ]; then
    step "running backend tests"
    # addopts already deselects the fuzz suite.
    uv run --frozen pytest -q || die "backend tests failed (pass --skip-tests to override)."

    step "running frontend tests"
    pnpm --dir "$ROOT/ui" test \
        || die "frontend tests failed (pass --skip-tests to override)."

    step "linting frontend"
    pnpm --dir "$ROOT/ui" lint \
        || die "frontend lint failed (pass --skip-tests to override)."
fi

# -- Confirm ----------------------------------------------------------------
echo
echo "  version   $VERSION"
echo "  tag       $TAG   (created last, only if the build verifies)"
echo "  branch    $BRANCH"
echo "  commit    $(git rev-parse --short=12 HEAD)  $(git log -1 --pretty=%s)"
echo "  remotes   $(git remote | tr '\n' ' ')"
echo
if [ "$ASSUME_YES" -eq 0 ]; then
    [ -t 0 ] || die "stdin is not a terminal; pass --yes to skip the confirmation."
    printf "Build and tag? [y/N] "
    read -r reply
    case "$reply" in y|Y|yes|YES) ;; *) die "aborted." ;; esac
fi

# -- Build ------------------------------------------------------------------
# Wipe dist/ so `make publish` (bare `uv publish`) cannot upload an artifact
# from an older version, and build/ so no stale build/lib copy wins on mtime.
step "building"
rm -rf "$ROOT/dist" "$ROOT/build"
uv build   # sdist from this tree, then the wheel from the unpacked sdist

SDIST="$ROOT/dist/auditview-$VERSION.tar.gz"
WHEEL="$ROOT/dist/auditview-$VERSION-py3-none-any.whl"
[ -f "$SDIST" ] || die "expected $SDIST; dist/ holds: $(ls "$ROOT/dist")"
[ -f "$WHEEL" ] || die "expected $WHEEL; dist/ holds: $(ls "$ROOT/dist")"
# Count distributions only: uv also drops a dist/.gitignore.
count="$(find "$ROOT/dist" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) | wc -l | tr -d ' ')"
[ "$count" -eq 2 ] || die "dist/ holds $count distributions, expected 2: $(ls "$ROOT/dist")"

# -- Verify the embedded stamp ----------------------------------------------
step "verifying artifacts"
python3 - "$SDIST" "$WHEEL" "$VERSION" "$HEAD_SHA" "$ALLOW_DIRTY" <<'PY'
import sys, tarfile, zipfile

sdist, wheel, version, head, allow_dirty = sys.argv[1:6]
allow_dirty = allow_dirty == "1"
member = f"auditview-{version}/auditview/_build_info.py"

with tarfile.open(sdist) as tf:
    f = tf.extractfile(member)
    if f is None:
        sys.exit(f"Error: {member} is missing from {sdist}")
    s = f.read().decode()

with zipfile.ZipFile(wheel) as zf:
    names = set(zf.namelist())
    for required in ("auditview/_build_info.py", "auditview/static/index.html"):
        if required not in names:
            sys.exit(f"Error: {required} is missing from {wheel}")
    w = zf.read("auditview/_build_info.py").decode()

# Byte-identity is the real proof that the wheel step reused the sdist's stamp
# instead of regenerating it in a checkout that has no .git.
if s != w:
    sys.exit("Error: sdist and wheel stamps differ (the wheel build clobbered "
             f"the stamp):\n--- sdist\n{s}--- wheel\n{w}")

ns = {}
exec(compile(w, "_build_info.py", "exec"), ns)   # our own generated literals

problems = []
if ns.get("VERSION") != version:
    problems.append(f"stamp VERSION={ns.get('VERSION')!r} != pyproject {version!r}")
if ns.get("COMMIT") != head:
    problems.append(f"stamp COMMIT={ns.get('COMMIT')!r} != HEAD {head!r}")
if ns.get("DIRTY") is None:
    problems.append("stamp carries no git info (DIRTY is None)")
elif ns["DIRTY"] and not allow_dirty:
    problems.append("stamp says the source tree was dirty")
if problems:
    sys.exit("Error: " + "; ".join(problems))

print(f"  stamp ok  version={ns['VERSION']} commit={ns['COMMIT'][:12]} "
      f"dirty={ns['DIRTY']} built={ns.get('BUILD_TIME')}")
PY

# -- Tag --------------------------------------------------------------------
# Tag the SHA captured at preflight, not HEAD: the build takes minutes and HEAD
# may have moved. Annotated, so tagger and date are recorded.
step "tagging"
git tag -a "$TAG" -m "auditview $VERSION" "$HEAD_SHA"
echo "ok  $TAG -> $(git rev-parse --short=12 "$TAG^{commit}")"

echo
echo "Built:"
echo "  $(basename "$SDIST")"
echo "  $(basename "$WHEEL")"
echo
echo "Next steps (not run by this script):"
for remote in $(git remote); do
    echo "  git push $remote HEAD && git push $remote $TAG"
done
echo "  make publish        # uv publish -- uploads what is in dist/"
