#!/usr/bin/env python3
"""The server keeps jobs for exactly as long as it tells users it will.

Why this exists
---------------
`pathwayAcquisitionRecoverJob` tells every user whose job has gone:

    "Job <id> not found at database. Please, note that jobs are automatically
     removed after 7 days for guests and 14 days for registered users."

That sentence was wrong in both directions at the same time.

  * The configuration said `MAX_JOB_DAYS = 365` and `MAX_GUEST_DAYS = 90`, so a
    registered user's job survived a year, not a fortnight.
  * Anonymous jobs -- run without signing in, stored with `userID: None` --
    were never examined at all. `cleanDatabases` walks `userCollection` and
    asks for `{"userID": str(user_id)}`, and a job belonging to nobody matches
    no user, so no rule ever reached it. The original author left a
    "TODO: nologin user will not be present in the DB" against precisely this.
    On paintomics.uv.es that was **159 of 218 jobs** -- the majority of the
    server -- retained indefinitely while being told they had seven days.

Every one of the 13 cleanup runs in the production logs reported the same
thing, and it was true: `0 jobs will be removed. 0 users will be removed.`

The sentence is the contract, because it is the only statement of the policy a
user ever sees. So it is what the configuration is checked against here, by
reading the number out of the servlet's own text rather than restating it --
change the message without changing the policy, or the policy without the
message, and this fails.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_retention_matches_the_promise
"""
import io
import os
import re
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

HERE = os.path.dirname(__file__)
SERVLET = os.path.join(HERE, "../servlets/PathwayAcquisitionServlet.py")
CLEANER = os.path.join(HERE, "../AdminTools/scripts/clean_databases.py")

PROMISE = re.compile(
    r"removed after\s+(\d+)\s+days? for guests and\s+(\d+)\s+days? for registered users")


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _stripComments(text):
    """Prose is not behaviour.

    Every assertion below that says "this construct must be gone" has to read
    code only: the comment explaining why it was removed necessarily quotes it,
    and would otherwise keep the test red forever.
    """
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                  if t.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


def _block(source, header, indent=""):
    """The body of the def that starts with `header`, to the next def at `indent`."""
    start = source.index(header)
    rest = source[start + len(header):]
    marker = "\n" + indent + "def "
    end = rest.find(marker)
    return source[start:] if end == -1 else source[start:start + len(header) + end]


def promisedDays():
    """(guest days, registered days) as the interface states them."""
    match = PROMISE.search(_read(SERVLET))
    if match is None:
        raise AssertionError(
            "the retention sentence is no longer in PathwayAcquisitionServlet. "
            "If it moved, point this test at its new home; if it was deleted, "
            "there is no longer any statement of the policy for users to rely "
            "on, which is its own problem.")
    return int(match.group(1)), int(match.group(2))


class PromiseMatchesConfigTest(unittest.TestCase):

    def setUp(self):
        try:
            from src.conf import serverconf
        except Exception as ex:      # pragma: no cover - environment, not behaviour
            self.skipTest("serverconf is not importable here: %s" % ex)
        self.conf = serverconf
        self.guestDays, self.userDays = promisedDays()

    def test_guest_retention_is_what_the_message_says(self):
        self.assertEqual(
            getattr(self.conf, "MAX_GUEST_JOB_DAYS", None), self.guestDays,
            "the interface promises guests %d days; MAX_GUEST_JOB_DAYS says "
            "otherwise" % self.guestDays)

    def test_registered_retention_is_what_the_message_says(self):
        self.assertEqual(
            self.conf.MAX_JOB_DAYS, self.userDays,
            "the interface promises registered users %d days; MAX_JOB_DAYS "
            "says otherwise" % self.userDays)

    def test_a_guest_job_does_not_outlive_a_registered_one(self):
        """Ordering, not just the numbers -- signing in must be worth something."""
        self.assertLessEqual(self.conf.MAX_GUEST_JOB_DAYS, self.conf.MAX_JOB_DAYS)

    def test_the_guest_account_lifetime_is_a_separate_setting(self):
        """MAX_GUEST_DAYS is about accounts, and must not be read as job retention.

        It was the only "guest" number in the configuration, which is how it
        came to be mistaken for the one the message is about.
        """
        self.assertTrue(hasattr(self.conf, "MAX_GUEST_DAYS"))
        self.assertTrue(hasattr(self.conf, "MAX_GUEST_JOB_DAYS"))


class AnonymousJobsAreReachableTest(unittest.TestCase):
    """The half that no number could fix: jobs nothing ever looked at."""

    def setUp(self):
        self.source = _read(CLEANER)

    def test_the_cleaner_selects_jobs_by_anonymous_user_id(self):
        self.assertIn("checkRemoveAnonymousJobs", self.source,
                      "nothing collects jobs that belong to no user, so the "
                      "seven-day promise cannot apply to most of the server")

    def test_anonymous_jobs_are_queried_directly_not_via_the_user_loop(self):
        """A per-user pass structurally cannot reach a job with no user."""
        block = _block(self.source, "def checkRemoveAnonymousJobs")
        self.assertIn("ANONYMOUS_USER_IDS", block)
        self.assertIn("jobInstanceCollection", block)

    def test_the_anonymous_window_is_the_guest_window(self):
        block = _block(self.source, "def checkRemoveAnonymousJobs")
        self.assertIn("MAX_GUEST_JOB_DAYS", block)

    def test_the_result_is_actually_queued_for_removal(self):
        """Collecting them and not deleting them would pass the tests above."""
        self.assertRegex(
            self.source,
            r"jobs_to_remove\[ANONYMOUS_DIR\]\s*=\s*anonymous_to_remove",
            "anonymous jobs are collected but never handed to the removal step")


class DeletingAJobDeletesItsInterpretationTest(unittest.TestCase):
    """A deleted job must not leave its AI report behind.

    Two independent paths delete jobs and both omitted the collection: the
    nightly `removeJobByJobID`, and `JobDAO.remove`, which is what runs when a
    user presses Delete in My Jobs. On production 366 of 437 AI records
    belonged to jobs that no longer existed -- 88KB each of report text, cited
    papers and the user's conversation with the agent, kept after the user
    asked for the job to go.
    """

    def test_the_nightly_cleanup_removes_the_ai_record(self):
        block = _block(_read(CLEANER), "def removeJobByJobID")
        self.assertIn("aiInterpretationCollection", _stripComments(block))

    def test_the_user_facing_delete_removes_the_ai_record(self):
        dao = _read(os.path.join(HERE, "../common/DAO/PathwayAcquisitionJobDAO.py"))
        block = _block(dao, "    def remove(self", indent="    ")
        self.assertIn("aiInterpretationCollection", _stripComments(block))

    def test_the_user_facing_delete_still_checks_ownership_first(self):
        """The cascade must stay behind the deleted_count gate.

        Moving the new deletes above it would let an anonymous caller wipe the
        interpretation of a job they do not own -- the same defect that gate
        was added to close for features and pathways.
        """
        dao = _read(os.path.join(HERE, "../common/DAO/PathwayAcquisitionJobDAO.py"))
        block = _stripComments(_block(dao, "    def remove(self", indent="    "))
        gate = block.index("deleted_count == 0")
        self.assertLess(gate, block.index("aiInterpretationCollection"),
                        "the AI record is deleted before ownership is checked")


class ReminderArrivesBeforeDeletionTest(unittest.TestCase):
    """A warning has to come before the thing it warns about.

    The window selected jobs whose accessDate was between MAX_JOB_DAYS and
    MAX_JOB_DAYS + 7 days old -- all of which are also older than
    MAX_JOB_DAYS, so STEP 4 deleted them in the same run that STEP 8 mailed
    about them. Harmless at 365 days because it never fired; at 14 it would
    have meant every reminder was a notification of a deletion that had just
    happened.
    """

    def setUp(self):
        self.block = _stripComments(
            _block(_read(CLEANER), "def checkRemindJobsForUser"))

    def test_the_window_ends_at_the_deletion_boundary(self):
        self.assertIn("REMINDER_WINDOW_DAYS", self.block)

    def test_the_old_inverted_window_is_gone(self):
        self.assertNotIn("MAX_JOB_DAYS + 7", self.block,
                         "the reminder window still reaches past the deletion "
                         "boundary, so it warns about jobs already deleted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
