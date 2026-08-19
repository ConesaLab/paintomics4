#!/usr/bin/env python3
"""The top-up must be able to read what a paper found, not just its setup.

Three writers add citations in this pipeline. The delegates get a `_quote_shelf`
of real passages. The Lead gets real quotes through `check_my_citations` and
`_quote_evidence_lines`. The top-up got `abstract[:220]` -- and it is the stage
whose citations die: over 23 archived runs it adds 11-14 citations for ~101 s,
about 8 fail verification and are pulled back, ~6 survive. Precision ~43%.

220 characters is not "a short abstract", it is the first 15% of one -- measured
over 899 stored abstracts the median is 1 428 characters. What 220 buys is the
background sentence, cut off at "In this study". A citation that is topically
plausible and factually unsupported is the expected output of that prompt.

    python -m src.tests.test_topup_sees_the_result
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []

# A structured abstract of the shape PubMed actually returns: the finding a
# citation would rest on sits well past character 220.
ABSTRACT = (
    "Cutaneous human papillomavirus infection has been implicated as a cofactor "
    "in squamous cell carcinoma, however its activity in vivo is poorly "
    "characterised and the responsible effectors are unknown. In this study we "
    "infected mice and profiled the transcriptional response across four "
    "timepoints. "
    "RESULTS: Cathelicidin expression rose 4.2-fold by 12 h and remained "
    "elevated, and Ccr2-positive monocytes accumulated at the lesion margin.")


def _offer(chars):
    """The listing line the top-up is actually shown."""
    return "[7] A title — %s" % ABSTRACT[:chars]


def test_the_default_window_hides_the_finding():
    """Pins the defect this constant exists to make adjustable."""
    shown = _offer(220)
    assert "RESULTS" not in shown, "fixture no longer reproduces the defect"
    assert "4.2-fold" not in shown, (
        "the finding a citation would rest on must be absent at the default")
    assert "In this study" in shown, shown


def test_a_wider_window_reaches_the_result():
    shown = _offer(1000)
    assert "RESULTS" in shown and "4.2-fold" in shown, (
        "widening the window still does not reach the finding")


def test_the_constants_exist_and_default_to_the_measured_behaviour():
    """Every round measured so far ran 220/30; the defaults must not move under
    them, or past rounds stop being comparable."""
    assert L.TOPUP_ABSTRACT_CHARS == 220, L.TOPUP_ABSTRACT_CHARS
    assert L.TOPUP_OFFER_PAPERS == 30, L.TOPUP_OFFER_PAPERS


def test_the_listing_uses_both_constants():
    """Pins the CALL SITE. A constant that nothing reads is a setting in name
    only, and this project has shipped one of those before."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    # Anchor on the TOP-UP's listing, not the first one in the file. The paper
    # screen builds a listing too -- and tellingly gets abstract[:600], nearly
    # three times what the top-up got, for the far easier judgement of whether a
    # paper is on topic at all.
    end = src.index('stats["topup_evidence_chars"]')
    block = src[src.rindex("listing = ", 0, end):end]
    assert "TOPUP_ABSTRACT_CHARS" in block, "the abstract window is still hardcoded"
    assert "TOPUP_OFFER_PAPERS" in block, "the paper count is still hardcoded"
    assert "[:220]" not in block, "a literal 220 survives in the listing"


def test_the_offer_size_is_recorded():
    """The change is only judgeable if the run says how much evidence it gave."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    assert 'stats["topup_evidence_chars"]' in src


def test_the_count_is_not_cut_at_the_same_time():
    """Precision is the measured problem, not volume. Halving the offer while
    widening the window would change two things at once and could easily net
    FEWER surviving citations."""
    assert L.TOPUP_OFFER_PAPERS == 30, (
        "the candidate count moved in the same change as the evidence window")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_default_window_hides_the_finding,
              test_a_wider_window_reaches_the_result,
              test_the_constants_exist_and_default_to_the_measured_behaviour,
              test_the_listing_uses_both_constants,
              test_the_offer_size_is_recorded,
              test_the_count_is_not_cut_at_the_same_time):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
