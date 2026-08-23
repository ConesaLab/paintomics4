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

## Item 6: Step 3 tabs + folded enrichment table (2026-08-24)

Verified in Chrome against job 1lqj2HS2zt on the worktree server (port 8024):

- `step3-tabs-pathways.jpg` — the five-tab layout (Metabolites absent for a
  job with no compound layer, by design); enrichment table folded to the top
  20 by the selected combined method with the footer
  "Showing the 20 most significant of 774 … Show all 774".
- `step3-tabs-regulation.jpg` — the Regulation tab: MORE table + the
  regulator-target network DRAWN (370 nodes; its cytoscape canvas measured
  0x0 until the tab-activate resize hook landed).
- Row expansion shows per-omic matched/relevant/p + combined methods.
- Search "insulin" un-folds (7 matches across all 774; footer says so);
  clearing refolds to 20. Show all / top-20 toggle verified.
- Data & mapping tab: Highcharts donut + boxplot sized right on first
  activation (global reflow hook).
- `?guides=1` HUD: 0 off-rail, 0 baseline strays on all four tabs
  (68/312/11/11 elements measured).
- Metabolites tab: verified ABSENT on a compound-less job; no local job has
  compounds + completed Step 3, so presence-rendering rides the same
  activate hooks and is exercised by the item-5 smoke.
