from pathlib import Path
import shutil
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist
from distutils.errors import DistutilsExecError


ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
UI_DIST = UI_DIR / "dist"
STATIC_DIR = ROOT / "auditview" / "static"


def _has_static_bundle():
    return (STATIC_DIR / "index.html").is_file()


def _require_static_bundle(reason):
    if _has_static_bundle():
        print(f"Skipping UI build: {reason}; using existing {STATIC_DIR}")
        return
    raise DistutilsExecError(
        f"Cannot build UI: {reason}, and {STATIC_DIR} does not contain a built UI. "
        "Install node and pnpm, then run `pnpm --dir ui build`."
    )


def _build_ui():
    if not UI_DIR.is_dir():
        _require_static_bundle(f"{UI_DIR} is missing")
        return

    missing = [tool for tool in ("node", "pnpm") if shutil.which(tool) is None]
    if missing:
        _require_static_bundle(f"missing required executable(s): {', '.join(missing)}")
        return

    print("Building UI with pnpm")
    subprocess.run(["pnpm", "build"], cwd=UI_DIR, check=True)

    if not (UI_DIST / "index.html").is_file():
        raise DistutilsExecError(f"UI build did not create {UI_DIST / 'index.html'}")

    if STATIC_DIR.exists():
        shutil.rmtree(STATIC_DIR)
    shutil.copytree(UI_DIST, STATIC_DIR)
    print(f"Copied built UI from {UI_DIST} to {STATIC_DIR}")


class build_py(_build_py):
    def run(self):
        _build_ui()
        super().run()


class sdist(_sdist):
    def run(self):
        _build_ui()
        super().run()


setup(
    cmdclass={
        "build_py": build_py,
        "sdist": sdist,
    }
)
