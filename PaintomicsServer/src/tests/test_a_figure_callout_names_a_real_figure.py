#!/usr/bin/env python3
"""A report may only point at figures the run actually produced.

Why this exists
---------------
`make_figure` returns a callout the agent pastes: `![Fig. 2](figure:fig2-x)`.
The client turns that into an image. Two ways it can lie to a reader, and the
difference between them decides the response:

  * **An id that does not exist** renders as a broken image, and in the
    markdown it is indistinguishable from a figure that was made. There is no
    version of that which is acceptable, so `submit_report` REJECTS it — no
    nudge, no second chance.
  * **An id whose figure failed its standards checks** is a real figure that
    should not be presented as evidence without saying so. That is a judgement
    the agent can defend, so it gets the one shared nudge and is then accepted.

Both paths are cheap to get wrong precisely because nothing raises: an
unresolvable callout costs the pipeline nothing and costs the reader the
figure.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_a_figure_callout_names_a_real_figure
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import agent_loop as al  # noqa: E402

REPORT = ("# Synthesis Report\n\n## Key Findings\n" + ("Cholesterol biosynthesis "
          "rises together in the G12V allele across both layers. " * 40))


class _Ctx(object):
    """RunContextWrapper's only relevant surface."""

    def __init__(self, context):
        self.context = context


def _context(figures, attempts=1):
    c = al.LoopContext(job_instance=None, job_id="j", organism_name="mouse",
                       experiment_design="d")
    c.figures = figures
    c.submit_attempts = attempts - 1        # the tool increments on entry
    c.delegated = ["something"]             # silence the delegation nudge
    c.hard_deadline = time.time() + 3600    # nudges are allowed to fire
    return c


def _submit(context, text):
    """Call the tool through the SDK wrapper the loop registers."""
    fn = getattr(al.submit_report, "on_invoke_tool", None)
    if fn is None:                          # plain function in some SDK versions
        return al.submit_report(_Ctx(context), text)
    import asyncio
    import json
    return asyncio.run(fn(_Ctx(context),
                          json.dumps({"report_markdown": text})))


PASSING = [{"id": "fig1-cholesterol", "archetype": "timecourse",
            "conclusion": "c", "qa_passed": True, "qa": [], "rendered": True,
            "bundle": "/tmp/x"}]
FAILING = [{"id": "fig1-cholesterol", "archetype": "timecourse",
            "conclusion": "c", "qa_passed": False,
            "qa": ["FAIL font_size_floor: 4.00 pt"], "rendered": True,
            "bundle": "/tmp/x"}]


class UnknownIdTest(unittest.TestCase):

    def test_an_invented_id_is_rejected_outright(self):
        out = _submit(_context(PASSING),
                      REPORT + "\n\n![Fig. 1](figure:fig9-invented)\n")
        self.assertIn("REJECTED", out)
        self.assertIn("fig9-invented", out)
        self.assertIn("fig1-cholesterol", out, "say which ids DO exist")

    def test_a_run_with_no_figures_says_so(self):
        out = _submit(_context([]), REPORT + "\n\n![Fig. 1](figure:fig1-x)\n")
        self.assertIn("REJECTED", out)
        self.assertIn("this run made none", out)

    def test_a_real_id_passes_the_gate(self):
        out = _submit(_context(PASSING),
                      REPORT + "\n\n![Fig. 1](figure:fig1-cholesterol)\n")
        self.assertNotIn("REJECTED", out)

    def test_a_report_with_no_callouts_is_untouched(self):
        out = _submit(_context(PASSING), REPORT)
        self.assertNotIn("REJECTED", out)


class UncitedFiguresTest(unittest.TestCase):
    """Figures drawn and never cited are figures the reader never gets.

    Measured on the first live run with figures: the tool offered 26 callouts
    and the submitted report contained none, so four rendered, QA-passing
    panels reached nobody -- the same outcome as not having the tool at all.
    """

    def test_a_run_that_cites_none_of_its_figures_is_nudged_once(self):
        context = _context(PASSING)
        first = _submit(context, REPORT)                 # no callouts at all
        self.assertIn("NOT SUBMITTED YET", first)
        self.assertIn("cites none of them", first)
        self.assertIn("fig1-cholesterol", first, "name the callouts to paste")
        second = _submit(context, REPORT)                # asked once, then accepted
        self.assertNotIn("NOT SUBMITTED YET", second)

    def test_citing_one_of_two_is_not_nudged(self):
        """The nudge is for NONE cited, not for a judgement about how many."""
        two = PASSING + [{"id": "fig2-other", "archetype": "heatmap",
                          "conclusion": "c2", "qa_passed": True, "qa": [],
                          "rendered": True, "bundle": "/tmp/y"}]
        out = _submit(_context(two),
                      REPORT + "\n\n![Fig. 1](figure:fig1-cholesterol)\n")
        self.assertNotIn("NOT SUBMITTED YET", out)

    def test_a_run_with_no_figures_is_never_nudged_about_them(self):
        out = _submit(_context([]), REPORT)
        self.assertNotIn("NOT SUBMITTED YET", out)


class OneNudgeCarriesEverythingTest(unittest.TestCase):
    """Every first-submit problem in ONE message, or the first hides the rest.

    They used to be separate `submit_attempts == 1` blocks that each returned.
    Measured across three live runs: the citation nudge fired 27-30 times and
    the figures nudge -- checked after it -- fired ZERO, while all three runs
    shipped figures they never cited. A check that cannot fire is not a check.
    """

    def test_citations_and_figures_are_raised_together(self):
        c = _context(PASSING)
        c.flagged_citations = {3, 7}
        out = _submit(c, REPORT + "\n\nSee [3] and [7].\n")
        self.assertIn("NOT SUBMITTED YET", out)
        self.assertIn("2 thing(s) to fix", out)
        self.assertIn("[3]", out)                       # the citation problem
        self.assertIn("cites none of them", out)        # and the figure one
        self.assertNotIn("NOT SUBMITTED YET", _submit(c, REPORT))

    def test_one_problem_still_reads_as_one(self):
        c = _context(PASSING)
        out = _submit(c, REPORT)
        self.assertIn("1 thing(s) to fix", out)


class FailedQaTest(unittest.TestCase):

    def test_citing_a_failed_figure_is_nudged_once_then_accepted(self):
        context = _context(FAILING)
        text = REPORT + "\n\n![Fig. 1](figure:fig1-cholesterol)\n"
        first = _submit(context, text)
        self.assertIn("NOT SUBMITTED YET", first)
        self.assertIn("fig1-cholesterol", first)
        second = _submit(context, text)       # same context: attempt 2
        self.assertNotIn("NOT SUBMITTED YET", second)
        self.assertNotIn("REJECTED", second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
