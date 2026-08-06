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
