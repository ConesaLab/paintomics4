#!/usr/bin/env python3
"""Tool YIELD: did the surviving quote come from the abstract, or from full text?

Adoption is answered -- all nine tools at 100%, four already removed on evidence.
Cost is answered -- the per-tool character bill. Neither says which tool's output
ENDS UP CITED, which is the question that decides whether a tool earns its place.

This answers it for the most expensive retrieval machinery in the pipeline. A
quote found in the abstract was free: search_literature already fetched it. A
quote found only deeper cost a full-text upgrade -- an NCBI or Europe PMC round
trip, plus read_paper's ~11 kB a run of context. If surviving quotes are
overwhelmingly abstract quotes, that machinery is paid for and unused; if they are
not, it is load-bearing.

    python -m src.tests.test_quote_provenance
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS  # noqa: E402
from src.classes.AIInterpret.verification import quote_provenance  # noqa: E402

_PASSED, _FAILED = [], []

ABSTRACT = "Glycolysis is elevated in treated mice."
RESULTS = "We observed a 3-fold increase in Hk2 protein at 24 hours."


def _paper(abstract=ABSTRACT, results=RESULTS):
    sections = {"abstract": abstract}
    if results:
        sections["results"] = results
    return {"abstract": abstract, "sections": sections}


def test_an_abstract_quote_is_credited_to_the_abstract():
    out = quote_provenance({1: ABSTRACT}, {1: _paper()})
    assert out["quotes_from_abstract"] == 1
    assert out["quotes_from_full_text"] == 0


def test_a_results_quote_is_credited_to_full_text():
    """This is the quote the full-text machinery exists to make possible."""
    out = quote_provenance({1: "a 3-fold increase in Hk2 protein"}, {1: _paper()})
    assert out["quotes_from_full_text"] == 1
    assert out["quotes_from_abstract"] == 0


def test_a_quote_in_neither_is_its_own_bucket():
    """Folding it into full text would flatter the machinery being measured."""
    out = quote_provenance({1: "a sentence nobody wrote"}, {1: _paper()})
    assert out["quotes_unlocatable_here"] == 1
    assert out["quotes_from_full_text"] == 0


def test_a_paper_with_only_an_abstract_cannot_yield_a_full_text_quote():
    out = quote_provenance({1: "a 3-fold increase in Hk2 protein"},
                           {1: _paper(results=None)})
    assert out["quotes_from_full_text"] == 0
    assert out["quotes_unlocatable_here"] == 1


def test_matching_is_not_brittle_about_exact_bytes():
    """Quotes are copied by a model and arrive with drifted whitespace and
    punctuation; an exact-substring test would report every quote unlocatable
    and make the machinery look useless."""
    out = quote_provenance({1: "Glycolysis   is elevated in treated mice"},
                           {1: _paper()})
    assert out["quotes_from_abstract"] == 1, out


def test_an_empty_quote_is_not_counted_at_all():
    """A citation with no quote is redacted before any of this matters."""
    out = quote_provenance({1: "", 2: None}, {1: _paper(), 2: _paper()})
    assert sum(out.values()) == 0


def test_a_missing_paper_does_not_raise():
    out = quote_provenance({99: "anything"}, {})
    assert out["quotes_unlocatable_here"] == 1


def test_empty_inputs_are_safe():
    assert sum(quote_provenance({}, {}).values()) == 0
    assert sum(quote_provenance(None, None).values()) == 0


def test_all_three_buckets_are_archived():
    for key in ("quotes_from_abstract", "quotes_from_full_text",
                "quotes_unlocatable_here"):
        assert key in STAGE_COUNTS, "%s is not archived" % key


def test_both_arms_compute_it_before_renumbering():
    """renumber_citations rewrites every ref_index, and the quotes dict is keyed
    on the OLD ones -- computing this after would score every quote against the
    wrong paper."""
    import inspect
    from src.classes.AIInterpret import agent_loop
    for module in (agent_loop,):
        src = inspect.getsource(module)
        assert "quote_provenance(quotes, ctx.paper_index)" in src, module.__name__
        called = src.index("quote_provenance(quotes, ctx.paper_index)")
        renumbered = src.index("renumber_citations(report)")
        assert called < renumbered, (
            "%s scores provenance after renumbering" % module.__name__)


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_an_abstract_quote_is_credited_to_the_abstract,
              test_a_results_quote_is_credited_to_full_text,
              test_a_quote_in_neither_is_its_own_bucket,
              test_a_paper_with_only_an_abstract_cannot_yield_a_full_text_quote,
              test_matching_is_not_brittle_about_exact_bytes,
              test_an_empty_quote_is_not_counted_at_all,
              test_a_missing_paper_does_not_raise,
              test_empty_inputs_are_safe,
              test_all_three_buckets_are_archived,
              test_both_arms_compute_it_before_renumbering):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
