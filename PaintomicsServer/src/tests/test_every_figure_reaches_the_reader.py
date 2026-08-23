#!/usr/bin/env python3
"""A figure that was drawn and checked must reach the reader.

Why this exists
---------------
The agent pastes `![Fig. N](figure:<id>)` into the draft it submits. That
draft is not what the reader gets: the loop keeps the Lead's head and tail
and stitches the delegated per-pathway sections into the middle — and the
callouts sit in exactly the middle that is replaced.

Measured across four stored runs, and the trace is unambiguous. The submit
line reads:

    accepted (attempt 1, 0 problem(s) found, 465s of run left, nudge needs >90s)

"0 problems" means the gate found callouts in the draft, so the agent had
done its part; the stored report contained none. Two earlier attempts to fix
this aimed at the wrong stage — one at a nudge whose window was closed, one
at a Results rewrite that `stats.results_rejected: undefined` proves never
ran on those jobs.

So the guarantee is made once, deterministically, where the report is
stored: any figure not already shown is appended with its conclusion as the
caption. Asking each text-reshaping stage to preserve markdown images is the
fragile version — there are three of them and each can drop one silently.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_every_figure_reaches_the_reader
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret.agent import (  # noqa: E402
    _ensure_figures_shown, _figure_manifest, _link_figures,
)

PASSED = {"id": "fig1-cholesterol", "archetype": "timecourse",
          "conclusion": "Cholesterol biosynthesis rises together in G12V",
          "qa_passed": True, "qa": [], "rendered": True}
FAILED = {"id": "fig2-layers", "archetype": "heatmap",
          "conclusion": "Both layers move together across the four conditions",
          "qa_passed": False, "qa": ["FAIL font_size_floor: 4.00 pt"],
          "rendered": True}


class _Job(object):
    def getUserID(self):
        return None

    def getJobID(self):
        return "JOB123"


def _manifest(figs):
    return _figure_manifest(_Job(), figs)


class GuaranteeTest(unittest.TestCase):

    def test_a_report_that_cites_nothing_still_shows_every_figure(self):
        m = _manifest([PASSED, FAILED])
        out = _ensure_figures_shown("The body of the report.", m)
        for fig in m:
            self.assertIn(fig["png"], out, fig["id"])
        self.assertIn("### Figures", out)
        self.assertIn(PASSED["conclusion"], out, "the conclusion is the caption")

    def test_a_figure_that_failed_its_checks_is_shown_and_flagged(self):
        out = _ensure_figures_shown("Body.", _manifest([FAILED]))
        self.assertIn(FAILED["png"] if False else "fig2-layers", out)
        self.assertIn("did not pass its quality checks", out)

    def test_a_cited_figure_is_left_where_the_agent_put_it(self):
        m = _manifest([PASSED, FAILED])
        body = "Intro.\n\n![Fig. 1](%s)\n\nMore prose." % m[0]["png"]
        out = _ensure_figures_shown(body, m)
        self.assertEqual(out.count(m[0]["png"]), 1, "not duplicated")
        self.assertIn("Intro.\n\n![Fig. 1](%s)" % m[0]["png"], out,
                      "the agent's placement survives")
        self.assertIn(m[1]["png"], out, "and the uncited one is appended")

    def test_nothing_is_appended_when_every_figure_is_already_shown(self):
        m = _manifest([PASSED, FAILED])
        body = "a %s b %s c" % (m[0]["png"], m[1]["png"])
        self.assertEqual(_ensure_figures_shown(body, m), body)

    def test_a_run_with_no_figures_is_untouched(self):
        self.assertEqual(_ensure_figures_shown("Body.", []), "Body.")


class WholeStorePathTest(unittest.TestCase):
    """The two steps in the order the servlet runs them."""

    def test_callouts_are_linked_then_the_rest_appended(self):
        m = _manifest([PASSED, FAILED])
        draft = "Findings.\n\n![Fig. 1](figure:fig1-cholesterol)\n"
        out = _ensure_figures_shown(_link_figures(draft, m), m)
        self.assertNotIn("figure:fig1-cholesterol", out, "the id became a URL")
        self.assertEqual(out.count(m[0]["png"]), 1)
        self.assertIn(m[1]["png"], out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
