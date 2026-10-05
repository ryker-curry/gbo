"""Every page loads and no file uses a name that doesn't exist (the kind of
bug that crashed Hitter Profile in Oct 2026)."""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {"ven", "__pycache__", ".git", "prev", "_style_preview", "Claude outputs", "tests"}


def test_app_imports():
    import app  # noqa: F401  (shiny_app/app.py -- imports every module)


def _py_files():
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def test_no_undefined_names():
    out = subprocess.run([sys.executable, "-m", "pyflakes", *_py_files()], capture_output=True, text=True).stdout
    bad = [line for line in out.splitlines() if "undefined name" in line]
    assert not bad, "Undefined names:\n" + "\n".join(bad)
