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
