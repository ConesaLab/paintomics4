#!/usr/bin/env python3
"""A tool should answer, not dump -- measured on the biggest dumper.

get_pathway_details is 33.7% of the Lead's per-tool character bill, 56 kB a run
from a median of two calls. Reading it produced two facts:

  * All 80 genes it shows are marked `relevant`, so filtering on that flag saves
    nothing -- and the `*` it renders carries no information either.
  * Those 80 genes carried 540 omic profiles, 6.8 each, and 355 were miRNA-seq,
    because several miRNAs target one gene. Ccr2 showed SEVEN profiles, five of
    them anonymous miRNA series. No identity is carried on a profile, so the
    agent could not tell them apart, cite one, or act on the difference.

Five unnamed 56-character series per gene is noise that is re-sent on every later
Decide turn. Summarising per LAYER -- how many features, the direction split, and
the strongest one's own series -- cut the block 40% (49,715 -> 29,800 chars) and
says more than the dump did. start_end_fc, peak_value and peak_timepoint were
already computed for every profile and used by nothing.

    python -m src.tests.test_profiles_answer_not_dump
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.agent_loop import _profile_summary  # noqa: E402

_PASSED, _FAILED = [], []


def _p(layer, values, pattern="up", fc=1.0):
    return {"omic_name": layer, "values": values, "pattern": pattern,
            "start_end_fc": fc}


def test_a_single_feature_layer_keeps_its_series():
    """One feature is identifiable, so its numbers are worth their space."""
    out = _profile_summary([_p("Gene expression", "1@0h, 2@24h", "monotonic-up")])
    assert out == "Gene expression: 1@0h, 2@24h (monotonic-up)", out


def test_a_multi_feature_layer_is_summarised():
    out = _profile_summary([_p("miRNA-seq", "1@0h", fc=1.0),
                            _p("miRNA-seq", "2@0h", fc=2.0),
                            _p("miRNA-seq", "3@0h", fc=-0.5)])
    assert "miRNA-seq: 3 features, 2 up / 1 down" in out, out


def test_the_strongest_feature_is_the_one_kept():
    """An interpretation reaches for the strongest signal, so that is the series
    worth carrying -- chosen by magnitude, not by sign."""
    out = _profile_summary([_p("miRNA-seq", "weak@0h", fc=0.4),
                            _p("miRNA-seq", "strong@0h", fc=-3.9)])
    assert "strong@0h" in out and "weak@0h" not in out, out
    assert "-3.90 start->end" in out, out


def test_direction_is_taken_from_the_computed_fold_change():
    out = _profile_summary([_p("Proteomics", "a", fc=-1.0),
                            _p("Proteomics", "b", fc=-2.0)])
    assert "0 up / 2 down" in out, out


def test_a_non_numeric_fold_change_does_not_crash():
    """Derived fields go missing; a summary must degrade, not raise."""
    out = _profile_summary([{"omic_name": "DNase-seq", "values": "x", "start_end_fc": None},
                            {"omic_name": "DNase-seq", "values": "y", "start_end_fc": "n/a"}])
    assert "DNase-seq: 2 features" in out, out


def test_every_layer_survives():
    """Summarising must not silently drop a layer -- relating layers is the job."""
    out = _profile_summary([_p("Gene expression", "g"), _p("miRNA-seq", "m1"),
                            _p("miRNA-seq", "m2"), _p("Proteomics", "p")])
    for layer in ("Gene expression", "miRNA-seq", "Proteomics"):
        assert layer in out, "%s vanished: %s" % (layer, out)


def test_layer_order_is_stable():
    """The agent reads these in order; reshuffling between calls invites it to
    treat the same gene as two different pictures."""
    profiles = [_p("Gene expression", "g"), _p("miRNA-seq", "m"), _p("DNase-seq", "d")]
    first = _profile_summary(profiles)
    assert first.index("Gene expression") < first.index("miRNA-seq") < first.index("DNase-seq")
    assert _profile_summary(profiles) == first


def test_the_summary_is_smaller_than_the_dump():
    """The point, stated as a test: five anonymous series must cost less than
    five anonymous series."""
    many = [_p("miRNA-seq", "0.1@0h, 0.2@2h, 0.3@6h, 0.4@12h, 0.5@18h, 0.6@24h",
               fc=i) for i in range(1, 6)]
    dump = "; ".join("miRNA-seq: %s (%s)" % (p["values"], p["pattern"]) for p in many)
    assert len(_profile_summary(many)) < len(dump), "the summary is not smaller"


def test_no_profiles_is_empty_not_broken():
    assert _profile_summary([]) == "" and _profile_summary(None) == ""


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_single_feature_layer_keeps_its_series,
              test_a_multi_feature_layer_is_summarised,
              test_the_strongest_feature_is_the_one_kept,
              test_direction_is_taken_from_the_computed_fold_change,
              test_a_non_numeric_fold_change_does_not_crash,
              test_every_layer_survives,
              test_layer_order_is_stable,
              test_the_summary_is_smaller_than_the_dump,
              test_no_profiles_is_empty_not_broken):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
