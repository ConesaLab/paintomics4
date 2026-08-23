"""
Tool definitions and executors for AI chat function-calling.

Chat tools (for follow-up Q&A):
  - get_gene_timecourse: all timepoint values for a single gene
  - get_pathway_genes: matched genes in a pathway (fuzzy name matching)
  - compare_genes: side-by-side comparison of multiple genes

Interpretation tools (Phase 3 sub-agent):
  - extract_evidence: spawn sub-agent to read full paper and extract evidence

Verification tools (Phase 5 sub-agent):
  - search_paper_text: keyword search within a paper's full text
  - fetch_paper_section: retrieve a specific section of a paper
"""
import logging
import re

from src.classes.AIInterpret.prompts import SYSTEM_PROMPT_EVIDENCE_EXTRACTOR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_gene_timecourse",
            "description": (
                "Return all timepoint values for a gene across every omic layer, "
                "including differential-expression status and timepoint labels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gene_symbol": {
                        "type": "string",
                        "description": "Gene symbol to look up (case-insensitive), e.g. 'TP53'.",
                    }
                },
                "required": ["gene_symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pathway_genes",
            "description": (
                "Return all matched genes in a pathway with their values. "
                "Uses fuzzy name matching (case-insensitive substring). "
                "If no pathway matches, lists available pathway names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pathway_name": {
                        "type": "string",
                        "description": "Pathway name or partial name to search for, e.g. 'MAPK signaling'.",
                    }
                },
                "required": ["pathway_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_genes",
            "description": (
                "Return a side-by-side comparison of values for multiple genes "
                "across all omic layers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gene_symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of gene symbols to compare (max 10).",
                    }
                },
                "required": ["gene_symbols"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_header_map(job_instance):
    """Map omicName -> list of simplified timepoint labels from omicHeader.

    Reads getGeneBasedInputOmics(); for each omic, omicHeader[0] is the gene
    ID column and omicHeader[1:] are the data column labels. Shortening is
    delegated to `context_builder._shorten_condition_labels`, which keeps the
    full column name whenever the short form would make two conditions
    indistinguishable -- this module had its own copy of the truncation and
    would otherwise disagree with the pathway context about what a condition
    is called.
    """
    from .context_builder import _shorten_condition_labels
    header_map = {}
    for omic in job_instance.getGeneBasedInputOmics():
        omic_name = omic.get("omicName", "")
        headers = omic.get("omicHeader")
        if headers and isinstance(headers, list) and len(headers) > 1:
            header_map[omic_name] = _shorten_condition_labels(headers[1:])
        else:
            header_map[omic_name] = None
    return header_map


def _find_gene_by_symbol(job_instance, symbol):
    """Case-insensitive gene lookup.  Returns (gene_id, gene_obj) or None."""
    target = symbol.upper()
    for gene_id, gene_obj in job_instance.getInputGenesData().items():
        if gene_obj.getName() and gene_obj.getName().upper() == target:
            return (gene_id, gene_obj)
    return None


def _find_matching_labels(header_map, n):
    """Find labels from another omic with matching length, else return None."""
    for labels in header_map.values():
        if labels and len(labels) == n:
            return labels
    return None


def _format_gene_omics(gene_obj, header_map):
    """Format all omic values for a gene into a readable string."""
    lines = []
    for ov in gene_obj.getOmicsValues():
        omic_name = ov.getOmicName()
        relevant = ov.isRelevant()
        values = ov.getValues() or []
        labels = header_map.get(omic_name)

        de_status = "DE" if relevant else "not DE"

        if not labels or len(labels) != len(values):
            # Borrow labels from another omic with the same length
            labels = _find_matching_labels(header_map, len(values))

        if labels:
            pairs = [f"{lbl}={v:.3f}" for lbl, v in zip(labels, values)]
            val_str = ", ".join(pairs)
        else:
            val_str = ", ".join(f"{v:.3f}" for v in values)

        lines.append(f"  {omic_name} ({de_status}): [{val_str}]")
    return "\n".join(lines) if lines else "  (no omic data)"


# ---------------------------------------------------------------------------
# Executor functions — each takes (job_instance, args_dict) -> str
# ---------------------------------------------------------------------------

def _exec_get_gene_timecourse(job_instance, args):
    symbol = args.get("gene_symbol", "").strip()
    if not symbol:
        return "Error: gene_symbol is required."

    result = _find_gene_by_symbol(job_instance, symbol)
    if result is None:
        return f"Gene '{symbol}' not found in this dataset."

    gene_id, gene_obj = result
    header_map = _build_header_map(job_instance)
    omics_text = _format_gene_omics(gene_obj, header_map)

    return (
        f"Gene: {gene_obj.getName()} (ID: {gene_id})\n"
        f"Omic profiles:\n{omics_text}"
    )


def _exec_get_pathway_genes(job_instance, args):
    query = args.get("pathway_name", "").strip()
    if not query:
        return "Error: pathway_name is required."

    matched_pathways = job_instance.getMatchedPathways()
    input_genes = job_instance.getInputGenesData()
    query_upper = query.upper()

    # Fuzzy match: case-insensitive substring
    matches = [
        pw for pw in matched_pathways.values()
        if query_upper in pw.name.upper()
    ]

    if not matches:
        available = sorted(set(pw.name for pw in matched_pathways.values()))
        listing = "\n".join(f"  - {n}" for n in available[:30])
        suffix = f"\n  ... and {len(available) - 30} more" if len(available) > 30 else ""
        return (
            f"No pathway matching '{query}'. Available pathways:\n"
            f"{listing}{suffix}"
        )

    header_map = _build_header_map(job_instance)
    parts = []
    for pw in matches[:3]:  # limit to 3 pathway matches
        gene_lines = []
        for gid in pw.matchedGenes:
            gene = input_genes.get(gid)
            if gene is None:
                continue
            name = gene.getName() or gid
            # Brief summary: first omic's values and DE status
            omics = gene.getOmicsValues()
            if omics:
                ov = omics[0]
                vals = ov.getValues() or []
                de = "DE" if ov.isRelevant() else "not DE"
                labels = header_map.get(ov.getOmicName())
                if not labels or len(labels) != len(vals):
                    labels = _find_matching_labels(header_map, len(vals))
                if labels:
                    val_str = ", ".join(f"{l}={v:.3f}" for l, v in zip(labels, vals))
                else:
                    val_str = ", ".join(f"{v:.3f}" for v in vals)
                gene_lines.append(f"  {name} ({de}): [{val_str}]")
            else:
                gene_lines.append(f"  {name}: (no data)")

        genes_text = "\n".join(gene_lines) if gene_lines else "  (no matched genes)"
        parts.append(
            f"Pathway: {pw.name} (ID: {pw.ID})\n"
            f"Matched genes ({len(pw.matchedGenes)}):\n{genes_text}"
        )

    return "\n\n".join(parts)


def _exec_compare_genes(job_instance, args):
    symbols = args.get("gene_symbols", [])
    if not symbols:
        return "Error: gene_symbols list is required."
    if len(symbols) > 10:
        symbols = symbols[:10]

    header_map = _build_header_map(job_instance)
    parts = []
    for sym in symbols:
        result = _find_gene_by_symbol(job_instance, sym.strip())
        if result is None:
            parts.append(f"Gene: {sym} — NOT FOUND")
        else:
            gene_id, gene_obj = result
            omics_text = _format_gene_omics(gene_obj, header_map)
            parts.append(f"Gene: {gene_obj.getName()} (ID: {gene_id})\n{omics_text}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_EXECUTORS = {
    "get_gene_timecourse": _exec_get_gene_timecourse,
    "get_pathway_genes": _exec_get_pathway_genes,
    "compare_genes": _exec_compare_genes,
}


def execute_tool(tool_name, job_instance, arguments):
    """Route a tool call to the correct executor. Returns a result string."""
    executor = _EXECUTORS.get(tool_name)
    if executor is None:
        return f"Error: unknown tool '{tool_name}'."
    try:
        return executor(job_instance, arguments)
    except Exception as e:
        logger.exception(f"Tool execution error ({tool_name})")
        return f"Error executing {tool_name}: {str(e)}"


# ===========================================================================
# Interpretation tools — Phase 3 sub-agent evidence extraction
# ===========================================================================



def build_interpretation_executor(paper_index, llm):
    """Factory: returns a tool executor callable(name, args) -> str for interpretation tools.

    Args:
        paper_index: {ref_index: paper_dict} mapping.
        llm: LLMClient instance for sub-agent calls.
    """
    def executor(tool_name, args):
        if tool_name == "extract_evidence":
            return _exec_extract_evidence(paper_index, llm, args)
        return f"Error: unknown interpretation tool '{tool_name}'."
    return executor


def _exec_extract_evidence(paper_index, llm, args):
    """Spawn a sub-agent to read full paper text and extract evidence.

    The sub-agent runs in its own LLM context with the full paper text.
    Only the compact result (~150 tokens) flows back to the main agent.
    """
    ref_idx = args.get("ref_index")
    question = args.get("question", "")

    if ref_idx is None:
        return "Error: ref_index is required."

    paper = paper_index.get(int(ref_idx))
    if not paper:
        return f"Error: No paper with reference index [{ref_idx}]."

    # Build sub-agent context with full paper text (ephemeral)
    paper_text_parts = []
    for section in ["abstract", "introduction", "results", "discussion", "other"]:
        text = paper.get("sections", {}).get(section)
        if text:
            paper_text_parts.append(f"## {section.title()}\n{text}")

    paper_content = "\n\n".join(paper_text_parts) if paper_text_parts else paper.get("abstract", "")

    if not paper_content.strip():
        return (f"FINDING: No text available for paper [{ref_idx}].\n"
                f"CITED_TEXT: \"\"\nRELEVANCE: NONE")

    sub_prompt = (
        f'Paper [{ref_idx}]: {paper.get("authors_short", paper.get("first_author", "Unknown"))} '
        f'"{paper["title"]}" {paper["journal"]}, {paper["year"]}.\n\n'
        f'{paper_content}\n\n'
        f'---\nQuestion: {question}\n\n'
        f'Extract a specific finding from this paper that answers the question.\n'
        f'You MUST respond in EXACTLY this format:\n\n'
        f'FINDING: <one or two sentence summary of the relevant finding>\n'
        f'CITED_TEXT: "<exact verbatim quote from the paper text above that supports '
        f'the finding - do NOT paraphrase>"\n'
        f'RELEVANCE: <HIGH/MEDIUM/LOW>\n\n'
        f'If the paper does not contain relevant information, respond with:\n'
        f'FINDING: No relevant evidence found.\n'
        f'CITED_TEXT: ""\n'
        f'RELEVANCE: NONE'
    )

    try:
        result = llm.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_EVIDENCE_EXTRACTOR},
                {"role": "user", "content": sub_prompt},
            ],
            max_tokens=500,
            temperature=0.1,
        )
        return result
    except Exception as e:
        logger.exception(f"Evidence extraction sub-agent failed for [{ref_idx}]")
        return (f"FINDING: Evidence extraction failed ({e}).\n"
                f"CITED_TEXT: \"\"\nRELEVANCE: NONE")


# ===========================================================================
# Verification tools — Phase 5 citation verification sub-agents
# ===========================================================================



def build_verification_executor(paper_index):
    """Factory: returns a tool executor callable(name, args) -> str for verification tools."""
    def executor(tool_name, args):
        if tool_name == "search_paper_text":
            return _exec_search_paper_text(paper_index, args)
        if tool_name == "fetch_paper_section":
            return _exec_fetch_paper_section(paper_index, args)
        return f"Error: unknown verification tool '{tool_name}'."
    return executor


def _exec_search_paper_text(paper_index, args):
    """Substring + keyword-overlap search within a paper's full text.

    Returns up to 3 matching passages with 200-char context windows.
    """
    ref_idx = args.get("ref_index")
    query = args.get("query", "").strip()

    if ref_idx is None or not query:
        return "Error: ref_index and query are required."

    paper = paper_index.get(int(ref_idx))
    if not paper:
        return f"Error: No paper with reference index [{ref_idx}]."

    # Concatenate all available sections
    sections = paper.get("sections", {})
    full_text = "\n\n".join(
        f"[{name.upper()}] {text}"
        for name, text in sections.items()
        if text
    )
    if not full_text:
        return f"No text available for paper [{ref_idx}]."

    full_text_lower = full_text.lower()
    query_lower = query.lower()

    # Strategy 1: Direct substring search
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

    # Strategy 2: keyword overlap if no direct matches
    if not matches:
        keywords = set(re.findall(r'\b\w{4,}\b', query_lower))
        if keywords:
            # Sliding window search
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
        return f"No passages matching '{query}' found in paper [{ref_idx}]."

    result_parts = [f"Found {len(matches)} passage(s) in paper [{ref_idx}]:"]
    for i, m in enumerate(matches, 1):
        # Truncate long matches
        if len(m) > 400:
            m = m[:400] + "..."
        result_parts.append(f"\n--- Passage {i} ---\n{m}")

    return "\n".join(result_parts)


def _exec_fetch_paper_section(paper_index, args):
    """Fetch a specific section from a paper."""
    ref_idx = args.get("ref_index")
    section = args.get("section", "").strip().lower()

    if ref_idx is None or not section:
        return "Error: ref_index and section are required."

    paper = paper_index.get(int(ref_idx))
    if not paper:
        return f"Error: No paper with reference index [{ref_idx}]."

    valid_sections = {"abstract", "introduction", "results", "discussion", "other"}
    if section not in valid_sections:
        return f"Error: section must be one of {valid_sections}."

    text = paper.get("sections", {}).get(section)
    if not text:
        available = [s for s in valid_sections if paper.get("sections", {}).get(s)]
        return (f"Section '{section}' not available for paper [{ref_idx}]. "
                f"Available: {available or 'none'}.")

    # Truncate if very long for context management
    if len(text) > 6000:
        text = text[:6000] + "\n... [truncated]"

    return f"[{section.upper()}] from paper [{ref_idx}]:\n{text}"
