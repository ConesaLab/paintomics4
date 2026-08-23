"""Render one fixture figure at boot, so a deploy proves its renderer works.

Why this exists
---------------
The figure pipeline failed on every production render for months --
``sys.executable`` under uWSGI is the uwsgi binary -- and nothing said so
until a user's report carried RENDER FAILED where its panels should be. The
interpreter probe (``PythonExecutable``) now catches that particular impostor
at boot, but a probe that imports matplotlib is still not a render: fonts,
cache directories, rlimits and the sandbox environment can each break on a new
box in their own way.

Set ``AI_FIGURE_SELFCHECK=1`` (systemd drop-in, shell, CI) and the server
renders one tiny fixture bundle through the REAL pipeline -- template writer,
subprocess sandbox, resolved interpreter -- into
``CLIENT_TMP_DIR/figure-selfcheck/``, and puts the verdict in the boot log:

    figure self-check: PASS -- rendered figure.png/svg/pdf in 1.8s under
    /path/to/python3 (bundle: .../figure-selfcheck/latest)

The fixture data is synthetic and says so in its legend; nothing about it
enters any job. Off by default: a production boot should not spend two seconds
rendering unless its operator asked for the proof.
"""
from __future__ import annotations

import logging
import os
import shutil
import time

logger = logging.getLogger(__name__)

# A slice in the exact shape make_figure resolves from a job: two features,
# three conditions. Small enough to render in about a second, real enough to
# exercise fonts, axes, legend and every output format.
_SLICE = {
    "conditions": ["T0", "T1", "T2"],
    "features": [
        {"id": "SELFCHECK-A|probe", "label": "SELFCHECK-A", "omic": "probe",
         "values": [0.0, 1.0, 0.5]},
        {"id": "SELFCHECK-B|probe", "label": "SELFCHECK-B", "omic": "probe",
         "values": [1.0, 0.2, 0.8]},
    ],
    "colours": {},
    "pathways": [],
}

_SPEC = {"archetype": "timecourse", "title": "Renderer self-check",
         "conclusion": "SYNTHETIC self-check data - not from any job.",
         "width": "single", "has_negative": False, "centre_zero": None,
         "n": 2, "test": None}


def run_selfcheck():
    """Render the fixture; return the one-line verdict for the boot log."""
    from src.conf.serverconf import CLIENT_TMP_DIR
    from src.classes.AIInterpret import figure_sandbox, figure_templates
    from src.common.PythonExecutable import resolve

    started = time.time()
    bundle = os.path.join(CLIENT_TMP_DIR, "figure-selfcheck", "latest")
    # A previous verdict must never be readable as this boot's: start clean.
    shutil.rmtree(bundle, ignore_errors=True)
    os.makedirs(bundle, exist_ok=True)

    data_tsv, script, legend = figure_templates.build_timecourse(_SLICE, _SPEC)
    for name, content in (("data.tsv", data_tsv), ("figure.py", script),
                          ("legend.md", legend)):
        with open(os.path.join(bundle, name), "w") as fh:
            fh.write(content)

    result = figure_sandbox.render(bundle, timeout=60)
    produced = sorted(f for f in os.listdir(bundle)
                      if f.startswith("figure.") and f != "figure.py")
    seconds = time.time() - started

    if result.ok and produced:
        verdict = ("figure self-check: PASS -- rendered %s in %.1fs under %s "
                   "(bundle: %s)" % ("/".join(produced), seconds, resolve(),
                                     bundle))
        logger.info(verdict)
    else:
        verdict = ("figure self-check: FAIL -- rc=%s after %.1fs under %s; "
                   "see %s (stderr: %s)"
                   % (result.returncode, seconds, resolve(),
                      os.path.join(bundle, "render.log"),
                      (result.stderr_tail or "")[-300:]))
        logger.error(verdict)
    return verdict


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(run_selfcheck())
