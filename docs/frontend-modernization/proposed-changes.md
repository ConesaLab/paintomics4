# Proposed changes to files owned by another agent

Changes the frontend-modernization work needs but cannot make itself, because the
file is on the do-not-touch list. Each entry gives the file, line, proposed diff
and rationale so the owning agent can apply or reject it.

---

## 1. `PaintomicsClient/public_html/index.html:38` — cookieconsent loaded from a public CDN

**Status:** open
**Raised:** iteration 1 (branch `frontend-modernization`)

### Current

```html
<link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/cookieconsent@3/build/cookieconsent.min.css" />
```

### Rationale

This is the only remaining external-CDN asset in the page head; every other
stylesheet (ExtJS Neptune, Font Awesome, dragula, jQuery UI, tooltipster,
odometer) is already vendored under `js/libs/` or `resources/`. It matters for
three reasons:

1. **Hard constraint.** The modernization brief forbids external CDNs — assets
   must be local and inlined or vendored.
2. **Availability.** PaintOmics is deployed inside CSIC infrastructure. Any
   egress restriction or jsdelivr outage leaves the cookie banner unstyled while
   the rest of the page renders, which looks like a broken deployment.
3. **Privacy.** A third-party request fires on every page load, before the user
   has answered the cookie banner the asset is styling.

### Proposed diff

Vendor the file (it is ~3 KB minified) and point at the local copy:

```diff
--- a/PaintomicsClient/public_html/index.html
+++ b/PaintomicsClient/public_html/index.html
@@ -38 +38 @@
-	<link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/cookieconsent@3/build/cookieconsent.min.css" />
+	<link rel="stylesheet" type="text/css" href="js/libs/cookieconsent/cookieconsent.min.css" />
```

Check whether the matching `cookieconsent.min.js` is also loaded from the CDN
further down the page; if so it needs vendoring in the same commit, otherwise the
banner styling and behaviour drift apart.

### Notes

Vendoring the asset itself (creating `js/libs/cookieconsent/`) is inside this
agent's remit — new files are owned by it. Only the one-line `href` change in
`index.html` needs the owning agent. Say the word and the vendored file will be
added so the diff above becomes a one-line apply.

---

## 2. Three WCAG AA contrast failures outside this branch's ownership

**Status:** open
**Raised:** iteration 2 (branch `frontend-modernization`)

A contrast audit of the live Step 1 page found 16 distinct failing
colour pairs. Thirteen were fixed in `main.css`. These three cannot be, because
the colour is not defined in a file this branch owns. Ratios are measured
against the actual rendered background, and all three carry normal-weight text
below 18.66px, so the AA threshold is 4.5:1.

| Colour | Used for | On | Ratio | Needs | Defined in |
|---|---|---|---|---|---|
| `#4a90d9` fill, white text | "AI Interpret" button | — | 3.34:1 | 4.5:1 | `PA_Step1Views.js` |
| `#e65100` text | "sends analysis summaries to external AI service" | `#ffffff` | 3.79:1 | 4.5:1 | `PA_Step1Views.js` |
| `#3892d3` fill, white text | ExtJS `Browse...` split buttons | — | 3.38:1 | 4.5:1 | vendored ExtJS Neptune theme |

### Proposed fixes

**`PA_Step1Views.js`** — darken both values along the same hue. These clear AA
with headroom and are visually near-indistinguishable from the originals:

```diff
-  #4a90d9   /* AI Interpret button fill, 3.34:1 */
+  #2F73BC   /* 4.88:1 */

-  #e65100   /* warning text, 3.79:1 */
+  #C44500   /* 5.00:1 */
```

**ExtJS `Browse...` button** — the `#3892d3` fill lives in
`js/libs/extjs/resources/ext-theme-neptune/ext-theme-neptune-all.css`, a
vendored third-party theme. Editing vendored files is out of scope here and
would be lost on any ExtJS upgrade. Two options, in order of preference:

1. Override it from `main.css` (which loads after the theme) with
   `.x-btn-default-small { background-color: #287AB6; }`. Deliberately *not*
   done in this branch: `x-btn-default-small` is a broad theme class applied to
   many buttons across every screen, Neptune styles its hover/pressed/disabled
   states separately, and a background-only override risks leaving those states
   visually inconsistent. It needs its own change with verification across
   Steps 1-4, not a drive-by edit inside a contrast pass.
2. Leave as-is and accept the 3.38:1. Note it still clears the 3:1 bar for
   non-text UI components, so only the button *label* is non-conformant.

---

## Not a proposed change, but worth recording

`JobController.js:1329` logs `Error saving data with IndexDB in store: jobs`
whenever the `paintomics` IndexedDB database is deleted while the app is open -
which is exactly what the verification procedure for this branch asks for
(clear sessionStorage and IndexedDB before each test run). The app does not
re-create its object stores, so the first save after a cache clear always
fails. It is harmless for the flows tested here and unrelated to any CSS
change, but it does mean a genuine IndexedDB fault would be easy to miss.

`JobController.js:51` (`checkJobStatus`) polls `check_job_status/<jobID>` every
5s. That endpoint reports on the *queue*, and a finished job is removed from the
queue - so if the job completes between two polls, the next poll gets
`{"status": "failed", "message": "Your job is not on the queue anymore..."}` and
the UI shows a red "Oops..Internal error!" for a job that actually succeeded.
Hit once during iteration 3 verification: job `03Eb3w4BGX` reported the error,
but loading `/?jobID=03Eb3w4BGX` showed a complete Step 2 and went on to render
Step 3 with the expected 888/44. Distinguishing "finished" from "died" needs a
completion check before treating a dequeued job as failed. Out of scope here
(`JobController.js` is owned elsewhere) but it makes a passing run look broken.

---

## 3. `pa_recover_job` crashes on a missing jobID and locks the whole UI

**Status:** open (backend - outside this branch's frontend scope)
**Raised:** iteration 4 (branch `frontend-modernization`)

`PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py:580`:

```python
jobID = formFields.get("jobID")
logging.info("RECOVER_JOB - LOADING JOB " + jobID + "...")
```

`formFields.get` returns `None` when the field is absent, and `str + None`
raises. Reproduced directly:

```
$ curl -sk -X POST https://localhost:8443/pa_recover_job
{"success": false, "message": "TypeError: AT PathwayAcquisitionServlet.py:
 pathwayAcquisitionRecoverJob. ERROR MESSAGE: can only concatenate str
 (not \"NoneType\") to str", "extra": {"exc_line": "580", ...}}
HTTP 400
```

This is not cosmetic. The client calls `pa_recover_job` during start-up, so
when it fires without a usable jobID the 400 surfaces as a full-screen
"Oops..Internal error!" dialog and **Step 1 never renders at all** - the
application is unusable until browser storage is cleared. Hit during iteration
4 verification; recovering required clearing `localStorage` in addition to the
`sessionStorage` + IndexedDB that the branch's test procedure already
prescribes. The dialog's own advice ("clear your web cache in your browser")
is in fact the workaround, which suggests this is a known-but-unfixed rough
edge.

Two independent fixes, both cheap:

1. Guard the log line and reject cleanly, rather than throwing:
   ```diff
   -		logging.info("RECOVER_JOB - LOADING JOB " + jobID + "...")
   +		if not jobID:
   +			response.setContent({"success": False, "message": "No job ID supplied."})
   +			return response
   +		logging.info("RECOVER_JOB - LOADING JOB %s ...", jobID)
   ```
   Using `%s` formatting also makes the line immune to this class of bug.
2. Have the client skip the recover call entirely when it has no jobID to
   recover, so a cold start never hits the endpoint.

---

## 4. Contrast failures on Steps 3 and 4 that live in JS view files

**Status:** open
**Raised:** iteration 5 (branch `frontend-modernization`)

Entry 2 covered Step 1 only. Auditing Steps 3 and 4 for the first time found 20
further failing pairs; 12 were fixed in `main.css`, and these 8 cannot be,
because the colour is set in a view file this branch does not own. All are
normal-weight text under 18.66px, so the bar is 4.5:1.

### `PA_Step3Views.js` - database and kingdom badge letters

The single-letter badges in the pathway grid. `R` alone renders 524 times on a
default Step 3, so this is high-volume, not incidental.

| Letter | Current | On white | Suggested | New |
|---|---|---|---|---|
| R (Reactome) | `#4cd964` | 1.84:1 | `#1D872F` | 4.61:1 |
| K (KEGG) | `#007aff` | 4.02:1 | `#0071EC` | 4.59:1 |
| M (MapMan) | `#5ac8fb` | 1.89:1 | `#047CB4` | 4.62:1 |
| H | `#ffcd02` | 1.50:1 | `#8E7200` | 4.61:1 |
| O | `#c644fc` | 3.73:1 | `#B817FB` | 4.61:1 |
| G | `#ff2d55` | 3.65:1 | `#EB002D` | 4.59:1 |

Each suggestion keeps the original hue and saturation and moves lightness only,
so the badges stay mutually distinguishable. `#ffcd02` is the awkward one - no
yellow carries 4.5:1 as text on white, so it necessarily reads as dark gold; if
that is unacceptable, give that badge a filled chip with dark text instead.

### `PA_Step4Views.js` - inline panel fills

Both are set as inline `style="background: ..."` on the element, so `main.css`
cannot reach them without an attribute-selector hack.

| Element | Current fill | White label | Suggested | New |
|---|---|---|---|---|
| "History" button | `#d66379` | 3.55:1 | `#CD435D` | 4.61:1 |
| "Pathway information" panel header | `#5bc0de` | 2.09:1 | `#1F7F9B` | 4.60:1 |

Note for whoever picks this up: **do not** instead darken the shared
`.lateralOptionsPanel-header h2` ink in `main.css`. The sibling "Download"
header is filled `#337ab7`, where white already passes at 4.56:1; switching
that h2 to dark ink would drop it to 3.73:1 and break a currently-conformant
header to fix a different one. The fill is the right thing to change, and only
for the cyan panel.
