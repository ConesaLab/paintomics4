#!/usr/bin/env python3
"""The retention rules, exercised against a real database.

Why this exists
---------------
`test_retention_matches_the_promise` reads the source and checks the policy is
stated consistently. That cannot tell you whether the code deletes the right
jobs, and this code deletes people's work: getting the boundary wrong by a day,
or the userID matching wrong by a type, destroys data with no undo.

So this builds a scratch database, seeds one job at every interesting age for
every kind of owner, runs the real selection functions against it, and asserts
exactly which job ids come back. Nothing is stubbed except the clock, which is
not stubbed either -- ages are seeded relative to today.

The scratch database is created and dropped here; the server's own database is
never opened. Follows the pattern of test_pymongo4_compat and
test_user_identity_security.

Skips cleanly when MongoDB is not reachable.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_retention_deletes_the_right_jobs
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SCRATCH_DB = "PaintomicsRetentionTestDB"


def _stamp(daysAgo):
    """An accessDate as the application writes it: "%Y%m%d%H%M"."""
    day = datetime.date.today() - datetime.timedelta(days=daysAgo)
    return day.strftime("%Y%m%d") + "1200"


class RetentionSelectionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from pymongo import MongoClient
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            cls.client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                                     serverSelectionTimeoutMS=3000)
            cls.client.server_info()
        except Exception as ex:
            raise unittest.SkipTest("MongoDB is not reachable: %s" % ex)

        import src.AdminTools.scripts.clean_databases as cleaner
        cls.cleaner = cleaner
        cls.guestDays = cleaner.MAX_GUEST_JOB_DAYS
        cls.userDays = cleaner.MAX_JOB_DAYS

        cls.client.drop_database(SCRATCH_DB)
        db = cls.client[SCRATCH_DB]

        # One registered user (id 7) and one guest account (id 9).
        db.userCollection.insert_many([
            {"userID": 7, "userName": "registered", "is_guest": False,
             "last_login": datetime.date.today().strftime("%Y%m%d")},
            {"userID": 9, "userName": "guest", "is_guest": True,
             "last_login": datetime.date.today().strftime("%Y%m%d")},
        ])

        # Jobs straddling every boundary that matters. The names say what each
        # one is asserting, so a failure reads as a sentence.
        cls.jobs = [
            # registered user: 14-day window
            ("reg_fresh",        "7",  1),
            ("reg_day13",        "7",  cls.userDays - 1),
            ("reg_exactly14",    "7",  cls.userDays),
            ("reg_day15",        "7",  cls.userDays + 1),
            ("reg_ancient",      "7",  400),
            # guest account: 7-day window
            ("guest_fresh",      "9",  1),
            ("guest_day6",       "9",  cls.guestDays - 1),
            ("guest_exactly7",   "9",  cls.guestDays),
            ("guest_day8",       "9",  cls.guestDays + 1),
            # anonymous: 7-day window, and the reason this change exists
            ("anon_fresh",       None, 1),
            ("anon_day6",        None, cls.guestDays - 1),
            ("anon_exactly7",    None, cls.guestDays),
            ("anon_day8",        None, cls.guestDays + 1),
            ("anon_ancient",     None, 300),
            # the string spelling of None that BSON round-trips have produced
            ("anon_str_day8",   "None", cls.guestDays + 1),
        ]
        db.jobInstanceCollection.insert_many([
            {"jobID": jid, "userID": uid, "accessDate": _stamp(age)}
            for jid, uid, age in cls.jobs
        ])
        # A job whose accessDate cannot be parsed must never be deleted.
        db.jobInstanceCollection.insert_one(
            {"jobID": "malformed_date", "userID": "7", "accessDate": "not-a-date"})
        db.jobInstanceCollection.insert_one(
            {"jobID": "missing_date", "userID": "7"})

        cls.db = db
        cls.connection = {SCRATCH_DB: db}

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "client", None) is not None:
            cls.client.drop_database(SCRATCH_DB)
            cls.client.close()

    def setUp(self):
        # The cleaner reads MONGODB_DATABASE at call time; point it at scratch.
        self._realDb = self.cleaner.MONGODB_DATABASE
        self.cleaner.MONGODB_DATABASE = SCRATCH_DB

    def tearDown(self):
        self.cleaner.MONGODB_DATABASE = self._realDb

    # ---------------------------------------------------------------- guests

    def test_anonymous_jobs_past_the_window_are_selected(self):
        """The whole point: these were previously unreachable."""
        picked = set(self.cleaner.checkRemoveAnonymousJobs(self.client))
        self.assertIn("anon_day8", picked)
        self.assertIn("anon_ancient", picked)

    def test_anonymous_jobs_inside_the_window_are_kept(self):
        picked = set(self.cleaner.checkRemoveAnonymousJobs(self.client))
        self.assertNotIn("anon_fresh", picked)
        self.assertNotIn("anon_day6", picked)

    def test_the_anonymous_boundary_day_is_kept(self):
        """"Removed after 7 days" means day 7 is still yours."""
        picked = set(self.cleaner.checkRemoveAnonymousJobs(self.client))
        self.assertNotIn("anon_exactly7", picked)

    def test_the_string_none_spelling_counts_as_anonymous(self):
        picked = set(self.cleaner.checkRemoveAnonymousJobs(self.client))
        self.assertIn("anon_str_day8", picked)

    def test_anonymous_selection_touches_no_owned_job(self):
        picked = set(self.cleaner.checkRemoveAnonymousJobs(self.client))
        for jid in ("reg_ancient", "guest_day8", "reg_day15"):
            self.assertNotIn(jid, picked,
                             "%s has an owner and must not be swept up by the "
                             "anonymous pass" % jid)

    def test_a_guest_accounts_jobs_use_the_guest_window(self):
        picked = set(self.cleaner.checkRemoveJobsForUser(
            self.client, 9, False, self.guestDays))
        self.assertIn("guest_day8", picked)
        self.assertNotIn("guest_exactly7", picked)
        self.assertNotIn("guest_fresh", picked)

    # ------------------------------------------------------------ registered

    def test_a_registered_users_jobs_use_the_longer_window(self):
        picked = set(self.cleaner.checkRemoveJobsForUser(
            self.client, 7, False, self.userDays))
        self.assertIn("reg_day15", picked)
        self.assertIn("reg_ancient", picked)
        self.assertNotIn("reg_exactly14", picked)
        self.assertNotIn("reg_day13", picked)
        self.assertNotIn("reg_fresh", picked)

    def test_a_registered_job_survives_the_guest_window(self):
        """Signing in has to be worth something: day 8 is safe for a user."""
        picked = set(self.cleaner.checkRemoveJobsForUser(
            self.client, 7, False, self.userDays))
        self.assertNotIn("reg_day13", picked)

    # --------------------------------------------------------- unreadable dates

    def test_an_unreadable_access_date_is_never_deleted(self):
        """"Cannot tell how old this is" must not mean "infinitely old"."""
        picked = set(self.cleaner.checkRemoveJobsForUser(
            self.client, 7, False, self.userDays))
        self.assertNotIn("malformed_date", picked)
        self.assertNotIn("missing_date", picked)

    def test_a_forced_removal_still_takes_undated_jobs(self):
        """When the account itself is going, its jobs go with it regardless."""
        picked = set(self.cleaner.checkRemoveJobsForUser(
            self.client, 7, True, self.userDays))
        self.assertIn("malformed_date", picked)
        self.assertIn("reg_fresh", picked)

    # ------------------------------------------------------------- reminders

    def test_the_reminder_fires_before_deletion_not_after(self):
        """Every reminded job must still be alive after the removal pass."""
        reminded = set(self.cleaner.checkRemindJobsForUser(self.client, 7))
        removed = set(self.cleaner.checkRemoveJobsForUser(
            self.client, 7, False, self.userDays))
        self.assertEqual(set(), reminded & removed,
                         "these jobs are mailed about and deleted in the same "
                         "run: %s" % sorted(reminded & removed))

    def test_the_reminder_covers_the_last_week_of_a_jobs_life(self):
        reminded = set(self.cleaner.checkRemindJobsForUser(self.client, 7))
        self.assertIn("reg_day13", reminded)
        self.assertNotIn("reg_fresh", reminded)

    # -------------------------------------------------------------- cascade

    def test_removing_a_job_removes_its_ai_interpretation(self):
        self.db.jobInstanceCollection.insert_one(
            {"jobID": "cascade_probe", "userID": "7", "accessDate": _stamp(1)})
        self.db.aiInterpretationCollection.insert_one(
            {"jobID": "cascade_probe", "report": "secret", "status": "done"})
        self.db.featuresCollection.insert_one({"jobID": "cascade_probe"})

        self.cleaner.removeJobByJobID(self.client, "7", "cascade_probe")

        self.assertIsNone(
            self.db.aiInterpretationCollection.find_one({"jobID": "cascade_probe"}),
            "the job is gone but its AI interpretation was left behind")
        self.assertIsNone(
            self.db.jobInstanceCollection.find_one({"jobID": "cascade_probe"}))
        self.assertIsNone(
            self.db.featuresCollection.find_one({"jobID": "cascade_probe"}))

    def test_removing_a_job_leaves_other_jobs_alone(self):
        self.db.jobInstanceCollection.insert_one(
            {"jobID": "victim", "userID": "7", "accessDate": _stamp(1)})
        self.db.aiInterpretationCollection.insert_many([
            {"jobID": "victim", "report": "a"},
            {"jobID": "bystander", "report": "b"},
        ])

        self.cleaner.removeJobByJobID(self.client, "7", "victim")

        self.assertIsNotNone(
            self.db.aiInterpretationCollection.find_one({"jobID": "bystander"}),
            "removing one job deleted another job's interpretation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
