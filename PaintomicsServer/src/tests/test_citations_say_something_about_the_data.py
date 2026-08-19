#!/usr/bin/env python3
"""A citation must be about the experiment, not merely next to it.

Every citation metric in this project counts markers and asks whether a quote
supports the sentence carrying them. Both arms pass that test with zero
redactions -- and reading the reports shows why: 90 to 95% of citation-bearing
sentences are statements ABOUT A PAPER, printed beside the data.

    "Integrin beta3 acts as a threshold regulator of B cell activation [1],
     reframing beta3 as a threshold regulator of B-cell activation."
    "NOB1 is a ribosome assembly factor that plays a crucial role in the
     maturation of the 40S ribosomal small subunit [9]."

A sentence that restates its own source is trivially supported by it, so the
verification gate cannot see the problem and `redacted` reads 0. The measurement
rewarded the failure it was built to catch, and no count could have found it --
it took reading a report.

    python -m src.tests.test_citations_say_something_about_the_data
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import (citation_grounding,          # noqa: E402
                                         repeated_citation_sentences)

_PASSED, _FAILED = [], []


def test_a_bare_literature_fact_is_not_grounded():
    text = "NOB1 is a ribosome assembly factor for the 40S subunit [9]."
    assert citation_grounding(text) == (1, 0), citation_grounding(text)


def test_a_claim_about_this_experiment_is_grounded():
    text = ("Ccr2 falls monotonically to -7.69 by 24h, consistent with the loss "
            "of inflammatory chemokine responsiveness reported in [2].")
    assert citation_grounding(text) == (1, 1), citation_grounding(text)


def test_a_pathway_id_counts_as_a_claim_about_the_data():
    text = "Rap1 signalling (mmu04015) is driven by accessibility rather than expression [4]."
    assert citation_grounding(text)[1] == 1


def test_a_p_value_counts():
    text = "Ribosome biogenesis factors decline together (global p=4.78e-06) [3]."
    assert citation_grounding(text)[1] == 1


def test_sentences_without_citations_are_not_counted_either_way():
    text = ("Ccnd1 falls to -4.13 by 24h. NOB1 is a ribosome assembly factor [9].")
    total, grounded = citation_grounding(text)
    assert total == 1, "an uncited data sentence was counted as a citation"
    assert grounded == 0


def test_the_reference_list_is_not_scanned():
    """Every entry there names authors and years and would score as grounded."""
    text = ("A claim [1].\n\n## References\n\n[1] Smith et al. 2019. "
            "Integrin beta3 p=0.001 at 24h in mmu04015.\n")
    assert citation_grounding(text) == (1, 0), citation_grounding(text)


def test_a_repeated_sentence_is_counted_once_as_padding():
    line = "PKCbeta is essential for a microenvironment supporting leukemic growth [8]."
    assert repeated_citation_sentences(line + " " + line) == 1
    assert repeated_citation_sentences(line) == 0


def test_the_same_claim_with_a_different_marker_still_counts_as_repeated():
    """Renumbering happens at the gate; padding should not hide behind it."""
    a = "Tropomyosins are master regulators of actin dynamics [6]."
    b = "Tropomyosins are master regulators of actin dynamics [7]."
    assert repeated_citation_sentences(a + " " + b) == 1


def test_it_is_a_floor_not_a_judgement():
    """Deliberately crude: it asks whether the sentence mentions the experiment,
    not whether the inference is sound. Recording that here so nobody later
    mistakes a passing score for a good citation."""
    gamed = "NOB1 is a ribosome assembly factor [9], and Nob1 is in our data at 24h."
    assert citation_grounding(gamed)[1] == 1, (
        "the metric is satisfiable by naming a timepoint -- that is known")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_bare_literature_fact_is_not_grounded,
              test_a_claim_about_this_experiment_is_grounded,
              test_a_pathway_id_counts_as_a_claim_about_the_data,
              test_a_p_value_counts,
              test_sentences_without_citations_are_not_counted_either_way,
              test_the_reference_list_is_not_scanned,
              test_a_repeated_sentence_is_counted_once_as_padding,
              test_the_same_claim_with_a_different_marker_still_counts_as_repeated,
              test_it_is_a_floor_not_a_judgement):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
