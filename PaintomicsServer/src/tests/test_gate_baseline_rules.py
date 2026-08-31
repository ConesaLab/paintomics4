"""The rules that decide whether a failing suite is master's fault or yours.

`run_all.BASELINE` is the only thing standing between "this branch broke a
test" and "this test was already broken", and every hole found in it so far has
been a hole in the *classification*, not in the list: matching on the suite name
alone absorbed a brand-new failure, and counting only `FAIL` lines missed every
error. Each of those shipped green. The rules are cheap to state and cheap to
check, so they are checked here rather than rediscovered the next time a gate
goes green over a suite that stopped running.

Offline, no fixtures, no server:

    cd PaintomicsServer && python -m src.tests.test_gate_baseline_rules
"""
import unittest

from src.tests import run_all


# What unittest really prints when a class fixture raises: one ERROR line that
# names setUpClass rather than a test, and a zero count. The suite executed
# nothing, but it does name one thing -- which is how it passed for "no worse
# than a baseline of 4".
SETUPCLASS_DIED = """\
E
======================================================================
ERROR: setUpClass (__main__.AiPipelineEndToEndTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "test_ai_agent_endtoend.py", line 227, in setUpClass
    cls.gateway = _startGateway()
FileNotFoundError: [Errno 2] No such file or directory: 'stub_gateway.py'

----------------------------------------------------------------------
Ran 0 tests in 0.002s

FAILED (errors=1)
"""

FOUR_REAL_FAILURES = """\
FAIL: test_reference_has_cited_text (__main__.AiPipelineEndToEndTest)
FAIL: test_quote_survives_redaction (__main__.AiPipelineEndToEndTest)
FAIL: test_citation_is_not_dropped (__main__.AiPipelineEndToEndTest)
ERROR: test_report_reaches_the_user (__main__.AiPipelineEndToEndTest)
----------------------------------------------------------------------
Ran 31 tests in 12.418s

FAILED (failures=3, errors=1)
"""

# The server logs through `logging` on its report, mail and hub failure paths,
# and `basicConfig`'s default format puts the level at the start of the line.
SUITE_THAT_LOGS = """\
ERROR:root:Report could not be delivered, storing it instead
ERROR:root:Report could not be delivered, storing it instead
FAIL: test_mail_outage_is_reported (__main__.ReportTest)
----------------------------------------------------------------------
Ran 16 tests in 0.940s

FAILED (failures=1)
"""


# The same accident in a file that holds more than one test class: the other
# class runs to completion, so the count does not even drop. Measured by
# planting a `raise` in one setUpClass of test_pathway_universe_database_filter,
# whose baseline is 1: "Ran 8 tests", one failing name, inherited, exit 0.
ONE_CLASS_OF_TWO_DIED = """\
test_a_kept_pathway_survives (__main__.PathwayUniverseDatabaseFilterTest) ... ok
setUpClass (__main__.RealOrganismPathwayCountsTest) ... ERROR

======================================================================
ERROR: setUpClass (__main__.RealOrganismPathwayCountsTest)
----------------------------------------------------------------------
Traceback (most recent call last):
RuntimeError: the fixture this branch broke

----------------------------------------------------------------------
Ran 8 tests in 0.000s

FAILED (errors=1)
"""


def _result(suite, out, state="FAIL"):
    """A result dict shaped exactly as both runners build one."""
    return {"suite": suite, "state": state,
            "ran": run_all.tests_run(out),
            "fixtures": run_all.BROKEN_FIXTURE.findall(out),
            "failing": run_all.FAILING_TEST.findall(out)}


class FailingTestNamesTest(unittest.TestCase):

    def test_unittest_failures_and_errors_both_count(self):
        self.assertEqual(len(run_all.FAILING_TEST.findall(FOUR_REAL_FAILURES)), 4)

    def test_a_dead_fixture_is_found_by_name(self):
        self.assertEqual(run_all.BROKEN_FIXTURE.findall(SETUPCLASS_DIED),
                         ["setUpClass"])
        self.assertEqual(run_all.BROKEN_FIXTURE.findall(FOUR_REAL_FAILURES), [])

    def test_a_log_record_is_not_a_failing_test(self):
        """`ERROR:root:...` is a log line; only `ERROR: name` is a test."""
        self.assertEqual(run_all.FAILING_TEST.findall(SUITE_THAT_LOGS),
                         ["test_mail_outage_is_reported"])

    def test_the_hand_rolled_convention_still_counts(self):
        out = "PASS  test_a\nFAIL  test_b: expected 3, got 4\n"
        self.assertEqual(run_all.FAILING_TEST.findall(out), ["test_b:"])

    def test_the_word_fail_mid_line_is_not_a_test(self):
        self.assertEqual(run_all.FAILING_TEST.findall("  FAIL: not at line start\n"), [])


class TestsRunCountTest(unittest.TestCase):

    def test_unittest(self):
        self.assertEqual(run_all.tests_run(FOUR_REAL_FAILURES), 31)
        self.assertEqual(run_all.tests_run(SETUPCLASS_DIED), 0)

    def test_hand_rolled(self):
        self.assertEqual(run_all.tests_run("PASS  a\n\nPassed: 3 / 4\n"), 4)

    def test_a_suite_that_never_said(self):
        self.assertIsNone(run_all.tests_run("Traceback (most recent call last):\n"))


class SplitByBaselineTest(unittest.TestCase):
    """The whole point: which side of the line does a failing suite fall on."""

    def setUp(self):
        self._real = run_all.BASELINE
        run_all.BASELINE = {"baselined": "4 failures: the stub gateway cannot "
                                         "satisfy the quote extractor"}

    def tearDown(self):
        run_all.BASELINE = self._real

    def split(self, result):
        inherited, introduced = run_all.split_by_baseline([result])
        return "introduced" if introduced else "inherited"

    def test_no_worse_than_master_is_masters(self):
        self.assertEqual(self.split(_result("baselined", FOUR_REAL_FAILURES)),
                         "inherited")

    def test_one_more_than_master_is_yours(self):
        out = FOUR_REAL_FAILURES + "ERROR: test_five (__main__.T)\n"
        result = _result("baselined", out)
        self.assertEqual(self.split(result), "introduced")
        self.assertEqual(result["grew"], (4, 5))

    def test_a_dead_class_fixture_is_yours_even_though_it_names_one_thing(self):
        """The regression this file exists for.

        `ERROR: setUpClass` is one name against a baseline of four, so the
        count rule alone called it inherited while the suite ran no tests.
        """
        result = _result("baselined", SETUPCLASS_DIED)
        self.assertEqual(result["failing"], ["setUpClass"])
        self.assertEqual(result["ran"], 0)
        self.assertEqual(self.split(result), "introduced")
        self.assertEqual(result["fixture"], ["setUpClass"])

    def test_a_suite_that_ran_nothing_is_yours(self):
        """No fixture error to point at -- it simply executed no test."""
        result = _result("baselined", "Passed: 0 / 0\n")
        self.assertEqual(result["ran"], 0)
        self.assertEqual(self.split(result), "introduced")
        self.assertEqual(result["collapsed"], 4)

    def test_a_dead_fixture_is_yours_even_when_the_count_does_not_move(self):
        """One class of two stops running; the other keeps the number honest.

        This is the shape the `ran == 0` rule cannot see, and it is the shape
        the real suites have: eight tests ran, one name is failing, the
        baseline is one. Only "a fixture died" distinguishes it.
        """
        run_all.BASELINE = {"baselined": "1 failure"}
        result = _result("baselined", ONE_CLASS_OF_TWO_DIED)
        self.assertEqual(result["ran"], 8)
        self.assertEqual(len(result["failing"]), 1)
        self.assertEqual(result["fixtures"], ["setUpClass"])
        self.assertEqual(self.split(result), "introduced")
        self.assertEqual(result["fixture"], ["setUpClass"])

    def test_a_suite_that_died_on_import_is_yours(self):
        result = _result("baselined", "ModuleNotFoundError: no module named x\n")
        self.assertIsNone(result["ran"])
        self.assertEqual(self.split(result), "introduced")

    def test_a_suite_that_did_not_finish_is_yours(self):
        result = _result("baselined", FOUR_REAL_FAILURES, state="TIMEOUT")
        self.assertEqual(self.split(result), "introduced")
        self.assertEqual(result["timedout"], 4)

    def test_a_suite_nobody_baselined_is_yours(self):
        self.assertEqual(self.split(_result("not_baselined", FOUR_REAL_FAILURES)),
                         "introduced")


class BaselineNotesTest(unittest.TestCase):

    def test_a_note_without_a_count_is_refused_before_anything_runs(self):
        real = run_all.BASELINE
        run_all.BASELINE = {"suite": "flaky on macOS"}
        try:
            with self.assertRaises(ValueError):
                run_all.check_baseline()
        finally:
            run_all.BASELINE = real

    def test_every_real_entry_states_its_count(self):
        run_all.check_baseline()


if __name__ == "__main__":
    unittest.main(verbosity=2)
