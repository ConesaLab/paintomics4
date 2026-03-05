"""
Tool definitions for AI pipeline agents using OpenAI Agents SDK @function_tool.

Data Query Tools (for Expert, Evaluator, Chat):
  - get_pathway_features: all matched genes + compounds in a pathway
  - get_gene_profile: detailed values for a gene across all gene-based omics
  - get_compound_profile: detailed values for a compound across all compound-based omics
  - compare_features: side-by-side comparison of genes and/or compounds
  - get_pathway_summary: per-omic p-values and feature counts

Literature Tools (for Expert, Evaluator, Chat):
  - search_pubmed: search PubMed, returns titles + abstracts
  - extract_evidence: async, delegates to Literature Sub-Agent for deep reading

Sub-Agent Tools (for Literature Sub-Agent only):
  - read_full_text: fetch/cache full paper text
  - search_paper_text: search within a paper's text
"""
import logging
import re

from agents import function_tool, Runner, RunContextWrapper
from src.classes.AIInterpret.models import PipelineContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_gene_header_map(job_instance):
    """Map omicName -> list of simplified column labels from gene-based omic headers."""
    header_map = {}
    for omic in job_instance.getGeneBasedInputOmics():
        omic_name = omic.get("omicName", "")
        headers = omic.get("omicHeader")
        if headers and isinstance(headers, list) and len(headers) > 1:
            labels = []
            for h in headers[1:]:
                col_str = str(h).strip()
                parts = col_str.rsplit("_", 1)
                labels.append(parts[-1] if len(parts) == 2 and parts[-1] else col_str)
            header_map[omic_name] = labels
        else:
            header_map[omic_name] = None
    return header_map


def _build_compound_header_map(job_instance):
    """Map omicName -> list of simplified column labels from compound-based omic headers."""
    header_map = {}
    for omic in job_instance.getCompoundBasedInputOmics():
        omic_name = omic.get("omicName", "")
        headers = omic.get("omicHeader")
        if headers and isinstance(headers, list) and len(headers) > 1:
            labels = []
            for h in headers[1:]:
                col_str = str(h).strip()
                parts = col_str.rsplit("_", 1)
                labels.append(parts[-1] if len(parts) == 2 and parts[-1] else col_str)
            header_map[omic_name] = labels
        else:
            header_map[omic_name] = None
    return header_map


def _find_matching_labels(header_map, n):
    """Find labels from another omic with matching length, else return index strings."""
    for labels in header_map.values():
        if labels and len(labels) == n:
            return labels
    return [str(i) for i in range(n)]


def _find_gene_by_symbol(job_instance, symbol):
    """Case-insensitive gene lookup. Returns (gene_id, gene_obj) or None."""
    target = symbol.upper()
    for gene_id, gene_obj in job_instance.getInputGenesData().items():
        if gene_obj.getName() and gene_obj.getName().upper() == target:
            return (gene_id, gene_obj)
    return None


def _find_compound_by_name(job_instance, name):
    """Case-insensitive compound lookup. Returns (compound_id, compound_obj) or None."""
    target = name.upper()
    for cpd_id, cpd_obj in job_instance.getInputCompoundsData().items():
        if cpd_obj.getName() and cpd_obj.getName().upper() == target:
            return (cpd_id, cpd_obj)
    return None


def _classify_expression_summary(values, design_type):
    """Return a pattern/summary suffix based on design type."""
    if not values or len(values) < 2:
        return ""

    from src.classes.AIInterpret.context_builder import _classify_temporal_pattern

    if design_type in ("time_series", "dose_response"):
        pattern = _classify_temporal_pattern(values)
        return f" | pattern: {pattern}"
    elif design_type == "case_control":
        fc = values[-1] - values[0]
        direction = "upregulated" if fc > 0.3 else ("downregulated" if fc < -0.3 else "unchanged")
        return f" | fold_change: {fc:+.3f} ({direction})"
    return ""


def _format_feature_omics(feature_obj, header_map, design_type):
    """Format all omic values for a gene or compound into a readable string."""
    lines = []
    for ov in feature_obj.getOmicsValues():
        omic_name = ov.getOmicName()
        relevant = ov.isRelevant()
        values = ov.getValues() or []
        labels = header_map.get(omic_name)

        de_status = "DE" if relevant else "not DE"

        if not labels or len(labels) != len(values):
            labels = _find_matching_labels(header_map, len(values))

        if labels:
            pairs = [f"{lbl}={v:.3f}" for lbl, v in zip(labels, values)]
            val_str = ", ".join(pairs)
        else:
            val_str = ", ".join(f"{v:.3f}" for v in values)

        suffix = _classify_expression_summary(values, design_type)
        lines.append(f"  {omic_name} ({de_status}): [{val_str}]{suffix}")
    return "\n".join(lines) if lines else "  (no omic data)"


def _format_authors_short(first_author):
    """'John Smith' -> 'Smith, J. et al.'"""
    if not first_author:
        return "Unknown"
    parts = first_author.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        initials = ".".join(p[0].upper() for p in parts[:-1] if p) + "."
        return f"{last}, {initials} et al."
    return f"{first_author} et al."


def _format_paper_text(paper):
    """Format a paper's full text for reading."""
    parts = []
    title = paper.get("title", "Unknown")
    authors = paper.get("authors_short", paper.get("first_author", "Unknown"))
    parts.append(f"# {title}")
    parts.append(f"{authors}, {paper.get('journal', '')}, {paper.get('year', '')}")
    parts.append(f"PMID: {paper.get('pmid', '')}")
    parts.append("")

    for section in ["abstract", "introduction", "results", "discussion", "other"]:
        text = paper.get("sections", {}).get(section)
        if text:
            parts.append(f"## {section.title()}")
            parts.append(text)
            parts.append("")

    result = "\n".join(parts)
    # Cap at ~12000 chars (~3000 tokens) to keep sub-agent context manageable
    if len(result) > 12000:
        result = result[:12000] + "\n\n... [truncated]"
    return result


# ---------------------------------------------------------------------------
# Data Query Tools
# ---------------------------------------------------------------------------


@function_tool
def get_pathway_features(ctx: RunContextWrapper[PipelineContext], pathway_name: str) -> str:
    """List ALL matched features in a pathway — both genes AND compounds.
    Returns gene names with DE status per omic plus compound names with DE status.
    Uses human-readable names (e.g. 'BRCA1', 'L-Glutamine'), not internal IDs."""
    job = ctx.context.job_instance
    matched_pathways = job.getMatchedPathways()
    input_genes = job.getInputGenesData()
    input_compounds = job.getInputCompoundsData()
    query_upper = pathway_name.upper()

    matches = [pw for pw in matched_pathways.values() if query_upper in pw.name.upper()]
    if not matches:
        available = sorted(set(pw.name for pw in matched_pathways.values()))
        listing = "\n".join(f"  - {n}" for n in available[:30])
        return f"No pathway matching '{pathway_name}'. Available:\n{listing}"

    pw = matches[0]
    gene_header = _build_gene_header_map(job)
    cpd_header = _build_compound_header_map(job)
    design = ctx.context.design_type

    parts = [f"Pathway: {pw.name} (ID: {pw.ID}, source: {pw.source})"]

    # Genes
    gene_lines = []
    for gid in pw.matchedGenes:
        gene = input_genes.get(gid)
        if gene is None:
            continue
        name = gene.getName() or gid
        omics = gene.getOmicsValues()
        if omics:
            de_omics = [ov.getOmicName() for ov in omics if ov.isRelevant()]
            de_str = f"DE in: {', '.join(de_omics)}" if de_omics else "not DE"
            gene_lines.append(f"  {name} ({de_str})")
        else:
            gene_lines.append(f"  {name} (no data)")
    parts.append(f"\nGenes ({len(pw.matchedGenes)} matched):")
    parts.append("\n".join(gene_lines) if gene_lines else "  (none)")

    # Compounds
    cpd_lines = []
    for cid in pw.matchedCompounds:
        cpd = input_compounds.get(cid)
        if cpd is None:
            continue
        name = cpd.getName() or cid
        omics = cpd.getOmicsValues()
        if omics:
            de_omics = [ov.getOmicName() for ov in omics if ov.isRelevant()]
            de_str = f"DE in: {', '.join(de_omics)}" if de_omics else "not DE"
            cpd_lines.append(f"  {name} ({de_str})")
        else:
            cpd_lines.append(f"  {name} (no data)")
    parts.append(f"\nCompounds/Metabolites ({len(pw.matchedCompounds)} matched):")
    parts.append("\n".join(cpd_lines) if cpd_lines else "  (none)")

    return "\n".join(parts)


@function_tool
def get_gene_profile(ctx: RunContextWrapper[PipelineContext], gene_name: str) -> str:
    """Get detailed values for a gene across ALL gene-based omic layers.
    Searches by gene name/symbol (case-insensitive), e.g. 'TP53', 'KRAS'.
    Output adapts to design type with appropriate pattern annotations."""
    job = ctx.context.job_instance
    result = _find_gene_by_symbol(job, gene_name)
    if result is None:
        return f"Gene '{gene_name}' not found in this dataset."

    gene_id, gene_obj = result
    header_map = _build_gene_header_map(job)
    omics_text = _format_feature_omics(gene_obj, header_map, ctx.context.design_type)
    return f"Gene: {gene_obj.getName()} (ID: {gene_id})\nOmic profiles:\n{omics_text}"


@function_tool
def get_compound_profile(ctx: RunContextWrapper[PipelineContext], compound_name: str) -> str:
    """Get detailed values for a metabolite/compound across ALL compound-based omic layers.
    Searches by compound name (case-insensitive), e.g. 'L-Glutamine', 'Pyruvate'.
    Output adapts to design type with appropriate pattern annotations."""
    job = ctx.context.job_instance
    result = _find_compound_by_name(job, compound_name)
    if result is None:
        return f"Compound '{compound_name}' not found in this dataset."

    cpd_id, cpd_obj = result
    header_map = _build_compound_header_map(job)
    omics_text = _format_feature_omics(cpd_obj, header_map, ctx.context.design_type)
    return f"Compound: {cpd_obj.getName()} (ID: {cpd_id})\nOmic profiles:\n{omics_text}"


@function_tool
def compare_features(ctx: RunContextWrapper[PipelineContext], names: list[str]) -> str:
    """Side-by-side comparison of multiple genes AND/OR compounds.
    Accepts any mix: ['BRCA1', 'L-Glutamine', 'TP53', 'Pyruvate'].
    Auto-detects whether each name is a gene or compound."""
    if not names:
        return "Error: names list is required."
    if len(names) > 10:
        names = names[:10]

    job = ctx.context.job_instance
    gene_header = _build_gene_header_map(job)
    cpd_header = _build_compound_header_map(job)
    design = ctx.context.design_type
    parts = []

    for name in names:
        name = name.strip()
        # Try gene first, then compound
        result = _find_gene_by_symbol(job, name)
        if result:
            gene_id, gene_obj = result
            omics_text = _format_feature_omics(gene_obj, gene_header, design)
            parts.append(f"Gene: {gene_obj.getName()} (ID: {gene_id})\n{omics_text}")
            continue

        result = _find_compound_by_name(job, name)
        if result:
            cpd_id, cpd_obj = result
            omics_text = _format_feature_omics(cpd_obj, cpd_header, design)
            parts.append(f"Compound: {cpd_obj.getName()} (ID: {cpd_id})\n{omics_text}")
            continue

        parts.append(f"{name} — NOT FOUND (not a gene or compound in this dataset)")

    return "\n\n".join(parts)


@function_tool
def get_pathway_summary(ctx: RunContextWrapper[PipelineContext], pathway_name: str) -> str:
    """Get statistical summary of a pathway: p-values per omic type, total vs significant
    features, which omics are enriched. Useful for understanding enrichment drivers."""
    job = ctx.context.job_instance
    matched_pathways = job.getMatchedPathways()
    query_upper = pathway_name.upper()

    matches = [pw for pw in matched_pathways.values() if query_upper in pw.name.upper()]
    if not matches:
        return f"No pathway matching '{pathway_name}'."

    pw = matches[0]
    lines = [f"Pathway: {pw.name} (ID: {pw.ID}, source: {pw.source})"]
    lines.append(f"Matched genes: {len(pw.matchedGenes)}")
    lines.append(f"Matched compounds: {len(pw.matchedCompounds)}")

    # Combined significance
    if pw.combinedSignificancePvalues:
        for method, pval in pw.combinedSignificancePvalues.items():
            lines.append(f"Combined p-value ({method}): {pval:.4e}")

    # Per-omic significance
    lines.append("\nPer-omic enrichment:")
    for omic_name, vals in pw.significanceValues.items():
        if len(vals) >= 3:
            total, relevant, pval = vals[0], vals[1], vals[2]
            sig = "SIGNIFICANT" if pval < 0.05 else "not significant"
            lines.append(f"  {omic_name}: p={pval:.4f} ({relevant}/{total} relevant) [{sig}]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Literature Tools
# ---------------------------------------------------------------------------


@function_tool
def search_pubmed(ctx: RunContextWrapper[PipelineContext], query: str, max_results: int = 5) -> str:
    """Search PubMed. Returns titles + abstracts only (~300 tokens per paper).
    Read the abstracts first — if an abstract supports your claim, cite it directly.
    Only call extract_evidence when the abstract isn't sufficient for your needs."""
    pubmed = ctx.context.pubmed_client
    if pubmed is None:
        return "Error: PubMed client not available."

    try:
        pmids = pubmed.search(query, max_results=max_results)
    except Exception as e:
        return f"PubMed search failed: {e}"

    if not pmids:
        return f"No PubMed results for: {query}"

    try:
        papers = pubmed.fetch_abstracts(pmids)
    except Exception as e:
        return f"Failed to fetch abstracts: {e}"

    if not papers:
        return "No papers returned."

    # Cache papers
    for p in papers:
        if p["pmid"] not in ctx.context.papers_used:
            p["authors_short"] = _format_authors_short(p.get("first_author", ""))
            p["sections"] = {"abstract": p.get("abstract", "")}
            p["full_text_available"] = False
            p["fetch_tier"] = "abstract_only"
            p["pathways"] = []
            ctx.context.papers_used[p["pmid"]] = p

    # Format output
    lines = []
    for p in papers:
        cached = ctx.context.papers_used.get(p["pmid"], p)
        lines.append(f"PMID: {p['pmid']}")
        lines.append(f"Title: {p.get('title', 'N/A')}")
        lines.append(f"Authors: {cached.get('authors_short', p.get('first_author', 'Unknown'))}")
        lines.append(f"Journal: {p.get('journal', 'N/A')}, {p.get('year', 'N/A')}")
        abstract = (p.get("abstract") or "")[:500]
        if abstract:
            lines.append(f"Abstract: {abstract}")
        lines.append("")

    return "\n".join(lines)


@function_tool
async def extract_evidence(ctx: RunContextWrapper[PipelineContext], pmid: str, question: str) -> str:
    """Extract specific evidence from a paper's full text to answer your question.
    A sub-agent reads the full paper (in its own context) and returns ONLY the
    relevant passage + finding. Use when the abstract isn't enough to support a claim.
    Returns ~200-500 tokens (finding + exact quote + relevance assessment)."""
    # Lazy import to avoid circular dependency (agents.py imports tools.py)
    from src.classes.AIInterpret.agents import literature_sub_agent

    prompt = (
        f"Paper PMID: {pmid}\n"
        f"Question: {question}\n\n"
        f"Read the paper using read_full_text({pmid}) and find evidence that answers the question. "
        f"If needed, use search_paper_text({pmid}, \"key phrase\") to locate specific passages."
    )

    try:
        result = await Runner.run(
            literature_sub_agent, prompt,
            context=ctx.context,
            max_turns=5,
        )
        return result.final_output
    except Exception as e:
        logger.warning(f"Evidence extraction failed for PMID {pmid}: {e}")
        return f"FINDING: Evidence extraction failed ({e}).\nCITED_TEXT: \"\"\nRELEVANCE: NONE"


# ---------------------------------------------------------------------------
# Sub-Agent Tools (used by Literature Sub-Agent)
# ---------------------------------------------------------------------------


@function_tool
def read_full_text(ctx: RunContextWrapper[PipelineContext], pmid: str) -> str:
    """Read a paper's full text. Fetches from PubMed/PMC if not already cached.
    Returns the paper's text organized by section (Abstract, Results, Discussion, etc.)."""
    # Check cache first
    paper = ctx.context.papers_used.get(pmid)
    if paper and paper.get("full_text_available"):
        return _format_paper_text(paper)

    # Fetch full text via PubMed client
    pubmed = ctx.context.pubmed_client
    if pubmed is None:
        if paper:
            return _format_paper_text(paper)  # Return abstract-only version
        return f"Error: No paper data for PMID {pmid}."

    try:
        papers = pubmed.fetch_papers([pmid])
        if papers:
            fetched = papers[0]
            fetched["authors_short"] = _format_authors_short(fetched.get("first_author", ""))
            ctx.context.papers_used[pmid] = fetched
            return _format_paper_text(fetched)
    except Exception as e:
        logger.warning(f"Full text fetch failed for PMID {pmid}: {e}")

    # Fallback to cached abstract
    if paper:
        return _format_paper_text(paper)
    return f"Could not fetch text for PMID {pmid}."


@function_tool
def search_paper_text(ctx: RunContextWrapper[PipelineContext], pmid: str, query: str) -> str:
    """Search within a paper's text for specific passages matching a query.
    Uses 3-tier matching: exact -> normalized -> fuzzy keyword overlap.
    Useful for finding specific quotes or verifying cited text exists."""
    paper = ctx.context.papers_used.get(pmid)
    if not paper:
        return f"Error: No paper data for PMID {pmid}. Call read_full_text first."

    sections = paper.get("sections", {})
    full_text = "\n\n".join(
        f"[{name.upper()}] {text}"
        for name, text in sections.items()
        if text
    )
    if not full_text:
        return f"No text available for PMID {pmid}."

    full_text_lower = full_text.lower()
    query_lower = query.lower()

    # Strategy 1: Direct substring
    matches = []
    start = 0
    while len(matches) < 3:
        idx = full_text_lower.find(query_lower, start)
        if idx == -1:
            break
        context_start = max(0, idx - 100)
        context_end = min(len(full_text), idx + len(query) + 100)
        matches.append(full_text[context_start:context_end])
        start = idx + len(query)

    # Strategy 2: Keyword overlap
    if not matches:
        keywords = set(re.findall(r'\b\w{4,}\b', query_lower))
        if keywords:
            sentences = re.split(r'(?<=[.!?])\s+', full_text)
            scored = []
            for sent in sentences:
                sent_lower = sent.lower()
                overlap = sum(1 for kw in keywords if kw in sent_lower)
                if overlap >= max(1, len(keywords) // 2):
                    scored.append((overlap, sent))
            scored.sort(key=lambda x: -x[0])
            matches = [s for _, s in scored[:3]]

    if not matches:
        return f"No passages matching '{query}' found in PMID {pmid}."

    result_parts = [f"Found {len(matches)} passage(s) in PMID {pmid}:"]
    for i, m in enumerate(matches, 1):
        if len(m) > 400:
            m = m[:400] + "..."
        result_parts.append(f"\n--- Passage {i} ---\n{m}")

    return "\n".join(result_parts)


# ---------------------------------------------------------------------------
# Tool collections for agent definitions
# ---------------------------------------------------------------------------

# Tools available to Pathway Expert and Pathway Evaluator
EXPERT_TOOLS = [
    get_pathway_features,
    get_gene_profile,
    get_compound_profile,
    compare_features,
    get_pathway_summary,
    search_pubmed,
    extract_evidence,
]

# Tools available to Literature Sub-Agent
SUB_AGENT_TOOLS = [
    read_full_text,
    search_paper_text,
]

# Tools available to Chat agent
CHAT_TOOLS = [
    get_pathway_features,
    get_gene_profile,
    get_compound_profile,
    compare_features,
    search_pubmed,
]
