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

**Status:** RESOLVED — two applied in iteration 10, the ExtJS `Browse...` button in iteration 12
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

**Applied in iteration 10.** Both `PA_Step1Views.js` values are now `#2F73BC`
(4.88:1) and `#C44500` (5.00:1), verified live at 4.88 and 5.00. A third failure
in the same paragraph, not in the original table, went with them: the
paint-brush mock button was `#ADA6A6` carrying the `.button` default ink
`#E2E2E2`, i.e. 1.85:1. It is now `#756C6C` with white at 5.10:1 - `#756C6C`
being the exact value `main.css` already gives the *real* Paint action in the
grid, so the illustration and the control it illustrates finally agree.

**ExtJS `Browse...` button — applied in iteration 12.** The `#3892d3` fill lives
in `js/libs/extjs/resources/ext-theme-neptune/ext-theme-neptune-all.css`, a
vendored third-party theme, so it is overridden from `main.css` rather than
edited: `index.html` loads the theme at line 28 and `main.css` at line 34, so
equal-specificity rules win without `!important` and survive an ExtJS upgrade.

The objection recorded here was the right one and is what took this long. Option
1 was originally rejected because a *background-only* override would leave
Neptune's separately-styled hover, focus, pressed and disabled states behind. So
all five states were taken together, keeping Neptune's hue and its
each-state-darker-than-the-last direction:

| State | Neptune | Ratio | Now | Ratio |
|---|---|---|---|---|
| base | `#3892d3` | 3.38:1 | `#287AB6` | 4.62:1 |
| over | `#3386c2` | 3.94:1 | `#236FA8` | 5.37:1 |
| focus | `#3386c2` | 3.94:1 | `#236FA8` | 5.37:1 |
| pressed | `#2a6d9e` | 5.56:1 | `#1D5C89` | 7.13:1 |
| disabled | GIF | — | `#8FB4CF` | exempt |

It cleared AA only when held down before; it clears it in every state now.

The same override drops Neptune's four-stop vertical gradient and its GIF
fallback (`background-image: none`), which were the most dated surface left in
the app, and moves the corner from Neptune's 3px onto the shared
`--pa-radius-sm`. The split `Browse...` control is a single `.x-btn` element
with the arrow drawn inside it, not two adjacent boxes, so rounding it leaves no
seam. Verified live: base 4.62, hover 5.37, and Steps 1, 3 and 4 all render.

---

## Checked and deliberately left alone

### `span.networkClusterImage > i` - do not "fix" this by darkening it

The one contrast flag remaining in `main.css`. It is `#DA643D` on its own
`rgba(255, 255, 255, 0.54)`, layered over an arbitrary network-cluster
thumbnail, and it measures 3.58:1 against white.

The obvious fix is wrong. Because the icon's backdrop is 54% white over an
unknown image, the effective background is *bounded*: `#898989` at the darkest
(veil over pure black) through `#FFFFFF`. Against that range:

| Colour | On `#898989` | On `#FFFFFF` |
|---|---|---|
| `#DA643D` (current) | 1.03:1 | 3.58:1 |
| `#B04F22` (darker orange) | 1.52:1 | 5.27:1 |
| `#1A1A1A` (near-black) | 5.02:1 | 17.40:1 |

Darkening the orange *improves the white case and makes the dark case worse* -
1.03:1 becomes 1.52:1, still nowhere near conformant. No orange clears 4.5:1
across that span; only a near-black does, and that discards the amber "this
cluster is disabled" signal the icon exists to convey.

It is also exempt: the rule that reveals it is
`span.networkClusterImage.disabled > i { display: block }`, so it marks an
inactive component, which WCAG 1.4.3 does not require to meet the contrast
minimum.

Left unchanged deliberately. If it is ever revisited, the fix is to give the
icon an opaque backing so the backdrop stops depending on the image underneath,
*then* darken the orange - not to darken the orange on its own.

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

**Update (iteration 9).** `dev` has since landed `929c1dae`, which fixes the
*messaging* half of this: `ajaxErrorHandler` now checks for an `extra` block
naming a Python file, and for those says "This happened on the server, so
retrying in the browser will not help" instead of telling the user to clear
their cache. That is exactly the misdirection recorded above, so this entry is
now half-resolved.

The crash itself is unchanged - `PathwayAcquisitionServlet.py` is untouched by
any commit on `dev`, and the endpoint still returns the same TypeError when
called without a jobID. Re-confirmed against the running server this iteration.
So the UI still locks on a cold start with stale storage; it now just explains
itself honestly while doing so.

---

## 4. Contrast failures on Steps 3 and 4 that live in JS view files

**Status:** open
**Raised:** iteration 5 (branch `frontend-modernization`)

Entry 2 covered Step 1 only. Auditing Steps 3 and 4 for the first time found 20
further failing pairs; 12 were fixed in `main.css`, and these 8 cannot be,
because the colour is set in a view file this branch does not own. All are
normal-weight text under 18.66px, so the bar is 4.5:1.

### ~~`PA_Step3Views.js` - database and kingdom badge letters~~ — RESOLVED (iteration 10)

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

**Fixed, but not this way — see entry 5's resolution.** The darkenings above
were never applied, because they solve the badge in isolation and break its
relationship with the chart. `getClassificationColor()` also feeds the
classification pie chart and the pathway grid's colour stripes, so a badge
darkened for legibility would no longer match the slice it indexes. Making the
palette colour the chip *fill* instead of the ink fixes both tables at once and
leaves the palette untouched.

### ~~`PA_Step4Views.js` - inline panel fills~~ — RESOLVED (iteration 10)

All five suggestions below were applied verbatim. Measured live on Step 4 of job
`24u543f6b7` with every panel open: Download 4.56, Global heatmap 4.62, Pathway
information 4.60, Visual settings 4.62, History 4.61. The pathway diagram still
paints and every panel still expands.


Both are set as inline `style="background: ..."` on the element, so `main.css`
cannot reach them without an attribute-selector hack.

`.lateralOptionsPanel-header` has **four** inline fill variants, found by opening
each of the Step 4 side panels in turn (pathway info, heatmap, settings,
search). Three of the four fail, and three of the four fixes can reuse a value
already present in `main.css`, so the palette gains nothing new:

| Element | Current fill | White label | Suggested | New | Reuses |
|---|---|---|---|---|---|
| "Download" header | `#337ab7` | 4.56:1 | *(no change)* | - | - |
| "Global heatmap" header | `#55c9a6` | 2.04:1 | `#2A8368` | 4.62:1 | `.btn-secondary` |
| "Pathway information" header | `#5bc0de` | 2.09:1 | `#1F7F9B` | 4.60:1 | new |
| "Visual settings" header | `#d9534f` | 3.96:1 | `#D43E3A` | 4.62:1 | `.btn-danger` |
| "History" button | `#d66379` | 3.55:1 | `#CD435D` | 4.61:1 | new |

Note the "Visual settings" case in particular: `#d9534f` is the *old* Bootstrap
danger red, which `main.css` already darkened to `#D43E3A` for `.btn-danger`.
Because this panel sets the colour inline from JS, it kept the pre-fix value -
so the same red now appears at two different lightnesses depending on whether
it came from the stylesheet or from a view file. Applying the suggestion above
also re-synchronises them.

Note for whoever picks this up: **do not** instead darken the shared
`.lateralOptionsPanel-header h2` ink in `main.css`. The sibling "Download"
header is filled `#337ab7`, where white already passes at 4.56:1; switching
that h2 to dark ink would drop it to 3.73:1 and break a currently-conformant
header to fix a different one. The fill is the right thing to change, and only
for the panels that need it.

**Update (iteration 7):** there is a third inline variant of this header. The
"Global heatmap" panel, which appears only in the Step 4 heatmap view, is
filled `#55c9a6` and carries a white label at **2.04:1** - worse than the cyan
one. Suggested `#2A8368` (4.62:1), which is the same value the `.btn-secondary`
fill already uses, so the palette does not gain a new colour.

---

## 5. Reactome classification badges - 18 colours, all far below AA

**Status:** RESOLVED in iteration 10 — see "How it was actually fixed" below
**Raised:** iteration 7 (branch `frontend-modernization`)

Every audit before this one measured only what was on screen, and elements
inside an inactive ExtJS tab have no `offsetParent`, so they were skipped
silently. Activating the **Reactome** tab of `tabcontainer_network` on Step 3
revealed 20 further failing pairs, 18 of them distinct classification badge
letters defined in `PA_Step3Views.js`.

These are the worst contrast values found anywhere in the application. Pure
yellow on white is effectively invisible.

| Current | On white | Suggested | New |
|---|---|---|---|
| `#ffff00` | 1.07:1 | `#797900` | 4.62:1 |
| `#e0f8d8` | 1.13:1 | `#348618` | 4.60:1 |
| `#ffef96` | 1.16:1 | `#897400` | 4.60:1 |
| `#99ffcc` | 1.20:1 | `#008744` | 4.62:1 |
| `#deeaee` | 1.23:1 | `#497C8D` | 4.61:1 |
| `#e3eaa7` | 1.27:1 | `#717B1D` | 4.61:1 |
| `#b5e7a0` | 1.41:1 | `#3F8521` | 4.58:1 |
| `#d6cbd3` | 1.57:1 | `#8A6D82` | 4.57:1 |
| `#eca1a6` | 2.06:1 | `#D73944` | 4.61:1 |
| `#ff9500` | 2.20:1 | `#AB6400` | 4.61:1 |
| `#b2ad7f` | 2.29:1 | `#7B774A` | 4.59:1 |
| `#92a8d1` | 2.40:1 | `#5275B6` | 4.59:1 |
| `#c1946a` | 2.72:1 | `#9A6B40` | 4.61:1 |
| `#b9936c` | 2.82:1 | `#946E46` | 4.59:1 |
| `#009999` | 3.49:1 | see note | - |
| `#269900` | 3.72:1 | `#228800` | 4.58:1 |
| `#618685` | 3.99:1 | `#597B7A` | 4.63:1 |
| `#008888` | 4.31:1 | `#008383` | 4.59:1 |

**One caveat that needs a human decision.** `#008888` and `#009999` are already
near-identical teals, and darkening both to AA converges them on the same
`#008383` - two distinct classifications would become indistinguishable. Fixing
that needs a hue shift on one of them, which is a palette decision rather than
a mechanical contrast fix, so it is left open rather than guessed at.

More broadly: this palette is pastel by design, and eighteen simultaneous
darkenings will visibly change the character of the Reactome classification
list. If preserving the pastels matters, the alternative is to stop using these
colours as *text* and render each badge as a filled chip with dark ink instead -
the same move already made for the omic boxes in `main.css`, which kept the
type-coding intact while fixing legibility.

### How it was actually fixed (iteration 10)

The alternative won, and the caveat above turned out to be the deciding
argument rather than a footnote. Three things ruled out the darkening table:

1. **The palette is shared.** `getClassificationColor()` is read by the
   classification pie chart (`colors`, `textColor`, `strokeColor`) and by the
   pathway grid's per-row colour stripe, not only by the badge. Darkening it
   would have desynchronised every badge from the chart slice it indexes.
2. **`#008888` / `#009999` had no mechanical answer.** Both darken onto
   `#008383`, collapsing two classifications into one colour. That needed a hue
   decision nobody could make from a contrast table.
3. **Eighteen darkenings would have cost the pastel identity** for a palette
   whose entire job is to be distinguishable at a glance.

So the colour moved from the ink to the fill. `classificationBadgeStyle()` in
`Util.js` paints the palette value as the chip background and draws the letter
in whichever of black or white contrasts better with it, choosing at the
luminance crossover of 0.1791. **Every palette value is unchanged**, so the
chart and the stripes are untouched, and the two teals stay distinct.

Verified on the running server (job `24u543f6b7`, mmu, 888/44): 963 badges
rendered, **34 distinct fill/ink pairs, zero below 4.5:1**. The weakest is
`#c1502e` with white at 4.71:1. The mapping is computed rather than tabulated,
so colours added to the palette later are conformant by construction.

`main.css` carries two supporting changes: a 1px `rgba(0,0,0,0.22)` inset ring,
which only does visible work at the pale end of the palette where a chip would
otherwise dissolve into the page, and a disabled state rewritten as a flat
`#E8E8E8` chip with `#595959` ink (5.72:1) — the old rule set ink and border
only, which on a filled chip left the palette colour showing through.

This also closes the badge half of entry 4.

---

## 6. The grid toolbar cannot use ExtJS's own overflow handler

**Status:** open (worked around in `main.css`; the proper fix is here)
**Raised:** iteration 11 (branch `frontend-modernization`)

The Step 3 pathway-enrichment toolbar lays out 1753px of controls. Its box is
only as wide as the grid, so from about 1750px of viewport downwards the tail is
clipped with no way to reach it. At 1280px that is **"Show combined p-values",
"Configure" and "Download as XLS"** - the table's only export. It is already
happening at 1440px, so this is not a small-screen edge case.

ExtJS solves exactly this with `enableOverflow: true`, which collapses the
surplus into a `»` menu. **It cannot be used here**, because
`ExtJS_extensions.js` puts raw HTML anchors in the toolbar:

```js
me.tbar = [ ... '->',
    ((me.download !== false) ? '<a class="downloadXLS" ...>Download as XLS</a>' : ""),
    ((me.multidelete !== false) ? '<a class="multiDelete" ...>Delete selected</a>' : "")
];
```

and binds their handlers with jQuery against the grid's own element:

```js
$("#" + this.el.id + " a.downloadXLS").click(function () { ... });   // line 334
```

The overflow handler re-renders items into a floating menu attached to the
document body, i.e. outside `this.el`. The selector would no longer match, so
the menu entries would render and do nothing - a download button that looks
present and silently fails, which is worse than one that is visibly clipped.

### Proposed fix

Convert the two anchors into real toolbar buttons with ExtJS handlers, then turn
on the overflow menu:

```diff
-me.tbar = [ ... ];
+me.tbar = {
+    enableOverflow: true,
+    items: [ ...
+        (me.download !== false) ? {
+            xtype: 'button', iconCls: 'fa fa-file-excel-o', text: 'Download as XLS',
+            handler: function () { /* body of the current $().click() callback */ }
+        } : null,
+        ... ]
+};
```

Note `me.tbar.splice(-3, 0, ...)` and `me.tbar.splice(-2, 0, ...)` further down
become `me.tbar.items.splice(...)`. The same applies to `a.multiDelete`.

Until then, `main.css` gives `.x-toolbar.x-docked-top > .x-box-inner` an
`overflow-x: auto`, which keeps every element where its handler expects it and
makes the tail reachable by scrolling. Verified at 1280px: the toolbar scrolls
590px and "Download as XLS" lands inside the viewport with the anchor still
inside the grid element. The workaround's one weakness is the reason to do the
above properly - ExtJS pins the inner box to an inline `height: 24px`, so on
platforms with classic (space-taking) scrollbars the bar sits over the bottom of
the control row. On overlay-scrollbar platforms it costs nothing; measured
`offsetHeight - clientHeight = 0` on macOS/Chromium.

---

## Checked in iteration 11 and found conformant - do not re-investigate

The Step 3 significance cells render a p-value gradient from `rgb(255,0,0)` to
`rgb(255,161,161)` (`PA_Step3Views.js` lines 3719, 4103, 5424, 5480). At small
sizes on a saturated red they *look* like dark-red-on-red, and were flagged as a
suspected contrast failure. They are not: the ink is pure black and the worst
pair in the whole gradient is `#000000` on `rgb(255,0,0)` at **5.25:1**. Audited
live across 55 distinct fills; none below 4.5:1. White would be *worse* here
(4.00:1), so the current choice is already the right one.
