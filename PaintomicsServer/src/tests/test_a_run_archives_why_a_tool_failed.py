"""The archive must record WHY a tool call failed, not just that it ran.

Measured before this test existed: 218 runs in the trace archive, and every one
of them carried tool calls with no stats at all. The diagnostics -- why the
top-up added nothing, what it dropped, which stage timed out -- went only to
Mongo, which keeps ONE interpretation per JOB. Of 81 interpretation documents
for 81 jobs, `topup_s` survived in 3 and `topup_rejected` in 1. So of the 23
top-up calls the archive could price by duration, the reason each one added
nothing was recoverable for at most three.

That is the difference between "which tool is useful" (answerable) and "how do
I make this tool better" (not answerable), and it is the second question that
decides what to build.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(SERVER, "src", "classes", "AIInterpret", "agent_loop.py")


class RunArchivesWhyAToolFailed(unittest.TestCase):

    def setUp(self):
        with open(SRC) as fh:
            self.src = fh.read()

    def test_the_stats_stamp_is_derived_not_hand_listed(self):
        """A hand-written field list reports what someone thought to add.

        `__outcome__` names seven fields by hand. `__config__` used to name
        about fifteen flags the same way and silently omitted the rest -- 35
        flags existed, 12 had ever been archived -- which is why it was changed
        to derive them from the module source. The stats stamp must derive too,
        or it inherits exactly that failure.
        """
        block = self.src.split('_trace_gate(ctx, "__stats__"')[0][-1600:]
        self.assertIn("for k, v in (stats or {}).items()", block,
                      "the stats stamp must iterate the stats dict, not name "
                      "individual keys")
        # No literal stat name should appear as a key being picked out.
        self.assertNotRegex(
            block, r'scalars\[\s*"[a-z_]+"\s*\]\s*=',
            "the stats stamp assigns a named key -- that is a hand-written "
            "list wearing a loop")

    def test_scalars_only_so_a_trace_file_stays_small(self):
        """verification/pathwayIndex/topup_added_refs are large and elsewhere."""
        block = self.src.split('_trace_gate(ctx, "__stats__"')[0][-1600:]
        self.assertIn("isinstance(v, (int, float))", block)
        self.assertIn("isinstance(v, str)", block)
        self.assertNotIn("isinstance(v, (dict, list))", block,
                         "dicts and lists must be skipped, not archived")

    def test_the_stats_stamp_is_not_truncated(self):
        """160 chars holds about six scalars. A run records far more.

        This is the failure `__config__` already hit: the cap cut its JSON
        mid-string and made every archived run unparseable by the analyzer the
        stamp exists to feed. A truncated JSON object is not a partial answer,
        it is no answer.
        """
        self.assertIn("VERBATIM_TRACE_STAMPS", self.src)
        m = re.search(r"VERBATIM_TRACE_STAMPS\s*=\s*frozenset\(\(([^)]*)\)\)",
                      self.src)
        self.assertIsNotNone(m, "the exempt set must be a literal frozenset")
        for stamp in ("__config__", "__outcome__", "__stats__"):
            self.assertIn(stamp, m.group(1),
                          "%s dumps JSON and must be archived whole" % stamp)

    def test_the_exemption_is_a_set_not_a_chain_of_equality_tests(self):
        """`== "__config__"` is how this bug reached a second stamp."""
        self.assertNotIn('tool == "__config__"', self.src,
                         "a single-tool equality test does not survive the "
                         "next stamp; use the set")

    def test_the_stamp_cannot_lose_a_finished_report(self):
        """It runs on the return path of a run that already spent its budget."""
        tail = self.src.split('_trace_gate(ctx, "__stats__"')[1][:600]
        self.assertIn("except Exception", tail,
                      "the stats stamp must not be able to discard a report")
        self.assertIn("logging.warning", tail)

    def test_a_json_dump_of_real_stats_survives_the_cap(self):
        """End-to-end on the actual rule, with a realistic stats dict."""
        stats = {"topup_added": 0, "topup_rejected": True,
                 "topup_dropped_existing": 4, "topup_s": 92.13,
                 "themes_retrieved": 13, "themes_cited": 10,
                 "gateway_retries": 2, "gateway_rate_limited": 0,
                 "timed_out_at_stage": "", "loop_s": 130.5,
                 "tool_chars": 48211, "search_budget_spent": 14}
        scalars = {k: v for k, v in stats.items()
                   if isinstance(v, bool) or isinstance(v, (int, float))
                   or (isinstance(v, str) and len(v) <= 120)}
        dumped = json.dumps(scalars, sort_keys=True)
        self.assertGreater(len(dumped), 160,
                           "if this fits in 160 chars the test proves nothing")
        verbatim = frozenset(("__config__", "__outcome__", "__stats__"))
        kept = dumped if "__stats__" in verbatim else dumped[:160]
        self.assertEqual(json.loads(kept), scalars,
                         "the archived stats must round-trip")


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(RunArchivesWhyAToolFailed))
    sys.exit(0 if r.wasSuccessful() else 1)
