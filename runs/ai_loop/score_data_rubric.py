"""Score a report against a rubric derived from the job's own data.

The tellme rubric encodes the findings of the published PaintOmics STATegra
analysis -- RET signalling, DOK family, mir-188-3p, polyamine hubs. Six of its
twenty tokens appear in the enrichment of none of the 45 stored jobs, so
scoring against it measures the gap between this deployment's data and that
paper as much as it measures the pipeline. A tool cannot report biology its
input does not contain.

This builds the rubric from the job instead: the pathways the analysis actually
enriched, the features actually corroborated across omic layers, and the
caveats the data actually warrants. Every item is therefore reachable by an
honest report and unreachable by a fabricating one -- which is the property the
tellme rubric has for its own dataset and lacks for these.

Deliberately NOT derived from any report: the expectations come from the job,
before any text exists, so a report cannot define its own target.

Usage: python score_data_rubric.py <job_id> <report.md> [<report.md> ...]
"""
import os, re, sys, warnings
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(REPO, "PaintomicsServer")
sys.path.insert(0, os.path.join(SERVER, "src"))
sys.path.insert(0, SERVER)

from src.common.JobInformationManager import JobInformationManager
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, build_key_regulators_block,
)

# Caveats the data warrants, phrased as the honest-practice checks they are.
CAVEATS = [
    (r"did not reach|short of significance|non-?significant|marginal|\btrend\b",
     "marginal results reported as trends"),
    (r"discordan|does not follow|without corresponding|inconsist",
     "cross-layer discordance named"),
    (r"annotation artefact|annotation artifact|named after|label reflects|despite (?:its|the) name",
     "disease-named pathway flagged as annotation"),
    (r"driven (?:almost )?(?:entirely|solely) by|single (?:omic )?layer|only .{0,20}assay",
     "single-layer pathways identified"),
    (r"remains? to be|requires? (?:further )?(?:testing|validation)|hypothes",
     "hypotheses marked as untested"),
    (r"control point|rate-?limiting|bottleneck", "control points proposed"),
    (r"both up.{0,15}and down|mixed direction|in opposite direction",
     "mixed directions reported honestly"),
]


def build_expectations(job_id, n_pathways=28, n_features=15):
    ji = JobInformationManager().loadJobInstance(job_id)
    if ji is None:
        raise SystemExit("job %s not loadable" % job_id)
    pathways = build_pathway_context(ji, max_pathways=n_pathways)
    names = [p["name"] for p in pathways if p.get("name")]
    block = build_key_regulators_block(ji, limit=n_features)
    features = re.findall(r"\*\*([\w\-\.]+)\*\*", block)[:n_features]
    # Differential genes inside the enriched pathways: the biology a reader of
    # this analysis would expect to see discussed.
    genes = []
    for p in pathways:
        for g in (p.get("top_genes") or []):
            if g.get("relevant") and g.get("symbol"):
                genes.append(g["symbol"])
    seen, top_genes = set(), []
    for g in genes:
        if g.upper() not in seen:
            seen.add(g.upper()); top_genes.append(g)
    return names, features, top_genes[:25]


def score(report_path, names, features, genes):
    t = open(report_path).read()
    low = t.lower()
    pw_hit = [n for n in names if n.lower() in low]
    ft_hit = [f for f in features if re.search(r"\b%s\b" % re.escape(f), t, re.I)]
    gn_hit = [g for g in genes if re.search(r"\b%s\b" % re.escape(g), t, re.I)]
    cv_hit = [label for pat, label in CAVEATS if re.search(pat, t, re.I | re.S)]

    refs = set(int(x) for x in re.findall(r"^\s*\[(\d+)\]", t, re.M))
    cited = set(int(x) for x in re.findall(r"\[(\d+)\]", t))
    dangling = [c for c in cited if c not in refs]

    # Percentages, so the scale means something: how much of what this analysis
    # found did the report actually convey?
    pw_pct = 100.0 * len(pw_hit) / max(len(names), 1)
    ft_pct = 100.0 * len(ft_hit) / max(len(features), 1)
    gn_pct = 100.0 * len(gn_hit) / max(len(genes), 1)
    cv_pct = 100.0 * len(cv_hit) / len(CAVEATS)
    overall = 0.35 * pw_pct + 0.20 * ft_pct + 0.20 * gn_pct + 0.25 * cv_pct
    return dict(pw=(len(pw_hit), len(names), pw_pct),
                ft=(len(ft_hit), len(features), ft_pct),
                gn=(len(gn_hit), len(genes), gn_pct),
                cv=(len(cv_hit), len(CAVEATS), cv_pct),
                refs=len(refs), dangling=len(dangling), overall=overall)


job = sys.argv[1]
names, features, genes = build_expectations(job)
print("Data-derived rubric for job %s:" % job)
print("  %d enriched pathways, %d cross-layer features, %d differential genes, "
      "%d caveat checks\n" % (len(names), len(features), len(genes), len(CAVEATS)))
print("%-16s %10s %10s %10s %10s %8s %s" %
      ("report", "pathways", "features", "genes", "caveats", "cited", "OVERALL"))
print("-" * 88)
for path in sys.argv[2:]:
    if not os.path.exists(path):
        continue
    r = score(path, names, features, genes)
    flag = "" if r["dangling"] == 0 else "  DANGLING=%d" % r["dangling"]
    print("%-16s %9.0f%% %9.0f%% %9.0f%% %9.0f%% %8d %6.1f%%%s" % (
        os.path.basename(path).replace("_report.md", ""),
        r["pw"][2], r["ft"][2], r["gn"][2], r["cv"][2], r["refs"], r["overall"], flag))
