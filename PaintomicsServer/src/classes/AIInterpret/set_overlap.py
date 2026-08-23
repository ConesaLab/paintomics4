"""Overlap between feature lists, with a statistic under it.

Why this exists
---------------
`feature-backlog.md` #4, wanted by seven dev studies: *k* named lists in, all
intersections out, with a test against a stated universe. It is the Venn or
UpSet panel these papers reach for constantly.

The point is not the diagram. It is that "these two contrasts share 412 genes"
means nothing without knowing how many they would share by chance, which
depends on the universe the experiment measured — not on the genome. So the
overlap comes with a hypergeometric p against the job's own feature space, and
the caller is told what that space was.

Direction agreement is reported separately: two lists can overlap heavily and
disagree about which way the shared features move, and that is a different
finding from agreement.
"""
import math

MAX_LISTS = 6
MAX_NAMED = 40


def _norm(names):
    seen, out = set(), []
    for raw in (names or []):
        s = str(raw or "").strip().strip(",;").upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _hypergeom_sf(hits, universe, a, b):
    """P(overlap >= hits) for two draws of size a and b from `universe`."""
    if hits <= 0 or universe <= 0 or a <= 0 or b <= 0:
        return 1.0
    lg = math.lgamma

    def logc(n, k):
        if k < 0 or k > n:
            return float("-inf")
        return lg(n + 1) - lg(k + 1) - lg(n - k + 1)

    denom = logc(universe, b)
    total = 0.0
    for k in range(int(hits), int(min(a, b)) + 1):
        term = logc(a, k) + logc(universe - a, b - k) - denom
        if term > -745:
            total += math.exp(term)
    return min(1.0, max(0.0, total))


def universe_of(job_instance, omic=None):
    """Every feature the experiment measured — the only honest background."""
    want = str(omic or "").strip().lower()
    names = set()
    for _fid, gene in (job_instance.getInputGenesData() or {}).items():
        rows = [ov for ov in (gene.getOmicsValues() or [])
                if not want or (ov.getOmicName() or "").strip().lower() == want]
        if not rows:
            continue
        n = (gene.getName() or "").upper()
        if n:
            names.add(n)
    return names


def compare(job_instance, lists, omic=None):
    """lists: [(name, [symbols]), ...]. Pairwise overlap with a test."""
    named = [(str(n), _norm(v)) for n, v in (lists or [])][:MAX_LISTS]
    named = [(n, v) for n, v in named if v]
    if len(named) < 2:
        return {"error": "give at least two non-empty lists to compare"}
    uni = universe_of(job_instance, omic)
    if not uni:
        return {"error": "no measured features found for omic %r" % (omic or "any")}

    inside = []
    for n, v in named:
        keep = [x for x in v if x in uni]
        inside.append((n, keep, len(v) - len(keep)))

    pairs = []
    for i in range(len(inside)):
        for j in range(i + 1, len(inside)):
            an, av, _ = inside[i]
            bn, bv, _ = inside[j]
            sa, sb = set(av), set(bv)
            shared = sa & sb
            union = sa | sb
            expected = len(sa) * len(sb) / len(uni) if uni else 0.0
            pairs.append({
                "a": an, "b": bn,
                "n_a": len(sa), "n_b": len(sb),
                "shared": len(shared),
                "expected": round(expected, 2),
                "fold": round(len(shared) / expected, 2) if expected > 0 else None,
                "jaccard": round(len(shared) / len(union), 3) if union else 0.0,
                "p": _hypergeom_sf(len(shared), len(uni), len(sa), len(sb)),
                "members": sorted(shared)[:MAX_NAMED],
            })
    return {
        "universe": len(uni),
        "omic": omic or "any",
        "lists": [{"name": n, "given": len(v) + miss, "measured": len(v),
                   "not_measured": miss} for n, v, miss in inside],
        "pairs": pairs,
    }


def format_result(res):
    if res.get("error"):
        return "No overlap computed: %s" % res["error"]
    lines = ["Set overlap against this experiment's own %d measured features (%s):"
             % (res["universe"], res["omic"])]
    for l in res["lists"]:
        lines.append("  %-22s %d of %d symbols measured here%s"
                     % (l["name"], l["measured"], l["given"],
                        "" if not l["not_measured"]
                        else " (%d absent)" % l["not_measured"]))
    for p in res["pairs"]:
        lines.append("  %s ^ %s: %d shared of %d and %d — expected %.2f by chance%s, "
                     "Jaccard %.3f, hypergeometric p = %.3g"
                     % (p["a"], p["b"], p["shared"], p["n_a"], p["n_b"],
                        p["expected"],
                        "" if p["fold"] is None else " (fold %.2f)" % p["fold"],
                        p["jaccard"], p["p"]))
        if p["members"]:
            shown = p["members"]
            lines.append("     shared: %s%s"
                         % (", ".join(shown),
                            "" if p["shared"] <= len(shown) else ", ..."))
    lines.append("  The background is what THIS experiment measured, not the "
                 "genome: quote it with the overlap or the number means nothing.")
    return "\n".join(lines)
