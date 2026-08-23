"""Which Python renders figures — because under uWSGI it is NOT sys.executable.

The figure sandbox runs each bundle's `figure.py` as ``[interpreter, "-I",
"figure.py"]``. On the development server (`launch_server.py`) the obvious
interpreter — ``sys.executable`` — is a real Python and everything works. Under
uWSGI it is the **uwsgi binary itself**: uWSGI embeds libpython and sets
``sys.executable`` to its own path, so every render exec'd the web server as if
it were Python, got its argument parser instead, and died with rc=-1. In
production every AI figure failed with RENDER FAILED while every local Chrome
verification, done against `launch_server.py`, looked fine.

This module picks an interpreter that can actually render, once, and says how
it chose. Candidates, in order:

  1. ``PYTHON_EXECUTABLE`` from serverconf (or the environment) — the operator
     override, absolute path to an interpreter.
  2. ``sys.executable`` — right on the dev server; skipped when its basename
     does not look like a Python (the uWSGI case).
  3. ``dirname(sys.executable)/python3`` — under uWSGI-in-a-venv the uwsgi
     binary sits in ``<venv>/bin`` next to the venv's python3. This is the UV
     layout (venv310/venv-py311 + `uWSGI` pip install).
  4. ``sys.base_prefix + /bin/python3`` and ``sys.prefix + /bin/python3`` —
     the interpreter uWSGI was built against, when uwsgi lives elsewhere.
  5. ``shutil.which("python3")`` — last resort; whatever PATH says.

A candidate wins by **probing**: it must run ``-I -c "import matplotlib"`` and
exit 0, because "is a Python" is not the requirement — "can render a figure"
is. If no candidate has matplotlib, the first candidate that at least runs
``-I -c "pass"`` is returned with a logged warning, so the render fails in the
child with a legible ImportError in render.log instead of failing here with a
None. The probe runs once per process; the result is cached.

Call :func:`resolve` for the path, :func:`describe` for the one-line story to
log at start-up — a deploy where figures cannot render should say so in the
boot log, not at the first user figure.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

# Existing deployments carry a conf/serverconf.py written before this setting
# existed; a bare import would take the server down at boot for a name that is
# merely absent.
try:
    from src.conf.serverconf import PYTHON_EXECUTABLE as _CONFIGURED
except ImportError:                                   # pragma: no cover
    _CONFIGURED = ""

_PROBE_TIMEOUT = 20        # first matplotlib import builds a font cache
_RENDER_PROBE = "import matplotlib"
_RUNS_PROBE = "pass"

_cached = None             # (path, story) after the first resolve


def _candidates():
    """The ordered, de-duplicated list of interpreter paths worth probing."""
    out = []

    configured = (_CONFIGURED or os.getenv("PYTHON_EXECUTABLE") or "").strip()
    if configured:
        out.append((configured, "serverconf PYTHON_EXECUTABLE"))

    exe = sys.executable or ""
    base = os.path.basename(exe).lower()
    if exe and base.startswith("python"):
        out.append((exe, "sys.executable"))
    elif exe:
        # The uWSGI case: sys.executable exists but is not a Python. Its
        # directory is still the best hint we have — a venv's bin/.
        logger.info("PythonExecutable: sys.executable is %r (not a Python); "
                    "probing beside it", exe)

    if exe:
        out.append((os.path.join(os.path.dirname(exe), "python3"),
                    "python3 beside sys.executable"))
    for prefix in (sys.base_prefix, sys.prefix):
        if prefix:
            out.append((os.path.join(prefix, "bin", "python3"),
                        "sys prefix bin/python3"))
    which = shutil.which("python3")
    if which:
        out.append((which, "python3 on PATH"))

    seen, unique = set(), []
    for path, how in out:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        unique.append((path, how))
    return unique


def _probe(path, code):
    """True when `path -I -c code` exits 0. Never raises."""
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return False
    try:
        proc = subprocess.run(
            [path, "-I", "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"MPLBACKEND": "Agg",
                 "MPLCONFIGDIR": os.getenv("MPLCONFIGDIR", "/tmp/.mplprobe"),
                 "PATH": os.getenv("PATH", "")},
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return proc.returncode == 0


def resolve():
    """The interpreter path the figure sandbox should exec. Cached."""
    global _cached
    if _cached is None:
        _cached = _resolve_uncached()
    return _cached[0]


def describe():
    """One line for the boot log: which interpreter, chosen how, render-ready?"""
    resolve()
    return _cached[1]


def reset_cache_for_tests():
    global _cached
    _cached = None


def _resolve_uncached():
    cands = _candidates()

    for path, how in cands:
        if _probe(path, _RENDER_PROBE):
            story = ("figure renderer: %s (%s; matplotlib imports)"
                     % (path, how))
            logger.info("PythonExecutable: %s", story)
            return path, story

    for path, how in cands:
        if _probe(path, _RUNS_PROBE):
            story = ("figure renderer: %s (%s; WARNING: matplotlib does NOT "
                     "import — every figure render will fail; pip install "
                     "matplotlib into this interpreter or set "
                     "PYTHON_EXECUTABLE in serverconf)" % (path, how))
            logger.warning("PythonExecutable: %s", story)
            return path, story

    # Nothing probed as a working Python. Return sys.executable so the render
    # fails where render.log can record it, and say why here.
    story = ("figure renderer: %s (fallback: NO candidate ran as a Python — "
             "probed %s)" % (sys.executable,
                             ", ".join(p for p, _ in cands) or "none"))
    logger.error("PythonExecutable: %s", story)
    return sys.executable, story


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(describe())
