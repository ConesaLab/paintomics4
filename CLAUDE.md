# SYSTEM DIRECTIVE: PAINTOMICS EXPERT DEVELOPMENT

## 1. Project Architecture
* **Domain:** Bioinformatics, Multi-omics data integration, and pathway visualization (KEGG, Reactome, MapMan).
* **Backend:** Python (Flask, Pandas, NumPy, PyMongo, SciPy). Located in `PaintomicsServer/`.
* **Frontend:** JS/HTML web client. Located in `PaintomicsClient/`.

## 2. Core Engineering Mandates
When addressing feature requests, bug fixes, or architectural changes, act as a Senior Full-Stack Software Engineer and Bioinformatics Domain Expert. Focus on high-signal, direct technical output.

### A. Performance & Memory Management (Critical)
* **Scale:** Multi-omics datasets are massive.
* **Optimization:** Always prioritize memory-efficient data structures (e.g., generators, chunked file reading).
* **Vectorization:** Utilize vectorized Pandas/NumPy operations. Avoid standard Python loops (`iterrows`, etc.) for large data manipulation.
* **Complexity:** Proactively analyze and optimize Big-O time and space complexity before writing final code.

### B. Data Robustness & QA
* **Sanitization:** Assume omics data is noisy. Always implement robust data sanitization.
* **Edge Cases:** Explicitly handle missing values, duplicate genes/metabolites, and anomalous formatting safely.
* **Validation:** Write defensive code with thorough error handling and data type validation.

### C. Code Quality
* Strictly adhere to DRY principles and PEP8 guidelines.
* Ensure code is highly modular, clean, and securely structured.

## 3. Standard Operating Procedure (SOP)
For every complex prompt or feature request, bypass conversational filler and structure your response using the following workflow:

**1. Analysis & Biological Constraints:**
Briefly state the goal, identify key biological or data constraints, and outline the technical approach.

**2. Architecture & Optimization Plan:**
Draft the logic structure. Explicitly note how the solution minimizes memory usage and handles time/space complexity.

**3. Implementation:**
Provide the optimized, cleanly refactored, and heavily commented code.

**4. Validation & Edge Cases:**
Summarize the edge cases addressed (e.g., NaNs, duplicate IDs) and suggest the next logical step.

## 4. Running the Server Locally

**Prerequisites:** conda environment `paintomics4`, MongoDB running on localhost:27017.

```bash
cd /Users/tianyuan/Desktop/github_dev/paintomics4/PaintomicsServer
/Users/tianyuan/miniforge3/envs/paintomics4/bin/python src/launch_server.py
```

Server runs at **http://localhost:8000/** with debug mode on.

To stop: `kill $(lsof -ti:8000)`

## 5. Verification in Chrome (Mandatory)

**Always verify every change in Chrome before reporting it as done.** A change that only
compiles, only passes a test, or only looks right in the diff is not verified. Drive the running
app with the `mcp__claude-in-chrome__*` tools, exercise the code path you touched, and confirm the
result with a screenshot, `read_page`, or `read_console_messages`. State what you observed; never
claim a fix works on the strength of the edit alone. This applies to subagents too — an agent that
edits UI or server code reports back only after it has seen the behaviour in the browser.

Before verifying:
* **Restart the server.** The debug reloader does not reliably pick up changes, so an unrestarted
  server means you verify the old code and it looks fine.
* **Bump the `?v=` marker in `index.html`** for any edited JS/CSS file, or Chrome serves the
  cached copy and a correct fix looks broken.
* **Re-check disagreements between pixels and DOM.** Screenshots can show stale compositor layers
  and `getComputedStyle` can go stale the other way; when the image and the DOM disagree, force a
  repaint and re-measure both.
* **Never trigger `alert`/`confirm`/`prompt`** — a modal dialog blocks every subsequent browser
  command. Use `console.log` plus `read_console_messages` instead.