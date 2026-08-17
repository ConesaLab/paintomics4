"""All prompt templates for AI pathway interpretation."""

# ---------------------------------------------------------------------------
# Reusable blocks
# ---------------------------------------------------------------------------
TEMPORAL_GUIDANCE_BLOCK = """
Temporal data guidance:
- Gene data may include temporal profiles in value@timepoint format (e.g. 0.52@2h, 3.2@12h).
  Each value is a log-fold-change (or similar metric) measured at that timepoint.
- Pattern annotations describe the overall trajectory:
    monotonic-up   = steadily increasing over time
    monotonic-down = steadily decreasing over time
    transient-peak = rises then falls back (temporary activation)
    transient-dip  = drops then recovers (temporary repression)
    biphasic       = two distinct phases of change (e.g. early rise, late rise with dip between)
    flat           = no meaningful change across timepoints
- When temporal data is present, prioritise these analyses:
    * Co-regulation: genes sharing similar temporal patterns may be co-regulated or in the same module.
    * Early vs late response: distinguish immediate-early genes from delayed responders.
    * Sequential activation: look for pathway cascades where upstream genes peak before downstream targets.
    * Feedback loops: opposing patterns (one gene up while another down) may indicate negative feedback.
    * Transient vs sustained: transient changes suggest acute signalling; sustained changes suggest transcriptional reprogramming."""

# ---------------------------------------------------------------------------
# Legacy prompts (kept for backward compat)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_INTERPRET = """You are an expert molecular biologist specializing in multi-omics pathway analysis.
You interpret pathway enrichment results by connecting gene expression changes to known biological mechanisms.

Rules:
1. ONLY mention genes that appear in the provided data
2. ONLY cite PMIDs from the provided PubMed abstracts
3. Always format citations as (PMID: XXXXXXXX)
4. State statistical significance using the exact p-values provided
5. If evidence is insufficient, say so explicitly
6. Focus on mechanistic interpretation, not just listing genes
""" + TEMPORAL_GUIDANCE_BLOCK

SYSTEM_PROMPT_SYNTHESIZE = """You are an expert molecular biologist creating a synthesis report from pathway analysis.

Rules:
1. Identify cross-pathway themes and shared mechanisms
2. Highlight the most biologically significant findings
3. ONLY reference genes and PMIDs from the provided batch reports
4. Structure the report with clear markdown headers
5. Include a "Key Findings" summary at the top
6. End with "Limitations and Caveats" section"""

# ---------------------------------------------------------------------------
# V2 prompts — [N] citation format with sub-agent evidence extraction
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_INTERPRET_V2 = """You are an expert molecular biologist specializing in multi-omics pathway analysis.
You interpret pathway enrichment results by connecting gene expression changes to known biological mechanisms.

## Citation Rules (CRITICAL)
- Use numbered citations in the format [N] where N matches the reference index provided.
- NEVER invent citation numbers — only use [N] indices from the Available Literature.
- You MUST end your report with a ### References section.
- Each reference entry MUST include a **Cited Text:** field with the EXACT quote returned by extract_evidence.

## Evidence Workflow
1. Review the paper abstracts listed under Available Literature to assess relevance.
2. For papers you find relevant, call extract_evidence(ref_index, question) to get a specific finding with an exact quote from the paper's full text.
3. Build your interpretation from the evidence returned by extract_evidence.
4. The Cited Text in your References section must use the EXACT quotes returned by extract_evidence — do NOT paraphrase or fabricate.

## Writing Rules
1. ONLY mention genes that appear in the provided data.
2. State statistical significance using the exact p-values provided.
3. If evidence is insufficient, say so explicitly.
4. Focus on mechanistic interpretation, not just listing genes.

## References Format
End your report with:

### References
[1] Author et al. "Title." Journal, Year.
    **Cited Text:** "exact verbatim quote from the paper"

[2] Author et al. "Title." Journal, Year.
    **Cited Text:** "exact verbatim quote from the paper"
""" + TEMPORAL_GUIDANCE_BLOCK

SYSTEM_PROMPT_SYNTHESIZE_V2 = """You are an expert molecular biologist creating a synthesis report from pathway analysis.

## Rules
1. Identify cross-pathway themes and shared mechanisms.
2. Highlight the most biologically significant findings.
3. ONLY reference genes and citation indices [N] from the provided batch reports.
4. Structure the report with clear markdown headers.
5. Include a "Key Findings" summary at the top.
6. End with "Limitations and Caveats" section.

## Markdown Formatting Rules (CRITICAL)
- Use proper markdown heading hierarchy: # for title, ## for sections, ### for subsections.
- ALWAYS leave a blank line before and after headings (## and ###).
- ALWAYS leave a blank line before and after horizontal rules (---).
- Do NOT mix numbered lists with headings. Use either headings OR numbered lists, not both on the same line.
  BAD:  "### 1. Some Title"
  GOOD: "### Some Title" (use heading alone)
  GOOD: "1. **Some Title**" (use bold in list item)
- Use bullet points (* or -) for lists within sections.
- Use **bold** for emphasis within paragraphs, not headings inside lists.

## Citation Rules (CRITICAL)
- PRESERVE all [N] citation indices exactly as they appear in the batch reports — do NOT renumber.
- Compile a unified ### References section from all batch reports.
- Include ALL references from the batch reports in the References section — do NOT drop any.
- For each reference, PRESERVE the **Cited Text:** exactly as provided in the batch reports.
- Try to use as many of the provided citations as possible in the body text to support your analysis.

### Pair each observation with the mechanism that explains it
Where a finding has a published explanation, state the observation and then the
mechanism, putting the [N] on the mechanistic clause:

  "Srm and Amd1 decline from 0h to 24h. Polyamine-synthesis genes are direct
   Myc targets [7]."

A citation sitting directly on this dataset's own numbers cannot be checked
against any paper, since no publication contains this experiment's
measurements.

## Experiment Recommendations (IMPORTANT)
- In the "Suggested Follow-up Experiments" section, provide 3-5 specific, actionable experiments.
- For each experiment, include:
  a) The specific experimental technique (e.g., ChIP-seq, ATAC-seq, single-cell RNA-seq, Western blot, RT-qPCR, CRISPR knockout, pharmacological inhibition)
  b) The biological rationale — what finding from the analysis motivates this experiment
  c) The expected outcome — what result would confirm or refute the hypothesis
  d) Priority level (High/Medium/Low) based on strength of evidence and feasibility
- Prioritize experiments that would validate cross-pathway themes or resolve ambiguous findings.
- Where possible, suggest both validation experiments (confirming key findings) and exploratory experiments (investigating novel hypotheses)."""

SYSTEM_PROMPT_EVIDENCE_EXTRACTOR = (
    "You are a precise evidence extraction agent. Extract exact verbatim quotes from the "
    "provided paper. Never fabricate or paraphrase quotes. If the paper does not contain "
    "relevant information, say so explicitly."
)

SYSTEM_PROMPT_VERIFICATION = (
    "You are a citation verification agent. Your job is to check whether a cited text actually "
    "exists in a paper and whether it supports the claim made. Use the provided tools to search "
    "the paper text and fetch specific sections. Respond with a JSON verdict."
)

# ---------------------------------------------------------------------------
# Phase 2: Agentic Literature Discovery — Search Planner + Sub-Agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SEARCH_PLANNER = """You are a strategic PubMed search planner for multi-omics pathway analysis.

Given enriched pathway data, a cross-omic matrix, and experiment context, your job is to
design targeted PubMed search tasks that will find the most relevant literature.

## Priorities (ranked)
1. Hub genes appearing in multiple enriched pathways — these are integration points.
2. Cross-omic contradictions: a gene upregulated in one omic but downregulated in another
   may reveal post-transcriptional regulation, feedback loops, or compensatory mechanisms.
3. Cross-pathway themes: shared regulators, upstream signalling cascades, or metabolic crosstalk.
4. Unexpected or novel patterns: genes showing biphasic dynamics, transient peaks at unusual
   timepoints, or strong effects in minor pathways.

## Output Format
Return a JSON array (no markdown fencing). Each element:
{{
  "task_id": "<short_slug>",
  "query_intent": "<1-sentence biological question this search answers>",
  "target_pathways": ["pathway_name_1", ...],
  "keywords": ["keyword1", "keyword2", ...],
  "pubmed_queries": [
    "<PubMed query string 1>",
    "<PubMed query string 2 (optional refinement)>"
  ]
}}

## CRITICAL: never search a pathway name verbatim
Pathway databases name many entries after the disease in which the pathway was
first characterised — "Human T-cell leukemia virus 1 infection", "Spinocerebellar
ataxia", "Alcoholic liver disease", "Amyotrophic lateral sclerosis". These are
annotation labels, NOT descriptions of the experiment. Searching them literally
returns literature about that disease, which has nothing to do with the system
being studied, and produces citations that are simply wrong.

A pathway is enriched because of the GENES in it. Search the genes and the
mechanism, never the label:

- WRONG: "Human T-cell leukemia virus 1 infection"[Title/Abstract] AND "Mus musculus"[Title/Abstract]
- RIGHT: (Jun OR Fos OR Nfkb1) AND ("B cell differentiation" OR "lymphocyte development")

- WRONG: "Spinocerebellar ataxia"[Title/Abstract]
- RIGHT: (Psmc6 OR Psma7 OR Adrm1) AND ("proteasome" OR "protein degradation")

Only use a pathway name directly when it names a mechanism rather than a disease
("Hippo signaling pathway", "Autophagy", "Arginine and proline metabolism").

## Anchor every query in the experiment
Each query must contain at least one term from the experimental system under
study — its cell type, tissue, developmental process, or perturbation — taken
from the Experiment Context above. A query that would return the same papers for
any experiment is not doing any work. The organism filter alone is not an
anchor: "Mus musculus" matches most of mouse biology.

## PubMed Query Tips
- Use [Title/Abstract] field tag for precision: "MAPK signaling"[Title/Abstract]
- Boolean AND/OR/NOT for combining concepts
- Quote multi-word phrases: "oxidative stress"
- Prefer gene symbols OR'd together, ANDed with a mechanism or process term
- Keep queries focused — broad queries return noisy results
- If a query would only match by disease name, discard it and search the genes

Design at most {max_tasks} search tasks. Aim for specificity over breadth."""

SYSTEM_PROMPT_SEARCH_SUBAGENT = """You are a literature relevance filter for multi-omics research.

Given a set of PubMed paper abstracts and a specific biological question, select the papers
most relevant to answering that question.

## Selection Criteria (ranked)
1. Direct relevance to the biological question and target pathways
2. Mechanistic insight (explains *why* a gene/pathway behaves as observed)
3. Recency (prefer newer papers, all else being equal)
4. Organism match (same organism > closely related model organism > in vitro)

## Output Format
Return a JSON array of PMID strings for the top {max_keep} papers.
Example: ["35486828", "33264437", "28558982"]

If fewer than {max_keep} papers are relevant, return only the relevant ones.
If none are relevant, return an empty array: []"""


def build_search_planner_prompt(pathways, cross_omic_matrix, gene_whitelist,
                                experiment_design, organism_name, max_tasks):
    """Build the user prompt for the search planner LLM call.

    Sections: Experiment Context, Cross-Omic Matrix, Enriched Pathways (sorted by
    significance, top 5 DE genes each), Hub Genes, Task instruction.
    """
    lines = []

    # -- Experiment Context --
    lines.append("## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    # -- Cross-Omic Matrix --
    if cross_omic_matrix:
        lines.append("## Cross-Omic Matrix (gene-level cheat sheet)")
        lines.append(cross_omic_matrix)
        lines.append("")

    # -- Enriched Pathways (sorted by combined p-value) --
    lines.append("## Enriched Pathways")
    sorted_pws = sorted(pathways, key=lambda p: p.get("combined_pvalue", 1.0))
    for pw in sorted_pws:
        lines.append(f"\n### {pw['name']} ({pw['id']}, source: {pw['source']})")
        # Name each figure for what it is. Calling the best-of-conditions value
        # "combined p-value" made reports disagree with the results table, which
        # headlines the global p-value, by orders of magnitude on the same
        # pathway.
        perCondition = pw.get("combined_pvalue_per_condition") or []
        if perCondition:
            lines.append("Combined p-value, best of %d conditions: %.4e"
                         % (len(perCondition), pw["combined_pvalue"]))
            lines.append("Combined p-value per condition: "
                         + ", ".join("%.4e" % v for v in perCondition))
        else:
            lines.append(f"Combined p-value: {pw['combined_pvalue']:.4e}")
        if pw.get("global_pvalue") is not None:
            lines.append("Global p-value (the value shown in the results table): "
                         "%.4e" % pw["global_pvalue"])
        lines.append(f"Per-omic significance: {pw['per_omic']}")
        lines.append(f"Significant omics: {pw.get('significant_omic_count', '?')}")
        # Top 5 DE genes only (keep prompt compact)
        de_genes = [g for g in pw.get("top_genes", []) if g.get("relevant")][:5]
        if de_genes:
            lines.append("Top DE genes:")
            for g in de_genes:
                profiles = g.get("omic_profiles") or []
                if profiles:
                    first = profiles[0]
                    lines.append(
                        f"  {g['symbol']} (|FC|={g['effect_size']}, "
                        f"peak={first['peak_value']}@{first['peak_timepoint']}, "
                        f"pattern={first['pattern']})")
                else:
                    lines.append(f"  {g['symbol']} (|FC|={g['effect_size']})")

    # -- Hub Genes (in ≥2 pathways) --
    gene_pathway_count = {}
    for pw in pathways:
        for g in pw.get("top_genes", []):
            sym = g["symbol"].upper()
            if sym in gene_whitelist:
                gene_pathway_count.setdefault(sym, set()).add(pw["name"])
    hub_genes = {sym: pws for sym, pws in gene_pathway_count.items() if len(pws) >= 2}
    if hub_genes:
        lines.append("\n## Hub Genes (appear in ≥2 pathways)")
        for sym, pws in sorted(hub_genes.items(), key=lambda x: -len(x[1])):
            lines.append(f"  {sym}: {', '.join(sorted(pws))}")

    # -- Task --
    lines.append(f"\n## Task")
    lines.append(f"Design up to {max_tasks} strategic PubMed search tasks.")
    # Query style matters more than query count: natural-language phrases
    # ("PKC signaling in B cell development") return 0-2 hits under a date
    # ceiling, which is how a whole run ends up citing nothing. Boolean
    # queries over 2-3 concrete entities are what PubMed's parser rewards.
    lines.append(
        "Write each query in PubMed search syntax, not natural prose: 2-3 "
        "concrete entities joined with AND (gene/protein symbol, pathway or "
        "process term, optionally the biological system), e.g. "
        '"Ikzf1 AND pre-B cell", "Bcl2 AND autophagy AND regulation". '
        "Avoid filler words; never write a full sentence as a query.")
    lines.append("Return ONLY a JSON array — no markdown fencing, no commentary.")

    return "\n".join(lines)


def build_subagent_filter_prompt(task, papers_with_abstracts, experiment_design,
                                 organism_name, max_keep):
    """Build the user prompt for a search sub-agent filtering papers.

    Args:
        task: dict with task_id, query_intent, target_pathways, keywords.
        papers_with_abstracts: list of paper dicts with pmid, title, first_author,
                               year, journal, abstract.
        experiment_design: str
        organism_name: str
        max_keep: int
    """
    lines = []

    lines.append("## Biological Question")
    lines.append(f"Intent: {task.get('query_intent', 'N/A')}")
    lines.append(f"Target pathways: {', '.join(task.get('target_pathways', []))}")
    lines.append(f"Keywords: {', '.join(task.get('keywords', []))}")
    lines.append("")

    lines.append("## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    lines.append("## Candidate Papers")
    for p in papers_with_abstracts:
        abstract_trunc = (p.get("abstract") or "")[:400]
        lines.append(f"\nPMID: {p['pmid']}")
        lines.append(f"Title: {p.get('title', 'N/A')}")
        lines.append(f"Authors: {p.get('first_author', 'Unknown')} et al.")
        lines.append(f"Journal: {p.get('journal', 'N/A')}, {p.get('year', 'N/A')}")
        if abstract_trunc:
            lines.append(f"Abstract: {abstract_trunc}")

    lines.append(f"\n## Task")
    lines.append(f"Select the top {max_keep} most relevant papers for the biological "
                 f"question above.")
    lines.append("Return ONLY a JSON array of PMID strings — no markdown fencing.")

    return "\n".join(lines)


SYSTEM_PROMPT_CHAT = """You are an expert molecular biologist assistant helping a researcher understand their multi-omics pathway analysis results.
You have access to the analysis report and can answer follow-up questions about the findings.

Rules:
1. Stay grounded in the provided analysis data
2. If asked about something not in the data, say so
3. Be concise but thorough
4. Suggest follow-up experiments when relevant

You have access to tools that can query the original analysis data. Always use tools for exact values rather than guessing from memory. For general questions about the report, answer directly without tools.

Available tools:
- get_gene_timecourse: Query all timepoint values for a specific gene across its omics layers. Use when the researcher asks about expression dynamics, temporal profiles, or exact values for a gene.
- get_pathway_genes: List all matched genes in a pathway with their significance status. Use when the researcher asks which genes were found in a particular pathway.
- compare_genes: Side-by-side comparison of temporal profiles for multiple genes. Use when the researcher asks to compare expression patterns between genes or wants to identify co-regulation."""


def build_two_pass_interpretation_prompt(pathways, papers, experiment_design, organism_name):
    """Build prompt for sub-agent interpretation: abstracts only, with extract_evidence instructions."""
    lines = []
    lines.append("## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    lines.append("## Enriched Pathways")
    for pw in pathways:
        lines.append(f"\n### {pw['name']} ({pw['id']}, source: {pw['source']})")
        # Name each figure for what it is. Calling the best-of-conditions value
        # "combined p-value" made reports disagree with the results table, which
        # headlines the global p-value, by orders of magnitude on the same
        # pathway.
        perCondition = pw.get("combined_pvalue_per_condition") or []
        if perCondition:
            lines.append("Combined p-value, best of %d conditions: %.4e"
                         % (len(perCondition), pw["combined_pvalue"]))
            lines.append("Combined p-value per condition: "
                         + ", ".join("%.4e" % v for v in perCondition))
        else:
            lines.append(f"Combined p-value: {pw['combined_pvalue']:.4e}")
        if pw.get("global_pvalue") is not None:
            lines.append("Global p-value (the value shown in the results table): "
                         "%.4e" % pw["global_pvalue"])
        lines.append(f"Per-omic significance: {pw['per_omic']}")
        lines.append(f"Matched genes: {pw['matched_gene_count']}")
        if pw['top_genes']:
            lines.append("Top genes:")
            for g in pw['top_genes']:
                rel = "DE" if g['relevant'] else "not-DE"
                profiles = g.get('omic_profiles') or []
                if profiles:
                    first = profiles[0]
                    line = (f"  {g['symbol']}({rel}, "
                            f"values=[{first['values']}], "
                            f"peak={first['peak_value']}@{first['peak_timepoint']}, "
                            f"pattern={first['pattern']})")
                    lines.append(line)
                    for prof in profiles[1:]:
                        lines.append(
                            f"    {prof['omic_name']}: "
                            f"values=[{prof['values']}], "
                            f"peak={prof['peak_value']}@{prof['peak_timepoint']}, "
                            f"pattern={prof['pattern']}")
                else:
                    lines.append(f"  {g['symbol']}({rel}, |FC|={g['effect_size']})")

    lines.append("\n## Available Literature")
    if papers:
        for p in papers:
            ft_flag = "[FULL TEXT]" if p.get("full_text_available") else "[ABSTRACT ONLY]"
            lines.append(f"\n[{p['ref_index']}] {p.get('authors_short', p['first_author'])} "
                         f'"{p["title"]}" {p["journal"]}, {p["year"]}. {ft_flag}')
            if p.get("abstract"):
                lines.append(f"    Abstract: {p['abstract'][:500]}")
    else:
        lines.append("No relevant papers found.")

    lines.append("\n## Task")
    lines.append("For each pathway above:")
    lines.append("1. Review paper abstracts to assess relevance to the pathways")
    lines.append("2. For relevant papers with [FULL TEXT], call extract_evidence(ref_index, question) to get detailed findings")
    lines.append("3. Build your interpretation using the evidence returned by extract_evidence")
    lines.append("4. The Cited Text in your References section must use the EXACT quotes returned by extract_evidence")
    lines.append("5. Note any unexpected or contradictory patterns")

    return "\n".join(lines)


def build_batch_interpretation_prompt(pathways, papers, experiment_design, organism_name):
    """Build prompt for interpreting a batch of pathways."""
    lines = []
    lines.append(f"## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    lines.append("## Enriched Pathways")
    for pw in pathways:
        lines.append(f"\n### {pw['name']} ({pw['id']}, source: {pw['source']})")
        # Name each figure for what it is. Calling the best-of-conditions value
        # "combined p-value" made reports disagree with the results table, which
        # headlines the global p-value, by orders of magnitude on the same
        # pathway.
        perCondition = pw.get("combined_pvalue_per_condition") or []
        if perCondition:
            lines.append("Combined p-value, best of %d conditions: %.4e"
                         % (len(perCondition), pw["combined_pvalue"]))
            lines.append("Combined p-value per condition: "
                         + ", ".join("%.4e" % v for v in perCondition))
        else:
            lines.append(f"Combined p-value: {pw['combined_pvalue']:.4e}")
        if pw.get("global_pvalue") is not None:
            lines.append("Global p-value (the value shown in the results table): "
                         "%.4e" % pw["global_pvalue"])
        lines.append(f"Per-omic significance: {pw['per_omic']}")
        lines.append(f"Matched genes: {pw['matched_gene_count']}")
        if pw['top_genes']:
            lines.append("Top genes:")
            for g in pw['top_genes']:
                rel = "DE" if g['relevant'] else "not-DE"
                profiles = g.get('omic_profiles') or []
                if profiles:
                    # Format first omic profile inline with gene symbol
                    first = profiles[0]
                    line = (f"  {g['symbol']}({rel}, "
                            f"values=[{first['values']}], "
                            f"peak={first['peak_value']}@{first['peak_timepoint']}, "
                            f"pattern={first['pattern']})")
                    lines.append(line)
                    # Additional omic profiles on indented lines
                    for prof in profiles[1:]:
                        lines.append(
                            f"    {prof['omic_name']}: "
                            f"values=[{prof['values']}], "
                            f"peak={prof['peak_value']}@{prof['peak_timepoint']}, "
                            f"pattern={prof['pattern']}")
                else:
                    # Fallback: no temporal data available
                    lines.append(f"  {g['symbol']}({rel}, |FC|={g['effect_size']})")

    lines.append("\n## PubMed Evidence")
    if papers:
        for p in papers:
            lines.append(f"\n**{p['title']}** (PMID: {p['pmid']})")
            lines.append(f"  {p['first_author']} et al., {p['journal']} ({p['year']})")
            if p['abstract']:
                lines.append(f"  Abstract: {p['abstract'][:500]}")
    else:
        lines.append("No relevant papers found.")

    lines.append("\n## Task")
    lines.append("For each pathway above:")
    lines.append("1. Explain the biological significance of the enrichment")
    lines.append("2. Interpret key gene expression changes in mechanistic context")
    lines.append("3. Connect findings to published evidence using the provided PMIDs")
    lines.append("4. Note any unexpected or contradictory patterns")

    return "\n".join(lines)


def build_synthesis_prompt(batch_reports, experiment_design, organism_name):
    """Build prompt for synthesizing batch reports into final report."""
    lines = []
    lines.append(f"## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    lines.append("## Batch Interpretation Reports")
    for i, report in enumerate(batch_reports, 1):
        lines.append(f"\n### Batch {i}")
        lines.append(report)

    lines.append("\n## Task")
    lines.append("Synthesize the above batch reports into a unified analysis:")
    lines.append("1. **Key Findings** (3-5 bullet points of the most important discoveries)")
    lines.append("2. **Cross-Pathway Themes** (shared mechanisms, pathway crosstalk)")
    lines.append("3. **Detailed Pathway Analysis** (organized by biological theme, not pathway order)")
    lines.append("4. **Suggested Follow-up Experiments** (2-3 specific, actionable experiments)")
    lines.append("5. **Limitations and Caveats** (data quality issues, missing evidence)")
    lines.append("\nUse markdown formatting. Cite all PMIDs from the batch reports.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# V2 prompt builders
# ---------------------------------------------------------------------------

def build_synthesis_prompt_v2(batch_reports, experiment_design, organism_name, unique_papers):
    """Build synthesis prompt with master reference list for [N] citation preservation."""
    lines = []
    lines.append("## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    lines.append("## Master Reference List")
    lines.append("These are all available references. Preserve [N] indices exactly.")
    for p in unique_papers:
        lines.append(f"[{p['ref_index']}] {p.get('authors_short', p['first_author'])} "
                     f'"{p["title"]}" {p["journal"]}, {p["year"]}. PMID: {p["pmid"]}')
    lines.append("")

    lines.append("## Batch Interpretation Reports")
    for i, report in enumerate(batch_reports, 1):
        lines.append(f"\n### Batch {i}")
        lines.append(report)

    lines.append("\n## Task")
    lines.append("Synthesize the above batch reports into a unified analysis:")
    lines.append("1. **Key Findings** (3-5 bullet points of the most important discoveries)")
    lines.append("2. **Cross-Pathway Themes** (shared mechanisms, pathway crosstalk)")
    lines.append("3. **Detailed Pathway Analysis** (organized by biological theme, not pathway order)")
    lines.append("4. **Suggested Follow-up Experiments** (3-5 prioritized experiments with specific techniques, biological rationale, expected outcomes, and priority levels)")
    lines.append("5. **Limitations and Caveats** (data quality issues, missing evidence)")
    lines.append("\nPreserve all [N] citation indices from batch reports. "
                 "Compile a unified ### References section with **Cited Text:** for each reference.")

    return "\n".join(lines)


def build_verification_prompt(claim_sentence, cited_text, ref_index):
    """Build prompt for a verification sub-agent checking one citation."""
    return f"""Verify the following citation from a scientific report.

## Citation to Verify
**Claim:** {claim_sentence}
**Reference:** [{ref_index}]
**Cited Text:** "{cited_text}"

## Instructions
1. Use search_paper_text(ref_index={ref_index}, query="<key phrase from cited text>") to check if text similar to the Cited Text exists in the paper.
2. If needed, use fetch_paper_section(ref_index={ref_index}, section="results") or section="discussion" to read full sections.
3. Evaluate:
   a) Does the Cited Text (or very similar text) actually appear in the paper? (text_match)
   b) Does the paper content actually support the claim being made? (supports_claim)

Respond with ONLY this JSON (no markdown fencing):
{{
    "text_match": true/false,
    "supports_claim": true/false,
    "reasoning": "brief explanation",
    "actual_text": "the closest matching text found in the paper, if any",
    "suggested_fix": "suggested replacement cited text if text_match is false, or empty string"
}}"""


def build_correction_prompt(report, failed_citations):
    """Build prompt instructing the LLM to correct failed citations in its report."""
    lines = ["## Citation Issues Found", ""]
    lines.append("The following citations in your report have verification problems. "
                 "Please correct them.")
    lines.append("")

    for fc in failed_citations:
        lines.append(f"### [{fc['ref_index']}] Issue")
        lines.append(f"- **Problem:** {fc['reason']}")
        lines.append(f"- **Your Cited Text:** \"{fc['cited_text']}\"")
        if fc.get("actual_text"):
            lines.append(f"- **Actual text found:** \"{fc['actual_text']}\"")
        if fc.get("suggested_fix"):
            lines.append(f"- **Suggested fix:** \"{fc['suggested_fix']}\"")
        lines.append("")

    lines.append("## Instructions")
    lines.append("1. For each issue, either correct the **Cited Text** to match the actual paper, "
                 "or remove the citation if no supporting evidence exists.")
    lines.append("2. Do NOT change citations that were not flagged.")
    lines.append("3. Preserve all [N] reference indices.")
    lines.append("4. Output the COMPLETE corrected report.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-pathway focus report
#
# Generated on demand when a user clicks a pathway citation in the main report,
# then cached. Deliberately narrower than the batch prompt: one pathway, all of
# its genes, and only the literature already attributed to it -- so the answer
# is about this pathway rather than a slice of a cross-pathway synthesis.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_PATHWAY_FOCUS = """You are an expert molecular biologist interpreting a single enriched pathway from a multi-omics experiment.

You are given one pathway, the measured genes that map to it, and the literature already gathered for this analysis. Write a focused interpretation of THIS pathway only.

## Citation Rules (CRITICAL)
- Use numbered citations in the format [N] where N matches the reference index provided.
- NEVER invent citation numbers — only use [N] indices from the Available Literature.
- If no literature is provided, write the interpretation without citations and say so plainly.

## Content Rules
1. ONLY mention genes that appear in the provided data — never introduce genes from memory.
2. State significance using the exact p-values provided.
3. Explain what the measured direction and timing of change imply mechanistically.
4. Where the data is thin or ambiguous, say so rather than overstating.
5. Do NOT speculate about other pathways; this report covers one pathway.

## Output Format
Use markdown with these sections, and no top-level title:
**Summary** — two or three sentences on what this pathway shows in this experiment.
**Key genes** — the informative genes and what their profiles indicate.
**Mechanistic interpretation** — how these changes fit known biology.
**Caveats** — limits of what this pathway result supports.

Keep the whole report under 400 words.
""" + TEMPORAL_GUIDANCE_BLOCK


def build_pathway_focus_prompt(pathway, papers, experiment_design, organism_name):
    """Build the user prompt for a single-pathway interpretation."""
    lines = []
    lines.append("## Experiment Context")
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")

    lines.append("## Pathway")
    lines.append(f"### {pathway['name']} ({pathway['id']}, source: {pathway['source']})")

    # Same naming discipline as the batch prompts: the best-of-conditions value
    # and the global value are different quantities and must not both be called
    # "the combined p-value", or the narrative contradicts the results table.
    pvalue = pathway.get("combined_pvalue")
    perCondition = pathway.get("combined_pvalue_per_condition") or []
    if perCondition:
        lines.append("Combined p-value, best of %d conditions: %.4e"
                     % (len(perCondition), pvalue))
        lines.append("Combined p-value per condition: "
                     + ", ".join("%.4e" % v for v in perCondition))
    elif isinstance(pvalue, (int, float)):
        lines.append(f"Combined p-value: {pvalue:.4e}")
    elif pvalue is not None:
        lines.append(f"Combined p-value per condition: {pvalue}")
    if pathway.get("global_pvalue") is not None:
        lines.append("Global p-value (the value shown in the results table): %.4e"
                     % pathway["global_pvalue"])
    lines.append(f"Per-omic significance: {pathway.get('per_omic')}")
    lines.append(f"Matched genes: {pathway.get('matched_gene_count')}")

    if pathway.get("top_genes"):
        lines.append("Genes:")
        for g in pathway["top_genes"]:
            rel = "DE" if g.get("relevant") else "not-DE"
            profiles = g.get("omic_profiles") or []
            if profiles:
                first = profiles[0]
                lines.append(f"  {g['symbol']}({rel}, "
                             f"values=[{first['values']}], "
                             f"peak={first['peak_value']}@{first['peak_timepoint']}, "
                             f"pattern={first['pattern']})")
                for prof in profiles[1:]:
                    lines.append(f"    {prof['omic_name']}: "
                                 f"values=[{prof['values']}], "
                                 f"peak={prof['peak_value']}@{prof['peak_timepoint']}, "
                                 f"pattern={prof['pattern']}")
            else:
                lines.append(f"  {g['symbol']}({rel}, |FC|={g.get('effect_size')})")

    lines.append("\n## Available Literature")
    if papers:
        for p in papers:
            lines.append(f"\n[{p['ref_index']}] {p.get('authors_short', p.get('first_author', ''))} "
                         f'"{p.get("title", "")}" {p.get("journal", "")}, {p.get("year", "")}')
            if p.get("abstract"):
                lines.append(p["abstract"])
    else:
        lines.append("None was gathered specifically for this pathway. "
                     "Write the interpretation from the data alone and state that no "
                     "pathway-specific literature was retrieved.")

    lines.append("\n## Task")
    lines.append("Write the focused interpretation of this pathway, following the output format.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The full-agent loop (agent_loop.py). One Lead Interpreter drives the whole
# investigation through its toolbelt; these are its standing orders and the
# kickoff message. Design: docs/diagrams/paintomics-ai-agent-proposal.drawio.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_LEAD_AGENT = """You are the Lead Interpreter: an expert \
bioinformatician investigating a multi-omics pathway-enrichment result. You \
work in a loop: look at the data, decide the next most informative action, \
call one tool, read the result, repeat. Keep each turn short.

How to investigate:
1. Start with get_experiment_overview, then cluster_pathways to see which \
pathways share features.
2. Go deep where the data is strongest or strangest: get_pathway_details on \
the top-ranked pathways, compare_gene_profiles on the genes that drive them \
(pass them all in one call).
3. Search the literature with search_literature. BROAD queries only: two or \
three gene symbols joined by OR plus at most one biological term, e.g. \
"(Ikzf1 OR Ccnd2) AND B cell differentiation". A query with three AND clauses \
returns nothing and still spends budget. Use read_paper selectively: for a \
specific claim whose support you are unsure of, not as a routine step before \
citing. Measured over 28 runs, citations whose paper was read first verify no \
better than citations made from the abstract (78 % against 84 %), so reading \
earns its ~2 s when it changes your mind about a paper, not when it confirms \
what the abstract already told you.
4. Get breadth by DELEGATING, not by writing everything yourself: call \
delegate_interpretation a few times, covering all the top-ranked pathways and \
clusters between them. SEARCH FIRST for the pathways you are about to \
delegate, and reuse those pathway names as the topic_tag: a sub-agent is shown \
the papers tagged for its pathways, so delegating before you have found any \
literature for them produces an interpretation with nothing to cite. Each call returns written interpretations carrying your \
reference numbers; your report is the synthesis across those returns plus what \
you found first-hand. This is how fifteen pathways get covered in the time you \
have, and skipping it is why a report ends up covering six.
5. After every substantive discovery, notebook_write one line. The notebook \
is your memory and your evidence trail.
6. Budgets are enforced by the tools and reported in every result; when one \
is exhausted, write with what you have.

Coverage checklist -- you are done when every top-ranked pathway is either \
analysed (with data read and, where possible, literature) or explicitly \
noted as not investigated, and your open questions are resolved or recorded. \
This is a WRITING requirement as much as an investigation one: a pathway you \
looked at but never named in the report is indistinguishable, to the reader, \
from one you ignored. Name every cluster you found and every top-ranked \
pathway in the prose -- with a sentence on what it shows, or a sentence on \
why you set it aside. Budget your turns so that is possible; you have room \
for roughly two dozen investigative tool calls before you must write.

Report rules:
- Cite ONLY [N] indices that search_literature returned. Never invent an index \
or a PMID.
- Before submitting, run check_my_citations on your draft: it names the \
citations that have no supporting quote, which are the ones that will be \
stripped. Fix or drop them rather than shipping them.
- Name only genes that appear in the data tools' output; use exact measured \
values and p-values.
- Structure, all five sections required: ## Key Findings (3-5 bullets), \
## Cross-Pathway Themes, ## Detailed Pathway Analysis -- a paragraph per \
top-ranked pathway or cluster, built from your delegated interpretations \
rather than a bare list -- ## Suggested Follow-up Experiments (3-5, \
prioritised), ## Limitations and Caveats. Leaving out the Detailed Pathway \
Analysis is not an option; most of the report's value sits there.
- Optionally run check_my_citations on your draft first.
- Finish by calling submit_report with the COMPLETE report. That is the only \
way to finish. After it returns SUBMITTED, reply DONE and stop."""


def build_lead_kickoff_prompt(organism_name, experiment_design, pathways,
                              max_turns, search_budget, loop_seconds):
    """The Lead Interpreter's opening message: context, ranked pathways,
    and the budgets the tools will enforce."""
    lines = ["## Experiment"]
    lines.append(f"Organism: {organism_name}")
    if experiment_design:
        lines.append(f"Design: {experiment_design}")
    lines.append("")
    lines.append("## Enriched pathways (ranked by combined p-value)")
    for i, p in enumerate(pathways, 1):
        lines.append(f"{i}. {p.get('name')} ({p.get('id')}, {p.get('source')}) "
                     f"p={p.get('combined_pvalue'):.3g}, "
                     f"{p.get('significant_omic_count', '?')} significant omic "
                     f"layer(s), {p.get('matched_gene_count', '?')} matched genes")
    lines.append("")
    lines.append("## Budgets (enforced by the tools)")
    lines.append(f"- {max_turns} turns; {search_budget} literature searches; "
                 f"~{loop_seconds} s of investigation time")
    lines.append("")
    lines.append("Investigate this experiment and submit your report. "
                 "Begin with get_experiment_overview.")
    return "\n".join(lines)

# The delegated interpreters in the agent loop (agent_loop.delegate_interpretation).
# NOT SYSTEM_PROMPT_INTERPRET, which is the workflow arm's and asks for
# "(PMID: XXXXXXXX)" -- a format the whole gate then has to convert, and one that
# says nothing about whether the claim can be quoted. Measured consequence: the
# delegated reports' citations reached the merge as PMID text, the full-text
# upgrade could not see them, and the citations that did arrive were often
# unquotable and stripped at the net.
#
# So this asks for exactly what survives: [N] markers on claims a sentence in the
# paper actually supports.
SYSTEM_PROMPT_DELEGATED_INTERPRET = """You are an expert molecular biologist \
interpreting part of a multi-omics pathway analysis. Another agent will merge \
your text into a larger report, so write self-contained prose about the pathways \
you are given -- no preamble, no summary of the whole experiment.

Rules:
1. ONLY mention genes that appear in the provided data, with the exact values \
and p-values given.
2. Cite with [N] markers, using the reference numbers exactly as they appear in \
the Available Literature block. Never write PMIDs inline, never invent a number, \
never renumber.
3. Cite a paper only where you could point to a specific sentence in it that \
supports the claim. A citation whose supporting sentence cannot be found is \
removed later along with the sentence carrying it, so an uncited observation is \
worth more than a decorated one.
4. Put the citation on the mechanism, not on this experiment's own numbers -- no \
paper contains these measurements.
5. Say so explicitly where the data is suggestive rather than conclusive.
6. Focus on mechanism: what the changes mean biologically, not a list of genes.
""" + TEMPORAL_GUIDANCE_BLOCK
