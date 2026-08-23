"""Test a gene set the agent names against the user's own data.

Why this exists
---------------
Across the dev corpus, three papers do the same thing PaintOmics could not:
they take a gene set that is NOT one of the built-in pathway databases and
ask whether it is enriched in their data.

  * 2025-39903532 — HALLMARK inflammatory response / TNFA-NFKB up, REACTOME
    cholesterol biosynthesis down, and a *published BACH2-repressed target
    set* from another paper.
  * 2025-39903537 — GO of each top-200 list, and of the 14-gene overlap.
  * 2025-40904458 — a *published 993-gene CAR-dependent set* intersected
    with the differential RNA and protein.

Three distinct dev studies, so it clears the "needed by >=3" rule; nothing
else in the buildable residue reaches three.

The test is deliberately the plain one -- a hypergeometric tail against the
job's OWN measured universe, not the genome. A set can only be enriched
among genes the experiment actually measured, and using a genomic
background would inflate every p-value on a targeted panel.

Two honesty requirements, both learned the hard way in this codebase:

  * Symbols that are not in the data are REPORTED, not dropped. "18 of your
    40 genes were measured here" is the difference between a real result and
    a misleading one, and the caller must see it.
  * The direction split (how many hits rise and how many fall) is computed
    from the raw values, never from the rendered two-decimal profile string.
"""
import math

MAX_SET_SIZE = 2000        # a "gene set" longer than this is a data dump
MAX_NAMES_ECHOED = 40      # keep the tool result readable


def _norm(symbols):
    """Upper-cased, de-duplicated, order-preserving; junk removed."""
    seen, out = set(), []
    for raw in (symbols or []):
        s = str(raw or "").strip().strip(",;").upper()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _hypergeom_sf(hits, universe, relevant, drawn):
    """P(X >= hits) for the hypergeometric tail, log-space, no SciPy.

    Written out rather than imported so this stays usable wherever the job
    runs, and so the arithmetic is inspectable: the enrichment claim is only
    worth as much as the number under it.
    """
    if hits <= 0:
        return 1.0
    if drawn <= 0 or relevant <= 0 or universe <= 0:
        return 1.0
    lg = math.lgamma

    def logc(n, k):
        if k < 0 or k > n:
            return float("-inf")
        return lg(n + 1) - lg(k + 1) - lg(n - k + 1)

    denom = logc(universe, drawn)
    total = 0.0
    upper = min(drawn, relevant)
    for k in range(int(hits), int(upper) + 1):
        term = logc(relevant, k) + logc(universe - relevant, drawn - k) - denom
        if term > -745:                      # exp underflows below this
            total += math.exp(term)
    return min(1.0, max(0.0, total))


def _direction(values):
    """+1 if the feature ends higher than it starts, -1 lower, 0 flat/unknown."""
    nums = [v for v in (values or []) if isinstance(v, (int, float))]
    if len(nums) < 2:
        return 0
    delta = nums[-1] - nums[0]
    if abs(delta) < 1e-9:
        return 0
    return 1 if delta > 0 else -1


def test_gene_set(job_instance, symbols, omic=None):
    """Hypergeometric enrichment of `symbols` among the job's relevant genes.

    Returns a dict; the caller formats it. `omic` restricts both the
    universe and the relevance flag to one layer, which is what makes
    "up in the proteome but not the transcriptome" expressible.
    """
    wanted = _norm(symbols)
    if not wanted:
        return {"error": "no gene symbols were given"}
    if len(wanted) > MAX_SET_SIZE:
        return {"error": "gene set has %d symbols; the limit is %d"
                         % (len(wanted), MAX_SET_SIZE)}

    want_omic = str(omic or "").strip().lower()
    universe = relevant = 0
    measured, hits, up, down = [], [], 0, 0
    target = set(wanted)

    for _gid, gene in (job_instance.getInputGenesData() or {}).items():
        name = (gene.getName() or "").upper()
        rows = [ov for ov in (gene.getOmicsValues() or [])
                if not want_omic or (ov.getOmicName() or "").strip().lower() == want_omic]
        if not rows:
            continue
        universe += 1
        is_rel = any(bool(ov.isRelevant()) for ov in rows)
        if is_rel:
            relevant += 1
        if name and name in target:
            measured.append(name)
            if is_rel:
                hits.append(name)
                # Direction from the first row that carries one, raw values.
                for ov in rows:
                    d = _direction(ov.getValues())
                    if d:
                        up += 1 if d > 0 else 0
                        down += 1 if d < 0 else 0
                        break

    drawn = len(measured)
    p = _hypergeom_sf(len(hits), universe, relevant, drawn)
    expected = (drawn * relevant / universe) if universe else 0.0
    return {
        "given": len(wanted),
        "measured": drawn,
        "not_measured": sorted(target - set(measured))[:MAX_NAMES_ECHOED],
        "not_measured_count": len(wanted) - drawn,
        "universe": universe,
        "relevant_in_universe": relevant,
        "hits": sorted(hits),
        "hit_count": len(hits),
        "expected": round(expected, 2),
        "fold": round(len(hits) / expected, 2) if expected > 0 else None,
        "p_value": p,
        "up": up,
        "down": down,
        "omic": omic or "any",
    }


def format_result(name, res):
    """The tool's reply: the number, the denominator, and what was missing."""
    if res.get("error"):
        return "Gene set '%s' could not be tested: %s" % (name, res["error"])
    if not res["measured"]:
        return ("Gene set '%s': none of its %d symbols were measured in this "
                "experiment, so it cannot be tested here."
                % (name, res["given"]))
    lines = [
        "Gene set '%s' (%s):" % (name, res["omic"]),
        "  %d of %d symbols were measured here%s."
        % (res["measured"], res["given"],
           "" if not res["not_measured_count"]
           else " -- %d were not, including %s" % (
               res["not_measured_count"], ", ".join(res["not_measured"][:8]))),
        "  %d of those %d are significant in this job (expected %.2f by chance%s)."
        % (res["hit_count"], res["measured"], res["expected"],
           "" if res["fold"] is None else ", fold %.2f" % res["fold"]),
        "  hypergeometric p = %.3g against this experiment's own %d measured "
        "genes, %d of them significant." % (res["p_value"], res["universe"],
                                            res["relevant_in_universe"]),
    ]
    if res["hit_count"]:
        lines.append("  direction of the significant members: %d up, %d down."
                     % (res["up"], res["down"]))
        shown = res["hits"][:MAX_NAMES_ECHOED]
        lines.append("  members: %s%s" % (", ".join(shown),
                     "" if len(res["hits"]) <= len(shown) else ", ..."))
    lines.append("  This is a test against YOUR data, not a literature claim: "
                 "cite it as such, and say how many symbols were missing.")
    return "\n".join(lines)
