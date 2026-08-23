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

## Items 5 + 7: Paper agent smoke + PA_PaperView (2026-08-24)

Two live runs through the real gateway, stored in `paperCollection` (and the
DAO's paper_* keys the UI polls):

- **stategra-multiomics** (5 omics + metabolites, job 15525y735k):
  `smoke-paper-stategra-multiomics.md`. 31 s. 45 facts substituted; the gate
  killed 3 sentences for unledgered numbers; figures QA-clean; specialist
  contracts receipted in stored notes (evidence = tool results). Rubric
  (stategra-v4, deterministic prescreen only — a lower bound; no LLM judge):
  **16.5–17.0 / 46 (~0.36)** across two runs, **zero fabricated claims**
  (both divergence tripwires untouched), beside the interpreter's recorded
  **20.7 / 46** (six tuned rounds, full scoring with judge).
- **stategra-more** (TF + MORE, job 1lqj2HS2zt = the 11-stategra-more data):
  `smoke-paper-stategra-more.md`. 22 s. 63 facts; REGULATES evidence split
  narrated from the graph; network figure QA-clean.

PA_PaperView, all states Chrome-verified on the dev server (restarted, ?v
bumped): `paper-tab-consent.jpg` (consent text + Write the paper; clicking
without job consent is refused server-side), `paper-tab-progress-lanes.jpg`
(queue-driven run through /paper_initiate: lanes tick done/active/pending),
`paper-tab-done-queuerun.jpg` + `paper-tab-manuscript.jpg` (manuscript with
the verification gate line), and the Markdown export button saved
`~/Downloads/paintomics-paper-22447i0A5S.md` (6.8 kB, verified on disk).
`metabolites-tab.jpg`: the Metabolites tab rendering class activity + hub
analysis on a compound-carrying job, 0 off-rail — closing the item-6 caveat.
