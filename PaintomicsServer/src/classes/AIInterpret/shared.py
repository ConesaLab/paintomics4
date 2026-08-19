"""Helpers the agent workflow shares with the verification machinery.

Citation plumbing (_build_local_paper_index / _remap_citation_indices), the
quote collector and the sentence/quote matchers it depends on, the tolerant
JSON-verdict parser, and the shared-gene-core prompt block (round-2 KEEP of
the evolve loop). Orchestration lives in agent.py; this module is the domain
logic it calls and must stay importable without the SDK.
"""
import json
import logging
import os
import re
from concurrent.futures import (ThreadPoolExecutor, as_completed,
                                TimeoutError as FuturesTimeout)
from difflib import SequenceMatcher

from src.conf.serverconf import AI_VERIFICATION_WORKERS
from src.classes.AIInterpret.llm_client import SHORT_CALL_TIMEOUT
# Reused so a quote is held to the same matching rule that will later judge
# it; a private import beats a second, subtly different matcher.
from src.classes.AIInterpret.verification import _fuzzy_contains, _normalize_text

logger = logging.getLogger(__name__)


CITED_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "cited_text": {
            "type": "string",
            "description": "Verbatim sentence from the paper, or empty if none supports the claim",
        },
        "supports": {"type": "boolean"},
    },
    "required": ["cited_text", "supports"],
    "additionalProperties": False,
}


def _quote_source_text(paper, max_chars=None):
    """Text a supporting quote may be drawn from: full text if we fetched it.

    The same text is handed to the verifier's tools later, so quote extraction
    and quote checking read from one source. If they disagreed -- extract from
    the abstract, verify against full text or the reverse -- valid citations
    would be refuted for being in the wrong half of the paper.

    The budget is split per section rather than cut once from the top.
    Sections arrive in document order (introduction first), so a flat
    ``text[:max_chars]`` kept abstract + introduction and silently discarded
    Results and Discussion: across every stored report, not one citation was
    ever labelled "full text (results)". The sentences that support a
    mechanistic claim live exactly there, so each non-empty section now gets
    an equal share of what remains (an underfull section's share rolls over),
    with the abstract taken in full first -- it is short, and its one-sentence
    statements of the finding are the strongest quote candidates.
    """
    if max_chars is None:
        max_chars = int(os.getenv("AI_QUOTE_SOURCE_CHARS", "18000"))
    sections = paper.get("sections") or {}
    if sections:
        remaining = max_chars
        parts = []
        abstract = (sections.get("abstract") or "").strip()
        if abstract:
            parts.append(abstract[:remaining])
            remaining -= len(parts[-1]) + 1
        # Results and Discussion ahead of Introduction: when the budget is
        # tight, the front matter is what a quote can best afford to lose.
        rest = [k for k in ("results", "discussion", "introduction", "other")
                if (sections.get(k) or "").strip()]
        rest += [k for k in sections
                 if k != "abstract" and k not in rest and (sections[k] or "").strip()]
        for i, key in enumerate(rest):
            if remaining <= 200:
                break
            share = remaining // (len(rest) - i)
            chunk = sections[key].strip()[:share]
            if chunk:
                parts.append(chunk)
                remaining -= len(chunk) + 1
        text = "\n".join(parts).strip()
        if text:
            return text
    return (paper.get("abstract") or "")[:max_chars]


def _snap_quote_to_source(quote, source_text):
    """Return the source's own wording for `quote`, or "" if nothing matches.

    Models paraphrase however firmly they are told not to, and a paraphrased
    "quote" is then correctly refuted by the verifier for not appearing in the
    paper -- which is how a tuned run reached "6 checked, 6 failed" on all three
    verification iterations without a single genuine problem. The verifier was
    right; the quote was never really from the paper.

    So the model's answer is treated as a *pointer* to the right sentence rather
    than as the citation itself. If it already matches, keep it; otherwise snap
    to the source sentence it resembles most. Dropping the quote entirely is the
    honest fallback -- verify_report_v2 then reports it unverifiable instead of
    the report carrying words the paper never said.
    """
    if not quote or not source_text:
        return ""
    if _fuzzy_contains(source_text, quote):
        return quote

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', source_text)
                 if len(s.strip()) > 30]
    if not sentences:
        return ""

    best, best_score = "", 0.0
    for sentence in sentences:
        score = SequenceMatcher(None, _normalize_text(quote),
                                _normalize_text(sentence)).ratio()
        if score > best_score:
            best, best_score = sentence, score
    # Below this the "closest" sentence is just the least unrelated one, and
    # substituting it would attach the claim to whatever the paper happened to
    # say instead of admitting there is no support.
    return best if best_score >= 0.45 else ""


def _claim_sentences_for(body, ref_index, limit=3):
    """Sentences citing [ref_index], most citable first.

    A reference is usually cited more than once, and only some of those
    sentences are the kind a paper can support. Taking the first one was
    costing citations outright: if it happened to be "Bcl2 peaks at 3.058 at
    24h" the lookup returned "no support" and the whole citation was dropped,
    even when the same reference also sat on a mechanistic sentence two
    paragraphs down that any relevant paper could back.

    Ranking is by digit density. Sentences thick with numbers are this
    dataset's own measurements, which no publication contains; sentences
    without them are the mechanistic statements that literature can confirm.
    """
    tag = "[%d]" % ref_index
    matches = [s.strip()[:600] for s in re.split(r'(?<=[.!?])\s+', body)
               if tag in s]
    if not matches:
        return []

    def _numeric_density(sentence):
        return sum(c.isdigit() for c in sentence) / max(len(sentence), 1)

    return sorted(matches, key=_numeric_density)[:limit]



def _collect_cited_quotes(llm, report, paper_index, job_id, known=None):
    """Ask which sentence of each cited paper backs the claim. {ref_index: quote}.

    One focused call per citation, not one call for all of them. The batched
    version was tried first and returned ``{"citations": []}`` -- 17 characters
    -- for a report with 16 citations: given a 12k-character report and a schema
    whose array may legally be empty, the model took the empty-array exit. A
    per-citation prompt carries one claim and one abstract, so there is no such
    exit and nothing to lose track of.

    Only the quote is requested. Author, title, journal and PMID are already
    known from retrieval, and letting the model restate them is how citations
    drift away from the papers they name.

    A failure here is not fatal: references still render without quotes, which
    verify_report_v2 reports honestly as unverifiable rather than as passed.
    """
    cited = sorted({int(n) for n in re.findall(r'\[(\d+)\]', report)}
                   & set(paper_index.keys()))
    # A citation already resolved against its paper does not change when the
    # report is rewritten, and re-asking costs one LLM call per reference per
    # verification round -- ~60s of a 412s verification loop at 42 references.
    if known:
        cited = [i for i in cited if i not in known]
    if not cited:
        return {}

    ref_match = re.search(r'^\s*(?:#{1,6}\s*)?\**\s*references\s*\**\s*:?\s*$',
                          report, re.MULTILINE | re.IGNORECASE)
    body = report[:ref_match.start()] if ref_match else report

    def _one(idx):
        paper = paper_index[idx] or {}
        claims = _claim_sentences_for(body, idx)
        if not claims:
            return idx, ""
        claim = "\n".join("- %s" % c for c in claims)
        # Search the full text where we have it, not just the abstract. An
        # abstract states conclusions; the sentence that actually supports a
        # specific mechanistic claim usually lives in Results. Restricting the
        # search to abstracts was discarding citations to papers that genuinely
        # do support the claim, one paragraph further down.
        source = _quote_source_text(paper)
        if not source:
            return idx, ""
        prompt = (
            'A report cites the paper below for the following claim(s):\n\n'
            '%s\n\n'
            'PAPER: "%s"\nTEXT: %s\n\n'
            'Quote the single sentence from the paper text that best supports '
            'ANY ONE of those claims -- they are alternatives, so you need only '
            'find support for one. When a sentence from the Results or '
            'Discussion supports a claim as well as one from the abstract, '
            'prefer it: it is the evidence itself rather than the summary. '
            'Copy it verbatim: do not paraphrase, shorten, '
            'or write a sentence of your own. If no sentence in the text '
            'supports any of them, set supports=false and cited_text to an empty '
            'string. Answering "no support" is correct and useful; inventing a '
            'quote is not.' % (claim, paper.get("title", ""), source))
        try:
            result = llm.complete_json(
                messages=[
                    {"role": "system", "content": "You extract verbatim "
                                                  "supporting quotations from papers."},
                    {"role": "user", "content": prompt},
                ],
                schema_name="cited_quote",
                schema=CITED_QUOTE_SCHEMA,
                fallback_parser=lambda text: {"cited_text": "", "supports": False},
                max_tokens=800,
                temperature=0.0,
                timeout=SHORT_CALL_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"[{job_id}] Quote lookup failed for [{idx}]: {e}")
            return idx, ""
        if not result.get("supports"):
            return idx, ""
        # Hold the model to the paper's own words before the quote ever reaches
        # the report or the verifier.
        return idx, _snap_quote_to_source(
            (result.get("cited_text") or "").strip(), source)

    # One call per citation, so this scales with citation count; at 20 citations
    # a pool of 4 costs five serial rounds for work that is fully independent.
    quotes = {}
    workers = int(os.getenv("AI_QUOTE_WORKERS", str(max(AI_VERIFICATION_WORKERS, 8))))
    # Bounded as a whole, not just per call. One hung quote lookup made a single
    # check_my_citations take 83.2 s against a median of 1.3 s over 70 calls --
    # 14% of a ten-minute run spent waiting on one citation. Whatever has come
    # back by the deadline is returned; a partial answer is strictly better than
    # a late one, because the gate re-checks anything missing.
    #
    # The deadline is a TIMEOUT on the wait, not a check between results. Two
    # earlier versions of this failed the same way: four fast lookups finished
    # before the deadline could expire, so nothing tripped the check, and
    # as_completed then blocked on the fifth for its full duration. Nor is this
    # a `with` block -- its __exit__ joins every running thread, which undid the
    # timeout just as completely.
    budget = float(os.getenv("AI_QUOTE_DEADLINE", "45"))
    executor = ThreadPoolExecutor(max_workers=min(workers, max(1, len(cited))))
    try:
        futures = [executor.submit(_one, idx) for idx in cited]
        try:
            for future in as_completed(futures, timeout=budget):
                idx, text = future.result()
                if text:
                    quotes[idx] = text
        except FuturesTimeout:
            logger.warning("[%s] quote collection stopped at its %.0fs deadline "
                           "with %d of %d resolved", job_id, budget,
                           len(quotes), len(cited))
    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:                      # cancel_futures is 3.9+
            executor.shutdown(wait=False)
    return quotes


def _parse_json_verdict(text):
    """Parse JSON verdict from verification sub-agent, with fallback for malformed output."""
    # Try direct JSON parse
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        result = json.loads(text)
        return {
            "text_match": bool(result.get("text_match", False)),
            "supports_claim": bool(result.get("supports_claim", False)),
            "reasoning": str(result.get("reasoning", "")),
            "actual_text": str(result.get("actual_text", "")),
            "suggested_fix": str(result.get("suggested_fix", "")),
        }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: try to find JSON within the text
    json_pattern = re.search(r'\{[^{}]*"text_match"[^{}]*\}', text, re.DOTALL)
    if json_pattern:
        try:
            result = json.loads(json_pattern.group())
            return {
                "text_match": bool(result.get("text_match", False)),
                "supports_claim": bool(result.get("supports_claim", False)),
                "reasoning": str(result.get("reasoning", "")),
                "actual_text": str(result.get("actual_text", "")),
                "suggested_fix": str(result.get("suggested_fix", "")),
            }
        except (json.JSONDecodeError, ValueError):
            pass

    # Final fallback: assume verification failed
    logger.warning(f"Could not parse verification verdict: {text[:200]}")
    return {
        "text_match": False,
        "supports_claim": False,
        "reasoning": "Could not parse verification result",
        "actual_text": "",
        "suggested_fix": "",
    }


# =========================================================================
# Phase 3 helpers: local batch indexing
# =========================================================================



_CITATION_GROUP_RE = re.compile(r'\[(\d+(?:\s*,\s*\d+)*)\]')




# =========================================================================
# Phase 2 helpers: Agentic Literature Discovery
# =========================================================================

