"""render_references_section must be readable by parse_references_section.

These two functions are inverses, and the whole citation-verification stage
depends on that holding. It did not hold when the model wrote the section
itself: across six measured runs the synthesis produced a parseable References
block exactly once. It omitted the heading, or wrote `**Cited Text:** foo`
without the double quotes the parser's regex requires, or emitted citation
markers with no list at all. Every one of those failures is silent -- the
verification loop breaks on an empty citation list and the run still reports
`done` with `citations_checked: 0`, which reads as "all verified".

So the round trip is asserted directly, along with the adversarial inputs that
broke it in the field.
"""
import os
import sys
import traceback

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(SERVER_ROOT, "src"))
sys.path.insert(0, SERVER_ROOT)

from src.classes.AIInterpret.verification import (
    render_references_section, parse_references_section,
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


PAPERS = {
    1: {"pmid": "12345678", "title": "Ikaros represses Myc in pre-B cells",
        "first_author": "Ma, S.", "journal": "J Immunol", "year": "2010",
        "abstract": "..."},
    2: {"pmid": "87654321", "title": "Polyamine metabolism in lymphocytes",
        "first_author": "Chen, L.", "journal": "Cell Metab", "year": "2018",
        "abstract": "..."},
}


def test_round_trip_recovers_index_and_quote():
    body = ("Ikaros represses c-Myc [1]. Polyamines decline over the course [2].")
    quotes = {1: "Ikaros directly represses Myc transcription in pre-B cells.",
              2: "Spermidine levels fell 3-fold by 24h."}
    out, rendered = render_references_section(body, PAPERS, quotes)
    assert rendered == [1, 2], rendered

    parsed = parse_references_section(out)
    assert len(parsed) == 2, parsed
    by_idx = {p["ref_index"]: p for p in parsed}
    assert by_idx[1]["cited_text"] == quotes[1], by_idx[1]
    assert by_idx[2]["cited_text"] == quotes[2], by_idx[2]
    # claim_sentence is what verification actually checks the quote against.
    assert "[1]" in by_idx[1]["claim_sentence"], by_idx[1]
    assert by_idx[1]["title"].startswith("Ikaros represses Myc"), by_idx[1]


def test_model_written_section_is_replaced_not_appended():
    """The model's own attempt must not survive alongside the canonical one."""
    body = ("Claim citing [1].\n\n"
            "## References\n"
            "[1] some mangled entry the model invented\n"
            "**Cited Text:** no quotes around this so the parser skips it\n")
    out, rendered = render_references_section(body, PAPERS, {1: "the real quote"})
    assert out.lower().count("references") == 1, out
    assert "mangled entry" not in out, out
    parsed = parse_references_section(out)
    assert len(parsed) == 1 and parsed[0]["cited_text"] == "the real quote", parsed


def test_markers_without_a_retrieved_paper_are_dropped():
    """A citation to a paper we never retrieved cannot be verified.

    Rendering it anyway would manufacture the appearance of support.
    """
    body = "Supported claim [1]. Claim citing a paper we never fetched [99]."
    out, rendered = render_references_section(body, PAPERS, {1: "q"})
    assert rendered == [1], rendered
    assert "[99]" not in out.split("### References")[1], out


def test_quote_containing_double_quotes_does_not_truncate():
    """The parser reads the quote as a "..."-delimited field."""
    body = "Claim [1]."
    nasty = 'The authors call this the "Warburg reversal" effect in B cells.'
    out, _ = render_references_section(body, PAPERS, {1: nasty})
    parsed = parse_references_section(out)
    assert len(parsed) == 1, parsed
    got = parsed[0]["cited_text"]
    assert "Warburg reversal" in got, got
    assert "effect in B cells" in got, "quote was truncated at the inner quote: %r" % got


def test_multiline_quote_is_flattened():
    body = "Claim [1]."
    out, _ = render_references_section(body, PAPERS, {1: "line one\n   line two"})
    parsed = parse_references_section(out)
    assert parsed[0]["cited_text"] == "line one line two", parsed


def test_missing_quote_still_renders_a_parseable_entry():
    """No quote is honest; a missing entry would hide the citation entirely."""
    body = "Claim [1]."
    out, rendered = render_references_section(body, PAPERS, {})
    assert rendered == [1], rendered
    assert "PMID: 12345678" in out, out
    parsed = parse_references_section(out)
    assert len(parsed) == 1 and parsed[0]["cited_text"] == "", parsed


def test_string_keyed_quotes_are_accepted():
    """JSON round-trips can hand back string keys."""
    body = "Claim [1]."
    out, _ = render_references_section(body, PAPERS, {"1": "string keyed"})
    assert parse_references_section(out)[0]["cited_text"] == "string keyed"


def test_no_citations_leaves_body_alone():
    body = "A report that cites nothing at all."
    out, rendered = render_references_section(body, PAPERS, {})
    assert rendered == [], rendered
    assert "References" not in out, out


def test_empty_paper_index_is_a_no_op():
    body = "Claim [1]."
    out, rendered = render_references_section(body, {}, {1: "q"})
    assert out == body and rendered == [], (out, rendered)


def main():
    for t in (test_round_trip_recovers_index_and_quote,
              test_model_written_section_is_replaced_not_appended,
              test_markers_without_a_retrieved_paper_are_dropped,
              test_quote_containing_double_quotes_does_not_truncate,
              test_multiline_quote_is_flattened,
              test_missing_quote_still_renders_a_parseable_entry,
              test_string_keyed_quotes_are_accepted,
              test_no_citations_leaves_body_alone,
              test_empty_paper_index_is_a_no_op):
        _check(t.__name__, t)

    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
