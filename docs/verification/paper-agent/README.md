# Paper Agent — verification evidence

## Item 1: one figure rendered under uWSGI (2026-08-23)

The app was booted with `uwsgi` (processes=1, threads=4, lazy-apps — the
production shape) from the venv whose `uwsgi` binary is `sys.executable`
inside the workers, with `AI_FIGURE_SELFCHECK=1`.

- `uwsgi-boot.log` — the worker says `sys.executable is .../bin/uwsgi (not a
  Python); probing beside it`, resolves `.../bin/python3`, and the self-check
  renders `figure.pdf/png/svg` through the real sandbox (PASS, ~9 s).
- `uwsgi-rendered-figure.png` — the PNG the uWSGI worker's sandbox produced.
- `uwsgi-figure-render-chrome.jpg` — Chrome showing that PNG **served by the
  uWSGI app** at `/CLIENT_TMP/figure-selfcheck/latest/figure.png` (HTTP 200).

Before the `PythonExecutable` fix this exact configuration failed every
render with rc=-1: the sandbox exec'd the uwsgi binary as if it were Python.
