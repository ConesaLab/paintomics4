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
