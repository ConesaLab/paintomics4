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


# ---------------------------------------------------------------------------
# The wiring, which is the part that actually broke.
#
# Every test above calls sort_references_section itself, through the local
# _pipeline helper -- so all of them passed while not one shipped report was
# sorted. The sorter was wired into pipeline.py (0616e2df); the Agents SDK
# rewrite (8a6a7dbd) replaced that module and did not carry the call across,
# leaving a function whose only remaining caller was this test file. A helper
# that reimplements the production sequence proves nothing about the
# production sequence, so this asserts against the real one.
# ---------------------------------------------------------------------------

def test_the_interpreter_loop_sorts_after_renumbering():
    """Retargeted from agent._run_async, which went with the workflow arm.

    The ordering property is unchanged and still load-bearing: renumbering
    assigns labels by first mention, so sorting before it orders the OLD labels
    and the References print out of step with the body.
    """
    import inspect
    from src.classes.AIInterpret import agent_loop

    source = inspect.getsource(agent_loop)
    assert "renumber_citations(" in source, "phase 6 no longer renumbers at all"
    assert "sort_references_section(" in source, (
        "the interpreter loop never calls sort_references_section, so every "
        "shipped report prints its References in render order while the body "
        "is numbered by first mention")
    assert (source.index("renumber_citations(")
            < source.index("sort_references_section(")), (
        "the sort has to run after the renumbering, or it orders the old labels")


def test_the_agent_loop_sorts_after_renumbering():
    """The full-agent arm (agent_loop.py) ships through the same gate; a
    sequence that lives in two modules can regress in either one."""
    import inspect
    from src.classes.AIInterpret import agent_loop

    source = inspect.getsource(agent_loop._run_loop_async)
    assert "renumber_citations(" in source, (
        "the agent loop's gate no longer renumbers at all")
    assert "sort_references_section(" in source, (
        "the agent loop never calls sort_references_section")
    assert (source.index("renumber_citations(")
            < source.index("sort_references_section(")), (
        "the agent loop's sort has to run after the renumbering")


def test_an_uncited_reference_is_dropped():
    """The list is the reader's measure of how much evidence stands behind the
    report. Measured over the stored reports, 11 of 43 listed entries the body
    never cited -- one listed 21 references for 18 citations, the extra three
    being papers on unrelated cancers."""
    report = ("A claim [1]. Another [2].\n\n### References\n\n"
              "[1] Smith. Nature 2020.\n"
              "[2] Jones. Cell 2021.\n"
              "[9] Chen. Breast cancer review 2022.\n")
    out, mapping = renumber_citations(report)
    refs = out.split("### References", 1)[1]
    assert "Chen" not in refs, "an uncited reference survived: %r" % refs
    assert "Smith" in refs and "Jones" in refs
    assert 9 not in mapping, "the dropped entry is still in the mapping: %s" % mapping


def test_a_dropped_entry_takes_its_continuation_lines():
    report = ("A claim [1].\n\n### References\n\n"
              "[1] Smith. Nature 2020.\n"
              "    **Cited Text:** the sentence that supports it.\n"
              "[9] Chen. Unrelated 2022.\n"
              "    **Cited Text:** a quote nobody cites.\n")
    out, _ = renumber_citations(report)
    refs = out.split("### References", 1)[1]
    assert "a quote nobody cites" not in refs, (
        "the dropped entry left its quote behind: %r" % refs)
    assert "the sentence that supports it" in refs


def test_pruning_closes_the_numbering_gaps():
    report = ("Only this one [7].\n\n### References\n\n"
              "[3] A. 2020.\n[7] B. 2021.\n[9] C. 2022.\n")
    out, _ = renumber_citations(report)
    body, refs = out.split("### References", 1)
    listed = [int(n) for n in re.findall(r"^\s*\[(\d+)\]", refs, re.M)]
    assert listed == [1], "expected a single renumbered entry, got %s" % listed
    assert "[1]" in body and "B." in refs


def test_a_report_with_no_surviving_citations_keeps_its_section():
    """Conservative on purpose: pruning everything would leave an empty heading,
    which reads as a rendering failure rather than an honest empty result."""
    report = "Everything was redacted.\n\n### References\n\n[1] Smith. Nature 2020.\n"
    out, _ = renumber_citations(report)
    assert "Smith" in out, "the section was emptied instead of left alone"


def test_a_cited_entry_is_never_dropped_by_pruning():
    report = ("Claims [1] and [2] and [3].\n\n### References\n\n"
              "[1] A. 2020.\n[2] B. 2021.\n[3] C. 2022.\n")
    out, mapping = renumber_citations(report)
    refs = out.split("### References", 1)[1]
    for name in ("A.", "B.", "C."):
        assert name in refs, "%s was dropped though it is cited" % name
    assert len(mapping) == 3



def main():
    # Collected, not hand-listed: a renamed or removed test used to leave a
    # NameError here and the suite died instead of running.
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith('test_') and callable(o)]
    assert tests, 'no tests collected'
    for name, t in tests:
        _check(name, t)

    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
