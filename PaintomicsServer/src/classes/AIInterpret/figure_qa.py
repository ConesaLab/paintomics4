"""The `figure-standards.md` checklist, as code that runs on every bundle.

Why this file exists. A standards document that lives only in a prompt is a
standard the model is *asked* to meet; this arm has already paid for that
distinction more than once (a stage that graded itself passed by changing
nothing). Everything here is a line of `prompts/figure-standards.md` turned
into a check with a name and a one-line reason, run after the render, on the
artefact that was actually produced.

The eight checks (design §4.4), and the failure each one is here to catch:

  1. `bundle_complete`         -- a figure nobody can regenerate. The standards
     require svg + pdf + png + `figure.py` + `data.tsv` + `legend.md` to ship
     together; a bundle missing the script is a screenshot with extra steps.
  2. `svg_text_is_text`        -- matplotlib with the wrong `svg.fonttype`
     writes every label as paths (or embeds a raster), and the "vector, text as
     text" line silently fails. A journal's typesetter finds this, not us.
  3. `font_size_floor`         -- a label below 5 pt at final size is illegible
     in print. This is the check that catches a figure drawn at 183 mm and then
     scaled down to 89 mm.
  4. `palette_membership`      -- rainbow/jet, or a colour that means one
     condition in Fig 1 and another in Fig 3. Same condition, same colour, all
     figures in a report -- so the allowed set is the house palette plus greys.
  5. `diverging_only_for_signed` -- a diverging map forced to centre on zero
     over all-positive data invents a midpoint the data does not have, and the
     eye reads the invented midpoint as a boundary.
  6. `legend_carries_stats`    -- stars alone. The standards want n, the test
     name and an exact p in the legend, and the conclusion sentence first.
  7. `values_match_job`        -- the data-claim rule: every number on a figure
     goes through the same verification as a sentence in the report. A value in
     `data.tsv` that is not the job's value for that feature/condition is a
     fabricated number with a chart around it.
  8. `no_label_collisions`     -- overlapping or clipped labels. Coarse, and
     honest about being coarse; see the check's own note.

Every check returns `(name, ok, reason)` and NOTHING here raises. A bundle that
fails QA is still stored and still reported (design §5) -- the verdict is the
product, so a QA pass that died on a malformed SVG would destroy the only
signal the caller wanted.

The `spec` argument is what the tool decided, not what the model asked for.
Keys read (all optional, all defaulted -- a missing key must never be the
reason a figure fails):

    conclusion   str   the one sentence the figure exists to make
    centre_zero  bool  did the template centre a diverging map on zero
    has_negative bool  does the plotted slice actually contain negative values
    statistic    bool  is a statistical comparison drawn (so n/test/p are due)
"""
from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Design §4.4 item 1. legend.md is in the list because a figure without its
# legend cannot be checked against item 6 at all.
REQUIRED_FILES = ("figure.svg", "figure.pdf", "figure.png",
                  "figure.py", "data.tsv", "legend.md")

MIN_FONT_PT = 5.0                       # figure-standards.md, "Composition"
VALUE_TOLERANCE = 1e-6                  # data.tsv is written by us, so exact-ish
MAX_REPORTED_MISMATCHES = 3             # a wall of diffs is not a reason

# matplotlib writes SVG at 72 user units per inch, so one SVG "px" is one point.
# Anything in em/%/rem cannot be resolved without the cascade and is reported as
# unverifiable rather than silently passed.
_FONT_SIZE_RE = re.compile(
    r"font-size\s*[:=]\s*[\"']?\s*([0-9]*\.?[0-9]+)\s*(px|pt|em|rem|%)?",
    re.I)
_COLOUR_RE = re.compile(
    r"\b(fill|stroke)\s*[:=]\s*[\"']?\s*"
    r"(#[0-9a-fA-F]{3}(?![0-9a-fA-F])|#[0-9a-fA-F]{6}|[a-zA-Z]+)",
    re.I)

# Named colours a plot legitimately uses that are not "in the palette": the
# absence of paint, and the two ends of the grey ramp.
_NEUTRAL_NAMES = frozenset((
    "none", "transparent", "currentcolor", "inherit",
    "black", "white", "gray", "grey", "lightgray", "lightgrey",
    "darkgray", "darkgrey", "silver", "dimgray", "dimgrey",
))

# Enough to satisfy "a test name" without turning into a taxonomy. The point is
# to reject a legend that has only stars, not to police vocabulary.
_TEST_NAMES = ("t-test", "t test", "ttest", "wilcoxon", "mann-whitney",
               "mann whitney", "anova", "kruskal", "fisher", "chi-square",
               "chi square", "hypergeometric", "binomial", "permutation",
               "bh", "benjamini", "fdr", "bonferroni", "spearman", "pearson",
               "log-rank", "logrank", "deseq", "limma", "edger")

_N_RE = re.compile(r"\bn\s*(?:=|:|\s)\s*\d+", re.I)
_P_RE = re.compile(r"\bp\s*(?:-?\s*(?:value|adj|adjusted))?\s*[=<>]\s*"
                   r"[0-9.]+(?:\s*[eE]\s*-?\s*[0-9]+)?", re.I)


# ---------------------------------------------------------------------------
# small readers -- each swallows its own failure and hands back a reason
# ---------------------------------------------------------------------------

def _read(path):
    """(text, error). Never raises: a file we cannot read is a FAILED check,
    not a crashed QA pass."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), ""
    except OSError as exc:
        return "", "cannot read %s (%s)" % (os.path.basename(path), exc.strerror)


def _norm_hex(value):
    """'#ABC' / '#aabbcc' -> '#aabbcc'; a name stays a lowercased name."""
    value = value.strip().lower()
    if value.startswith("#") and len(value) == 4:
        return "#" + "".join(c * 2 for c in value[1:])
    return value


def _is_grey(value):
    """True for #rrggbb with r == g == b -- the whole neutral ramp at once."""
    if not (value.startswith("#") and len(value) == 7):
        return False
    return value[1:3] == value[3:5] == value[5:7]


def _strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


def _text_elements(svg_text):
    """[(attrib dict, text)] for every <text>, or [] if the SVG will not parse.

    ElementTree rather than a regex because a `<text>` can carry `<tspan>`
    children and the label a reader sees is the concatenation of them; a regex
    over the raw markup would measure the wrong string.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return []
    out = []
    for node in root.iter():
        if _strip_ns(node.tag) != "text":
            continue
        out.append((dict(node.attrib), "".join(node.itertext()).strip()))
    return out


# ---------------------------------------------------------------------------
# the eight checks -- each returns (name, ok, one-line reason)
# ---------------------------------------------------------------------------

def _check_bundle_complete(bundle_dir, _spec, _values):
    name = "bundle_complete"
    missing, empty = [], []
    for fname in REQUIRED_FILES:
        path = os.path.join(bundle_dir, fname)
        if not os.path.isfile(path):
            missing.append(fname)
        elif os.path.getsize(path) == 0:
            # A zero-byte figure.pdf is the signature of a render that was
            # killed mid-write; the file exists, so presence alone would pass.
            empty.append(fname)
    if missing or empty:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if empty:
            parts.append("empty " + ", ".join(empty))
        return name, False, "; ".join(parts)
    return name, True, "all %d bundle files present and non-empty" % len(REQUIRED_FILES)


def _check_svg_text_is_text(bundle_dir, _spec, _values):
    name = "svg_text_is_text"
    svg, err = _read(os.path.join(bundle_dir, "figure.svg"))
    if err:
        return name, False, err
    n_image = len(re.findall(r"<\s*image\b", svg, re.I))
    n_text = len(re.findall(r"<\s*text\b", svg, re.I))
    if n_image:
        return (name, False,
                "svg embeds %d <image> element(s) -- a raster in a vector file "
                "is not 'text as text'" % n_image)
    if n_text == 0:
        return (name, False,
                "svg has no <text> elements -- labels were drawn as paths "
                "(set svg.fonttype='none')")
    return name, True, "%d <text> elements, no embedded raster" % n_text


def _check_font_size_floor(bundle_dir, _spec, _values):
    name = "font_size_floor"
    svg, err = _read(os.path.join(bundle_dir, "figure.svg"))
    if err:
        return name, False, err
    sizes, unresolvable = [], 0
    for raw, unit in _FONT_SIZE_RE.findall(svg):
        unit = (unit or "px").lower()
        if unit in ("em", "rem", "%"):
            unresolvable += 1          # needs the cascade; not a silent pass
            continue
        try:
            sizes.append(float(raw))   # px == pt at matplotlib's 72 units/inch
        except ValueError:
            unresolvable += 1
    if not sizes:
        return (name, False,
                "no resolvable font-size in the svg (%d relative sizes) -- "
                "the 5 pt floor could not be checked" % unresolvable)
    smallest = min(sizes)
    if smallest < MIN_FONT_PT:
        return (name, False,
                "smallest font-size is %.2f pt, below the %.0f pt print floor"
                % (smallest, MIN_FONT_PT))
    note = "" if not unresolvable else " (%d relative sizes unchecked)" % unresolvable
    return name, True, "smallest font-size %.2f pt%s" % (smallest, note)


def _check_palette_membership(bundle_dir, _spec, _values):
    name = "palette_membership"
    # Lazy, and inside the function on purpose: figure_style.py is written by
    # another hand on this branch, and an import at module scope would make
    # figure_qa unimportable -- and every other check unrunnable -- for as long
    # as that file is absent.
    try:
        from .figure_style import PALETTE          # deliberate late import
    except ImportError:
        try:
            from src.classes.AIInterpret.figure_style import PALETTE
        except ImportError:
            return (name, False,
                    "SKIPPED: figure_style.PALETTE is not importable, so "
                    "palette membership could not be checked")
    try:
        raw = PALETTE.values() if hasattr(PALETTE, "values") else PALETTE
        allowed = {_norm_hex(str(c)) for c in raw}
    except (TypeError, AttributeError):
        return (name, False,
                "SKIPPED: figure_style.PALETTE is not a colour collection")

    svg, err = _read(os.path.join(bundle_dir, "figure.svg"))
    if err:
        return name, False, err

    offenders = []
    for _prop, value in _COLOUR_RE.findall(svg):
        colour = _norm_hex(value)
        if colour in allowed or colour in _NEUTRAL_NAMES or _is_grey(colour):
            continue
        if colour not in offenders:
            offenders.append(colour)
    if offenders:
        return (name, False,
                "%d colour(s) outside the house palette and the grey ramp: %s"
                % (len(offenders), ", ".join(offenders[:5])))
    return name, True, "every fill/stroke is a palette colour or a grey"


def _check_diverging_only_for_signed(_bundle_dir, spec, _values):
    name = "diverging_only_for_signed"
    centre_zero = bool(spec.get("centre_zero"))
    has_negative = bool(spec.get("has_negative"))
    if centre_zero and not has_negative:
        return (name, False,
                "a diverging map is centred on zero but the slice has no "
                "negative values -- the midpoint is invented")
    if centre_zero:
        return name, True, "diverging map centred on zero over signed data"
    return name, True, "sequential map (centre_zero is off)"


def _check_legend_carries_stats(bundle_dir, spec, _values):
    name = "legend_carries_stats"
    legend, err = _read(os.path.join(bundle_dir, "legend.md"))
    if err:
        return name, False, err
    flat = " ".join(legend.split()).lower()

    conclusion = " ".join(str(spec.get("conclusion", "")).split()).lower()
    if conclusion and conclusion not in flat:
        return (name, False,
                "the legend does not open with the figure's conclusion "
                "sentence")

    # n / test / p are due only when a statistical comparison is actually
    # drawn. Demanding them of a descriptive panel would train the templates to
    # print a p-value that means nothing, which is worse than omitting one.
    if not spec.get("statistic"):
        return (name, True,
                "conclusion present; no statistic plotted, so no n/test/p due")

    missing = []
    if not _N_RE.search(legend):
        missing.append("n")
    if not (_P_RE.search(legend)
            or any(t in flat for t in _TEST_NAMES)):
        missing.append("test name or exact p")
    if missing:
        return (name, False,
                "a statistic is plotted but the legend has no %s -- stars "
                "alone are not a statistic" % " and no ".join(missing))
    return name, True, "conclusion, n and a test/p are all in the legend"


def _parse_data_tsv(text):
    """(rows, error) as [(feature, condition, value_string)].

    Two shapes are accepted because the templates legitimately produce both:
    WIDE (feature in column 0, one column per condition, the shape a heatmap
    slice takes) and LONG (exactly three columns headed feature/condition/
    value, the shape a timecourse takes). Guessing is confined to this
    function so that a third shape later fails HERE, loudly, and not as a wall
    of phantom value mismatches.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return [], "data.tsv has no data rows"
    header = lines[0].split("\t")
    if len(header) < 2:
        return [], "data.tsv is not tab-separated (header has one column)"

    long_shape = (len(header) == 3
                  and header[1].strip().lower() in ("condition", "conditions",
                                                    "sample", "group"))
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        if long_shape:
            if len(cells) < 3:
                continue
            rows.append((cells[0].strip(), cells[1].strip(), cells[2].strip()))
        else:
            feature = cells[0].strip()
            for idx, cell in enumerate(cells[1:], start=1):
                if idx < len(header):
                    rows.append((feature, header[idx].strip(), cell.strip()))
    return rows, ""


def _check_values_match_job(bundle_dir, _spec, values):
    name = "values_match_job"
    if values is None:
        return (name, False,
                "SKIPPED: no job values were supplied, so the numbers on the "
                "figure were not re-checked against the run")
    text, err = _read(os.path.join(bundle_dir, "data.tsv"))
    if err:
        return name, False, err
    rows, parse_err = _parse_data_tsv(text)
    if parse_err:
        return name, False, parse_err

    mismatches, compared = [], 0
    for feature, condition, cell in rows:
        if cell == "" or cell.lower() in ("na", "nan", "none", "null"):
            continue                    # a blank is a missing value, not a claim
        try:
            plotted = float(cell)
        except ValueError:
            mismatches.append("%s/%s is not a number (%r)"
                              % (feature, condition, cell))
            continue
        per_feature = values.get(feature)
        if per_feature is None:
            mismatches.append("%s is not a feature in the job" % feature)
            continue
        if condition not in per_feature:
            mismatches.append("%s has no job value for condition %s"
                              % (feature, condition))
            continue
        compared += 1
        expected = float(per_feature[condition])
        if abs(plotted - expected) > VALUE_TOLERANCE:
            mismatches.append("%s/%s plots %.6g, job has %.6g"
                              % (feature, condition, plotted, expected))

    if mismatches:
        shown = "; ".join(mismatches[:MAX_REPORTED_MISMATCHES])
        more = ("" if len(mismatches) <= MAX_REPORTED_MISMATCHES
                else " (+%d more)" % (len(mismatches) - MAX_REPORTED_MISMATCHES))
        return (name, False,
                "%d value(s) in data.tsv are not the job's: %s%s"
                % (len(mismatches), shown, more))
    return name, True, "all %d plotted values equal the job's values" % compared


def _text_boxes(svg_text):
    """[(box, label)] for the <text> elements we can place, plus a skip count.

    Deliberately COARSE, and the reason it may be is that its only job is to
    catch a collision a reader would see: a box is `0.6 * font-size` wide per
    character (the mean advance of a humanist sans at these sizes) and one
    font-size tall, anchored by `text-anchor`. Rotated labels are SKIPPED
    rather than mis-placed -- a rotated y-axis title measured as horizontal is
    the single easiest way to invent a collision that is not there, and a QA
    check that cries wolf gets switched off.
    """
    boxes, skipped = [], 0
    for attrib, label in _text_elements(svg_text):
        if not label:
            continue
        transform = attrib.get("transform", "")
        if "rotate" in transform or "matrix" in transform:
            skipped += 1
            continue
        style = attrib.get("style", "")
        match = _FONT_SIZE_RE.search(style) or _FONT_SIZE_RE.search(
            "font-size=%s" % attrib.get("font-size", ""))
        try:
            size = float(match.group(1)) if match else 0.0
        except (TypeError, ValueError):
            size = 0.0
        if size <= 0:
            skipped += 1               # no resolvable size: cannot place it
            continue
        try:
            x = float(attrib.get("x", "nan"))
            y = float(attrib.get("y", "nan"))
        except ValueError:
            skipped += 1
            continue
        if x != x or y != y:           # NaN: the element had no x/y at all
            skipped += 1
            continue
        width = 0.6 * size * len(label)
        anchor = (attrib.get("text-anchor")
                  or _style_value(style, "text-anchor") or "start").lower()
        if anchor == "middle":
            x -= width / 2.0
        elif anchor == "end":
            x -= width
        # SVG y is the baseline; the glyph body sits mostly above it.
        boxes.append(((x, y - size * 0.8, x + width, y + size * 0.2), label))
    return boxes, skipped


def _style_value(style, prop):
    match = re.search(re.escape(prop) + r"\s*:\s*([^;\"']+)", style or "", re.I)
    return match.group(1).strip() if match else ""


def _overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _check_no_label_collisions(bundle_dir, _spec, _values):
    name = "no_label_collisions"
    svg, err = _read(os.path.join(bundle_dir, "figure.svg"))
    if err:
        return name, False, err
    boxes, skipped = _text_boxes(svg)
    if not boxes:
        return (name, False,
                "no placeable <text> elements (%d skipped) -- collisions could "
                "not be checked" % skipped)
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlaps(boxes[i][0], boxes[j][0]):
                return (name, False,
                        "labels %r and %r overlap (coarse boxes: 0.6*size per "
                        "character, rotated labels skipped)"
                        % (boxes[i][1][:40], boxes[j][1][:40]))
    note = "" if not skipped else ", %d skipped (rotated or unplaceable)" % skipped
    return name, True, "%d labels, no coarse-box overlap%s" % (len(boxes), note)


CHECKS = (
    _check_bundle_complete,
    _check_svg_text_is_text,
    _check_font_size_floor,
    _check_palette_membership,
    _check_diverging_only_for_signed,
    _check_legend_carries_stats,
    _check_values_match_job,
    _check_no_label_collisions,
)


def run_checks(bundle_dir, spec=None, values=None):
    """[(name, ok, reason)] for all eight checks, in checklist order.

    A check that blows up is reported as a FAILED check carrying its own
    exception text. It is never allowed to abort the pass: the seven checks
    after it are the ones that would have told the author what to fix.
    """
    spec = spec or {}
    results = []
    for fn in CHECKS:
        try:
            results.append(fn(bundle_dir, spec, values))
        except Exception as exc:            # broad on purpose -- see above
            logger.exception("figure_qa: check %s raised", fn.__name__)
            results.append((fn.__name__.lstrip("_").replace("check_", ""),
                            False, "check raised %r" % (exc,)))
    return results


def check(bundle_dir, spec=None, values=None):
    """(passed, lines) -- the verdict the tool pastes into its return string.

    `values` is {feature: {condition: float}} straight from the job, and is
    what makes check 7 mean anything; omitting it does not quietly pass that
    check, it fails it as SKIPPED. A figure whose numbers were never re-checked
    must not look the same as one whose numbers were.
    """
    results = run_checks(bundle_dir, spec, values)
    lines = ["%s  %s: %s" % ("PASS" if ok else "FAIL", name, reason)
             for name, ok, reason in results]
    return all(ok for _n, ok, _r in results), lines
