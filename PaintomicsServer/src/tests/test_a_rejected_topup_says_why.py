"""A rejected top-up must record WHICH condition rejected it.

Measured over 13 archived runs: 5 top-ups (38%) were rejected outright,
spending 32-130 s and delivering nothing. That is the only lever in this
pipeline with no citation cost -- a rejected top-up adds zero BY DEFINITION, so
removing it cannot lose a citation, unlike the deadline (21% citation loss) and
the headroom threshold (blocks runs that did not need blocking), both of which
were priced and rejected.

Of those 5, only 2 recorded anything about why, and only because
`topup_dropped_existing` is set independently of the guard. The other 3 failed
on "too short" or "added nothing" and were indistinguishable.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(SERVER, "src", "classes", "AIInterpret", "agent_loop.py")


class RejectedTopupSaysWhy(unittest.TestCase):

    def setUp(self):
        with open(SRC) as fh:
            self.src = fh.read()

    def test_the_reason_is_recorded(self):
        self.assertIn('stats["topup_rejected_why"]', self.src)

    def test_every_guard_condition_has_a_named_reason(self):
        """The guard has exactly three conditions; each needs a distinct label.

        If a condition is added later without a label, a rejection it causes
        reads as one of the others -- which is worse than "unknown", because it
        is wrong rather than absent.
        """
        # Anchored on the REJECT branch, not on the guard. Slicing forward from
        # the guard walks through the accept branch first, which is ~40 lines of
        # comment here, so a fixed window ends before the labels and the test
        # fails on a correct implementation. This repo has hit that exact
        # stale-slice failure in five other suites.
        self.assertIn("if (len(candidate) > 0.6 * len(str(report))", self.src,
                      "the guard's shape changed; update this test")
        tail = self.src.split('stats["topup_rejected"] = True')[1][:2500]
        for label in ("short", "no_gain", "dropped"):
            self.assertIn('"%s"' % label, tail,
                          "no label for the %r condition" % label)

    def test_the_labels_mirror_the_guard_not_a_guess(self):
        """Each label's test must be the NEGATION of the guard's condition."""
        tail = self.src.split('stats["topup_rejected"] = True')[1][:2000]
        self.assertIn("len(candidate) <= 0.6 * len(str(report))", tail,
                      "'short' must negate the guard's length test exactly")
        self.assertIn("added <= len(cited_now)", tail,
                      "'no_gain' must negate the guard's gain test exactly")
        self.assertIn("if dropped:", tail)

    def test_it_never_records_an_empty_reason(self):
        tail = self.src.split('stats["topup_rejected"] = True')[1][:2000]
        self.assertIn('or "unknown"', tail,
                      "an empty reason string is indistinguishable from the "
                      "field being absent, which is the failure this fixes")

    def test_the_ratio_is_kept_because_short_is_a_ratio(self):
        self.assertIn('stats["topup_candidate_ratio"]', self.src)

    def test_the_reason_reaches_the_archive(self):
        """It must be a scalar, or the __stats__ stamp drops it.

        The stamp keeps ints, floats, bools and strings <=120 chars, and
        deliberately skips dicts and lists. A reason recorded as a list would be
        computed and then silently discarded -- exactly the failure round 56
        fixed at the level above.
        """
        tail = self.src.split('stats["topup_rejected_why"]')[1][:200]
        self.assertIn('",".join(', tail,
                      "the reason must be joined into a string, not left a list")


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(RejectedTopupSaysWhy))
    sys.exit(0 if r.wasSuccessful() else 1)
