import re
import difflib
import unicodedata
from src.conf.serverconf import AI_VERIFICATION_FUZZY_THRESHOLD

# ---------------------------------------------------------------------------
# Legacy verification (kept for backward compat)
# ---------------------------------------------------------------------------

def verify_report(report_text, gene_whitelist, collected_papers, job_instance):
    """
    Returns {"score": 0.0-1.0, "issues": [...], "gene_accuracy": float, "pmid_accuracy": float}
    Gene check is informational only — does NOT trigger redaction.
    Only fabricated PMIDs trigger redaction.
    """
    issues = []

    # 1. Gene whitelist check (informational — many valid gene family names won't be in the dataset)
    mentioned_genes = _extract_gene_mentions(report_text)
    valid_genes = sum(1 for g in mentioned_genes if g.upper() in gene_whitelist)
    gene_accuracy = valid_genes / max(len(mentioned_genes), 1)
    gene_issues = []
    for g in mentioned_genes:
        if g.upper() not in gene_whitelist:
            gene_issues.append(f"Gene '{g}' not found in analysis data")

    # 2. PMID existence check — this is the critical one
    cited_pmids = set(re.findall(r'PMID[:\s]*(\d{7,8})', report_text))
    paper_pmids = {p["pmid"] for p in collected_papers}
    valid_pmids = cited_pmids & paper_pmids
    pmid_accuracy = len(valid_pmids) / max(len(cited_pmids), 1)
    pmid_issues = []
    for pmid in cited_pmids - paper_pmids:
        pmid_issues.append(f"PMID {pmid} not in retrieved papers")
    issues.extend(pmid_issues)

    # 3. P-value check (informational)
    pval_issues = _check_pvalues(report_text, job_instance)
    issues.extend(pval_issues)

    # Gene issues are informational only — add them but don't use for redaction
    issues.extend(gene_issues)

    # Score: weight PMID accuracy heavily, gene accuracy lightly (too many false positives)
    score = 0.5 * pmid_accuracy + 0.2 * gene_accuracy + 0.3 * (1 - min(len(pval_issues) / 5, 1))
    return {"score": round(score, 2), "issues": issues,
            "gene_accuracy": round(gene_accuracy, 2), "pmid_accuracy": round(pmid_accuracy, 2)}


def redact_unverified(text, issues):
    """Remove sentences containing fabricated PMIDs only. Gene issues are informational."""
    # Only redact for fabricated PMIDs — gene mentions are too noisy for redaction
    bad_pmids = {i.split("PMID ")[1].split(" ")[0] for i in issues if "PMID " in i and "not in" in i}
    if not bad_pmids:
        return text, 0

    sentences = re.split(r'(?<=[.!?])\s+', text)
    clean = []
    removed = 0
    for s in sentences:
        if any(p in s for p in bad_pmids):
            removed += 1
        else:
            clean.append(s)
    result = " ".join(clean)
    if removed:
        result += f"\n\n> **Note:** {removed} statement(s) with unverified citations were removed."
    return result, removed


# ---------------------------------------------------------------------------
# PMID → [N] citation conversion
# ---------------------------------------------------------------------------

def convert_pmid_citations(report_text, papers):
    """Convert [PMID:XXXXXXXX] citations to [N] format using paper ref_index.

    Handles variants: [PMID:12345678], [PMID: 12345678], [PMID:12345678, PMID:23456789]
    """
    pmid_to_ref = {str(p["pmid"]): p["ref_index"] for p in papers if p.get("ref_index")}

    def _replace_single(match):
        pmid = match.group(1).strip()
        ref = pmid_to_ref.get(pmid)
        if ref is not None:
            return f"[{ref}]"
        return match.group(0)

    # Handle single PMID citations: [PMID:12345678] or [PMID: 12345678]
    result = re.sub(r'\[PMID:\s*(\d{7,8})\]', _replace_single, report_text)

    # Handle comma-separated multi-citations: [PMID:111, PMID:222]
    def _replace_multi(match):
        inner = match.group(1)
        parts = re.split(r',\s*', inner)
        refs = []
        for part in parts:
            m = re.match(r'PMID:\s*(\d{7,8})', part.strip())
            if m:
                pmid = m.group(1).strip()
                ref = pmid_to_ref.get(pmid)
                if ref is not None:
                    refs.append(str(ref))
                else:
                    return match.group(0)  # can't convert all → leave as-is
            else:
                return match.group(0)
        return "[" + ", ".join(refs) + "]"

    result = re.sub(r'\[(PMID:\s*\d{7,8}(?:\s*,\s*PMID:\s*\d{7,8})+)\]', _replace_multi, result)

    return result


# ---------------------------------------------------------------------------
# V2 verification — [N] citation format with fuzzy text matching
# ---------------------------------------------------------------------------

def verify_report_v2(report_text, gene_whitelist, unique_papers, job_instance):
    """Verify a report using [N] citation format.

    Returns {
        "score": float,
        "failed_citations": [{"ref_index", "reason", "cited_text", "claim_sentence"}],
        "gene_accuracy": float,
        "ref_accuracy": float,
    }
    """
    paper_index = {p["ref_index"]: p for p in unique_papers}
    valid_ref_indices = set(paper_index.keys())

    # 1. Parse references section
    parsed_refs = parse_references_section(report_text)

    # 2. Check [N] indices in body text
    body_indices = set(int(m) for m in re.findall(r'\[(\d+)\]', report_text))
    invalid_indices = body_indices - valid_ref_indices

    failed_citations = []

    # Flag invalid reference indices
    for idx in invalid_indices:
        failed_citations.append({
            "ref_index": idx,
            "reason": f"Reference [{idx}] not in available papers",
            "cited_text": "",
            "claim_sentence": "",
            "actual_text": "",
            "suggested_fix": "",
        })

    # 3. Fuzzy-match cited text against paper sections
    for ref_entry in parsed_refs:
        ref_idx = ref_entry["ref_index"]
        cited_text = ref_entry.get("cited_text", "").strip()

        if ref_idx not in valid_ref_indices:
            continue  # already flagged above

        if not cited_text:
            failed_citations.append({
                "ref_index": ref_idx,
                "reason": f"Reference [{ref_idx}] has no Cited Text",
                "cited_text": "",
                "claim_sentence": ref_entry.get("claim_sentence", ""),
                "actual_text": "",
                "suggested_fix": "",
            })
            continue

        paper = paper_index[ref_idx]
        # Concatenate all sections for searching
        all_text = " ".join(
            text for text in paper.get("sections", {}).values() if text
        )

        if not all_text:
            # Only abstract available — use it
            all_text = paper.get("abstract", "")

        if not _fuzzy_contains(all_text, cited_text, AI_VERIFICATION_FUZZY_THRESHOLD):
            failed_citations.append({
                "ref_index": ref_idx,
                "reason": f"Cited text for [{ref_idx}] not found in paper (fuzzy match failed)",
                "cited_text": cited_text,
                "claim_sentence": ref_entry.get("claim_sentence", ""),
                "actual_text": "",
                "suggested_fix": "",
            })

    # 4. Gene whitelist check (informational)
    mentioned_genes = _extract_gene_mentions(report_text)
    valid_genes = sum(1 for g in mentioned_genes if g.upper() in gene_whitelist)
    gene_accuracy = valid_genes / max(len(mentioned_genes), 1)

    # 5. Compute ref accuracy
    total_refs = len(parsed_refs) + len(invalid_indices)
    failed_count = len(failed_citations)
    ref_accuracy = (total_refs - failed_count) / max(total_refs, 1)

    # 6. P-value check (informational)
    pval_issues = _check_pvalues(report_text, job_instance)

    score = 0.5 * ref_accuracy + 0.2 * gene_accuracy + 0.3 * (1 - min(len(pval_issues) / 5, 1))

    return {
        "score": round(score, 2),
        "failed_citations": failed_citations,
        "gene_accuracy": round(gene_accuracy, 2),
        "ref_accuracy": round(ref_accuracy, 2),
    }


def redact_unverified_v2(report_text, failed_citations):
    """Remove sentences citing failed [N] indices and their References entries.

    Returns (cleaned_report, removed_count).
    """
    if not failed_citations:
        return report_text, 0

    bad_indices = {fc["ref_index"] for fc in failed_citations}
    bad_patterns = {f"[{idx}]" for idx in bad_indices}

    # Split report into body and references
    ref_header_match = re.search(r'^### References\s*$', report_text, re.MULTILINE)

    if ref_header_match:
        body = report_text[:ref_header_match.start()]
        refs_section = report_text[ref_header_match.start():]
    else:
        body = report_text
        refs_section = ""

    # Remove body sentences that cite bad indices
    sentences = re.split(r'(?<=[.!?])\s+', body)
    clean_sentences = []
    removed = 0
    for s in sentences:
        if any(bp in s for bp in bad_patterns):
            removed += 1
        else:
            clean_sentences.append(s)
    clean_body = " ".join(clean_sentences)

    # Remove bad reference entries from References section
    if refs_section:
        ref_lines = refs_section.split("\n")
        clean_ref_lines = []
        skip_entry = False
        for line in ref_lines:
            # Check if this line starts a new reference entry
            ref_match = re.match(r'\[(\d+)\]', line.strip())
            if ref_match:
                idx = int(ref_match.group(1))
                skip_entry = idx in bad_indices
                if skip_entry:
                    removed += 1
                    continue
            elif skip_entry:
                # Skip continuation lines of a bad entry (indented lines)
                if line.startswith("    ") or line.strip().startswith("**Cited Text:**"):
                    continue
                else:
                    skip_entry = False
            clean_ref_lines.append(line)
        refs_section = "\n".join(clean_ref_lines)

    result = clean_body.rstrip()
    if refs_section.strip():
        result += "\n\n" + refs_section.rstrip()

    if removed:
        result += f"\n\n> **Note:** {removed} citation(s) with unverified references were removed."

    return result, removed


def renumber_citations(report_text):
    """Renumber [N] citations sequentially starting from [1].

    After redaction or synthesis, citations may have gaps (e.g., [7], [11], [18]).
    This function remaps them to [1], [2], [3]... consistently across body and References.

    Returns (renumbered_report, old_to_new_mapping).
    """
    # 1. Collect all [N] indices used in the report (body + references), in order of first appearance
    all_indices = []
    seen = set()
    for m in re.finditer(r'\[(\d+)\]', report_text):
        idx = int(m.group(1))
        if idx not in seen:
            all_indices.append(idx)
            seen.add(idx)

    if not all_indices:
        return report_text, {}

    # Check if already sequential starting from 1
    if all_indices == list(range(1, len(all_indices) + 1)):
        return report_text, {i: i for i in all_indices}

    # 2. Build old -> new mapping (preserve order of first appearance)
    old_to_new = {}
    for new_idx, old_idx in enumerate(all_indices, 1):
        old_to_new[old_idx] = new_idx

    # 3. Replace all [N] occurrences — use placeholder to avoid collision
    # e.g., if [2] -> [1] and [1] -> [3], direct replacement would corrupt
    result = report_text

    # First pass: replace [old] with unique placeholders
    for old_idx in sorted(old_to_new.keys(), reverse=True):
        # Use a placeholder that can't appear naturally in text
        placeholder = f"__CITE_PLACEHOLDER_{old_to_new[old_idx]}__"
        result = result.replace(f"[{old_idx}]", placeholder)

    # Second pass: replace placeholders with final [new] indices
    for new_idx in range(1, len(all_indices) + 1):
        result = result.replace(f"__CITE_PLACEHOLDER_{new_idx}__", f"[{new_idx}]")

    return result, old_to_new


def parse_references_section(report_text):
    """Parse ### References section from a report.

    Returns list of {
        "ref_index": int,
        "cited_text": str,
        "claim_sentence": str,  # first body sentence citing this ref
        "author": str,
        "title": str,
    }
    """
    # Find References section
    ref_match = re.search(r'^### References\s*$', report_text, re.MULTILINE)
    if not ref_match:
        return []

    body = report_text[:ref_match.start()]
    refs_text = report_text[ref_match.end():]

    # Parse each reference entry
    # Pattern: [N] Author "Title" Journal, Year.
    entries = []
    # Split by reference entries starting with [N]
    ref_pattern = re.compile(r'^\[(\d+)\]\s*(.+)', re.MULTILINE)
    matches = list(ref_pattern.finditer(refs_text))

    for i, m in enumerate(matches):
        ref_idx = int(m.group(1))
        header_line = m.group(2).strip()

        # Extract the block of text until the next reference entry
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(refs_text)
        block = refs_text[m.start():block_end]

        # Extract Cited Text
        cited_match = re.search(r'\*\*Cited Text:\*\*\s*"([^"]*)"', block)
        cited_text = cited_match.group(1) if cited_match else ""

        # Extract author and title from header line
        title_match = re.search(r'"([^"]+)"', header_line)
        title = title_match.group(1) if title_match else ""
        author = header_line.split('"')[0].strip().rstrip('.')

        # Find claim sentence in body that cites this ref
        claim_sentence = ""
        ref_tag = f"[{ref_idx}]"
        body_sentences = re.split(r'(?<=[.!?])\s+', body)
        for sent in body_sentences:
            if ref_tag in sent:
                claim_sentence = sent.strip()
                break

        entries.append({
            "ref_index": ref_idx,
            "cited_text": cited_text,
            "claim_sentence": claim_sentence,
            "author": author,
            "title": title,
        })

    return entries


# ---------------------------------------------------------------------------
# Fuzzy text matching
# ---------------------------------------------------------------------------

def _fuzzy_contains(haystack, needle, threshold=None):
    """3-tier matching: exact substring → normalized substring → sliding-window fuzzy.

    Args:
        haystack: The full paper text to search in.
        needle: The cited text to find.
        threshold: Minimum SequenceMatcher ratio for fuzzy match.

    Returns:
        True if needle is found in haystack at the given threshold.
    """
    if threshold is None:
        threshold = AI_VERIFICATION_FUZZY_THRESHOLD

    if not haystack or not needle:
        return False

    # Tier 1: Exact substring (fast path)
    if needle in haystack:
        return True

    # Tier 2: Normalized substring (lowercase, strip punctuation/extra whitespace)
    norm_haystack = _normalize_text(haystack)
    norm_needle = _normalize_text(needle)

    if norm_needle and norm_needle in norm_haystack:
        return True

    # Tier 3: Sliding-window SequenceMatcher
    if len(norm_needle) < 20:
        # Too short for reliable fuzzy matching
        return False

    needle_len = len(norm_needle)
    best_ratio = 0.0

    # Slide window over haystack in steps of needle_len/3
    step = max(needle_len // 3, 10)
    for start in range(0, max(1, len(norm_haystack) - needle_len + 1), step):
        window = norm_haystack[start:start + needle_len + needle_len // 4]
        ratio = difflib.SequenceMatcher(None, norm_needle, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
        if best_ratio >= threshold:
            return True

    return best_ratio >= threshold


def _normalize_text(text):
    """Lowercase, strip punctuation and collapse whitespace for fuzzy comparison."""
    text = text.lower()
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    # Remove punctuation except alphanumeric and whitespace
    text = re.sub(r'[^\w\s]', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Common words and abbreviations that look like gene symbols but aren't
_COMMON_WORDS = frozenset({
    # English words
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "WAS",
    "ONE", "OUR", "OUT", "HAS", "HIS", "HOW", "ITS", "MAY", "NEW", "NOW", "OLD",
    "SEE", "WAY", "WHO", "DID", "GET", "LET", "SAY", "SHE", "TOO", "USE",
    "KEY", "ALSO", "BEEN", "CALL", "COME", "EACH", "FIND", "HAVE", "INTO",
    "MADE", "MANY", "MOST", "MUCH", "MUST", "NAME", "ONLY", "OVER", "SUCH",
    "TAKE", "THAN", "THAT", "THEM", "THEN", "THIS", "VERY", "WHEN", "WILL",
    "WITH", "FROM", "SOME", "WHAT", "MORE", "WERE", "HERE", "JUST", "LIKE",
    "THESE", "THOSE", "OTHER", "WHICH", "THEIR", "THERE", "ABOUT", "WOULD",
    "COULD", "BEING", "AFTER", "BELOW", "ABOVE", "BASED", "GIVEN", "SHOWN",
    "RESULTS", "TABLE", "FIGURE", "HOWEVER", "PATHWAY", "PATHWAYS",
    "ABSTRACT", "METHODS", "ANALYSIS", "BETWEEN", "THROUGH", "BECAUSE",
    "OVERALL", "SUGGEST", "SEVERAL", "FURTHER", "KNOWN", "FOUND", "USING",
    "WHILE", "WHERE", "SINCE", "NOTED", "LEVEL", "LEVELS", "GENES", "STUDY",
    "DATA", "TYPE", "ROLE", "CELL", "HIGH", "BOTH", "WELL", "THUS", "ALSO",
    "FIRST", "SECOND", "THIRD", "NOTE", "UPON", "NEXT", "ONLY", "DONE",
    # Scientific/bioinformatics abbreviations
    "DNA", "RNA", "ATP", "GTP", "ADP", "NAD", "FAD", "SAM", "UDP", "AMP",
    "PCR", "SNP", "UTR", "CDS", "ORF", "TSS", "TTS",
    "FC", "DE", "FDR", "LOG", "SD", "SE", "CI", "OR", "HR", "RR",
    "GO", "BP", "MF", "CC",  # Gene Ontology terms
    "KEGG", "MAPK", "MTOR", "AMPK", "VEGF", "ERBB",  # Pathway names (not individual genes)
    "MHC", "TCR", "BCR", "TLR", "NLR", "RIG",  # Receptor family names
    "TNF", "TGF", "EGF", "FGF", "IGF", "NGF", "PDGF", "CSF",  # Growth factor families
    "AGE", "RAGE", "SASP",  # Biological process abbreviations
    "HPV", "HIV", "HBV", "HCV", "HSV", "HTLV", "EBV", "CMV",  # Virus names
    "NK", "DC", "TH", "TH1", "TH2", "TH17", "TREG",  # Immune cell types
    "ER", "PM", "ECM",  # Cellular compartments
    "WNT", "JAK", "STAT", "RAS", "PI3K", "AKT", "NOTCH",  # Signaling pathway names
    "ATAC", "CHIP", "HIC",  # Assay types
    "H2", "H3", "H4", "K4", "K9", "K27", "K36",  # Histone marks
    "D1", "D2", "D3", "G1", "G2", "S1", "S2", "M1", "M2",  # Cell cycle / numbered terms
    "Q1", "Q2", "Q3", "Q4",  # Quantile labels
    "K1", "K2", "K3",  # Cluster labels
    "VS", "WT", "KO", "KD", "OE", "CTL", "CTRL",  # Experimental terms
    "PMID", "DOI", "REF",  # Citation terms
    "IL", "IFN", "CCL", "CXCL", "CCR", "CXCR",  # Cytokine/chemokine families
    "MM", "BP", "KB", "MB", "GB",  # Units
    "PC", "PCA", "UMAP", "TSNE",  # Analysis methods
    "DNase", "RNase",  # Enzyme types
    "GNRH", "GABA", "NMDA", "AMPA",  # Neurotransmitter terms
})

def _extract_gene_mentions(text):
    """Extract likely gene symbols — require at least 2 uppercase chars and filter common words."""
    candidates = set(re.findall(r'\b([A-Z][A-Z0-9][A-Za-z0-9]{0,6})\b', text))
    return [g for g in candidates if g.upper() not in _COMMON_WORDS]

def _check_pvalues(text, job_instance):
    issues = []
    matches = re.findall(r'p[\s-]*(?:value)?[\s=<]*(\d+\.?\d*(?:e[+-]?\d+)?)', text, re.IGNORECASE)
    actual_pvals = {}
    for pw in job_instance.getMatchedPathways().values():
        for method, val in pw.combinedSignificancePvalues.items():
            actual_pvals[f"{val:.4f}"] = pw.name
    for claimed in matches[:10]:
        try:
            claimed_f = float(claimed)
            if not any(abs(claimed_f - float(actual)) / max(float(actual), 1e-10) < 0.5
                       for actual in actual_pvals):
                issues.append(f"Claimed p-value {claimed} doesn't match any pathway")
        except ValueError:
            pass
    return issues
