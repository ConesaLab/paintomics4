"""Reading order of the rendered References section.

``render_references_section`` emits entries in ascending index order, and
``renumber_citations`` then rewrites every ``[N]`` marker in place so the
numbering runs 1..n in order of first mention. Neither step moves an entry, so
the two compose into a section whose labels are individually correct and
collectively unreadable: a list rendered 2, 9, 10, 15, 22 and renumbered in body
order comes out as [1], [5], [3], [2], [4].

That is what a reader sees -- the bibliography of a numbered citation style
scrambled -- and nothing else in the pipeline notices, because every marker
still resolves to the right paper. Verification passes, the job reports done.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_reference_section_ordering
"""
import os
import re
import sys
import traceback

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(SERVER_ROOT, "src"))
sys.path.insert(0, SERVER_ROOT)

from src.classes.AIInterpret.verification import (
    render_references_section, renumber_citations, sort_references_section,
    parse_references_section,
)

_PASSED, _FAILED = [], []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  " + name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  " + name)


# The five papers from the report that surfaced this, with the sparse global
# ref_index they carried and a body that cites them out of numeric order.
PAPERS = {
    2:  {"first_author": "Gersende Caron", "title": "Cell-Cycle-Dependent Reconfiguration",
         "journal": "Cell reports", "year": 2015, "pmid": "26565917"},
    9:  {"first_author": "Ashleigh King", "title": "Dynein light chain regulates B cells",
         "journal": "PLoS genetics", "year": 2017, "pmid": "28922373"},
    10: {"first_author": "Xiaoling Chen", "title": "Metformin prevents BAFF activation",
         "journal": "International immunopharmacology", "year": 2021, "pmid": "34004440"},
    15: {"first_author": "Hyun-A Kim", "title": "TGF-beta1 and IFN-gamma",
         "journal": "Journal of leukocyte biology", "year": 2008, "pmid": "18334541"},
    22: {"first_author": "Xiaobei Feng", "title": "Reduction of Stat3 activity",
         "journal": "JASN", "year": 2009, "pmid": "19608706"},
}
QUOTES = {i: "a quotation from paper %d long enough to be checked" % i for i in PAPERS}

BODY = (
    "## Findings\n\n"
    "Methylation is remodelled during differentiation [2]. "
    "BAFF is induced by TGF-beta [15]. "
    "Metformin impedes that activation [10]. "
    "Stat3 activity drives injury [22]. "
    "Dynein light chain shapes B cell development [9].\n"
)


def _labels(report):
    """The [N] labels of the reference entries, in the order they are printed."""
    heading = re.search(r'^###\s*References\s*$', report, re.MULTILINE)
    assert heading, "no References section in:\n%s" % report
    return [int(n) for n in
            re.findall(r'^\[(\d+)\]', report[heading.end():], re.MULTILINE)]


def _pipeline(body, papers, quotes):
    """The order the pipeline runs these in, with the sort as the last step."""
    report, _ = render_references_section(body, papers, quotes)
    report, _ = renumber_citations(report)
    return sort_references_section(report)


def test_renumbering_alone_leaves_the_section_scrambled():
    """The bug, stated directly -- guards the fix against being a no-op."""
    report, _ = render_references_section(BODY, PAPERS, QUOTES)
    assert _labels(report) == [2, 9, 10, 15, 22], _labels(report)
    scrambled, _ = renumber_citations(report)
    assert _labels(scrambled) == [1, 5, 3, 2, 4], _labels(scrambled)


def test_final_section_reads_in_order():
    out = _pipeline(BODY, PAPERS, QUOTES)
    assert _labels(out) == [1, 2, 3, 4, 5], _labels(out)


def _entry_headers(report):
    """{label: header line} for the reference entries only, never the body."""
    heading = re.search(r'^###\s*References\s*$', report, re.MULTILINE)
    assert heading, "no References section in:\n%s" % report
    return {int(n): line for n, line in
            re.findall(r'^\[(\d+)\](.*)$', report[heading.end():], re.MULTILINE)}


def test_each_label_still_points_at_its_own_paper():
    """Reordering must move whole entries, never relabel them."""
    out = _pipeline(BODY, PAPERS, QUOTES)
    # Body order was 2, 15, 10, 22, 9 -> new labels 1..5 in that order.
    expected_pmid = {1: "26565917", 2: "18334541", 3: "34004440",
                     4: "19608706", 5: "28922373"}
    headers = _entry_headers(out)
    assert set(headers) == set(expected_pmid), headers
    for idx, pmid in expected_pmid.items():
        assert headers[idx].endswith("PMID: " + pmid), (
            "reference [%d] carries the wrong paper: %s" % (idx, headers[idx]))


def test_cited_text_travels_with_its_entry():
    out = _pipeline(BODY, PAPERS, QUOTES)
    quote_of = {e["ref_index"]: e["cited_text"] for e in parse_references_section(out)}
    assert quote_of[1] == QUOTES[2], quote_of
    assert quote_of[5] == QUOTES[9], quote_of
    assert len(quote_of) == 5, quote_of


def test_a_trailing_redaction_note_stays_last():
    report, _ = render_references_section(BODY, PAPERS, QUOTES)
    report, _ = renumber_citations(report)
    report += "\n\n> **Note:** 2 citation(s) with unverified references were removed."
    out = sort_references_section(report)
    assert out.rstrip().endswith("were removed."), out[-200:]
    assert _labels(out) == [1, 2, 3, 4, 5], _labels(out)
    assert out.count("**Note:**") == 1, out


def test_an_already_ordered_section_is_untouched():
    report, _ = render_references_section(BODY, PAPERS, QUOTES)
    assert sort_references_section(report) == report


def test_report_without_references_is_untouched():
    text = "No citations here at all."
    assert sort_references_section(text) == text


def test_single_entry_is_untouched():
    body = "One claim [7].\n"
    report, _ = render_references_section(body, {7: PAPERS[9]}, {7: QUOTES[9]})
    assert sort_references_section(report) == report


def test_ten_sorts_after_nine_not_before_it():
    """String ordering would put [10] between [1] and [2]."""
    papers = {i: dict(PAPERS[9], pmid=str(1000000 + i)) for i in range(1, 12)}
    quotes = {i: "quotation number %d that is long enough" % i for i in papers}
    # Cite them in reverse so renumbering has to move every entry.
    body = " ".join("Claim %d [%d]." % (i, i) for i in range(11, 0, -1)) + "\n"
    out = _pipeline(body, papers, quotes)
    assert _labels(out) == list(range(1, 12)), _labels(out)


def main():
    for t in (test_renumbering_alone_leaves_the_section_scrambled,
              test_final_section_reads_in_order,
              test_each_label_still_points_at_its_own_paper,
              test_cited_text_travels_with_its_entry,
              test_a_trailing_redaction_note_stays_last,
              test_an_already_ordered_section_is_untouched,
              test_report_without_references_is_untouched,
              test_single_entry_is_untouched,
              test_ten_sorts_after_nine_not_before_it):
        _check(t.__name__, t)

    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
