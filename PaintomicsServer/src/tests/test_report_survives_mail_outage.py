"""Regression tests for the report handler that died on a mail outage.

Production symptom (2026-08-19), reported by a user submitting the organism
request form:

    Oops..Internal error!
    Exception: AT AdminServlet.py: adminServletSendReport. ERROR MESSAGE:
    SMTP_PASSWORD is not configured. Please set the environment variable.

Two independent defects met there:

  1. paintomics4.ini declared `env-file = /etc/paintomics/paintomics.env`.
     uWSGI has no such option (--env, --envdir and --unenv are the real ones)
     and ignores unknown ini keys silently, so SMTP_PASSWORD was empty in every
     worker. Delivery to systemd's EnvironmentFile= is the fix; this file pins
     the ini so the dead option cannot come back.

  2. adminServletSendReport called sendEmail with no guard, so ANY delivery
     failure -- unset credential, exhausted provider quota, blocked egress --
     became an internal error AND discarded the user's report. Organism
     requests arrive through this handler, so those were being lost outright.

Run:  PYTHONPATH=PaintomicsServer python3 PaintomicsServer/src/tests/test_report_survives_mail_outage.py
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))


def _ensureServerConfig():
    """Make src.conf.serverconf importable on a checkout that has no config.

    serverconf.py is gitignored and installed from the tracked template at
    deploy time, so a clean checkout (CI, a fresh worktree) has none and
    importing any servlet dies at module level. test_release_hygiene already
    pins that the template imports with no environment set, so binding it under
    the real module name gives this test the same names the app would see.
    """
    try:
        import src.conf.serverconf                       # noqa: F401
        return
    except ImportError:
        pass

    template = os.path.join(HERE, "..", "resources", "example_serverconf.py")
    spec = importlib.util.spec_from_file_location("src.conf.serverconf", template)
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.conf.serverconf"] = module
    spec.loader.exec_module(module)


_ensureServerConfig()

import src.servlets.AdminServlet as AdminServlet


class _Cookies(object):
    def get(self, _name):
        return None            # anonymous reporter: the form supplies identity


class _Request(object):
    def __init__(self, form):
        self.cookies = _Cookies()
        self.form = form


class _Response(object):
    """Minimal stand-in recording what the handler decided."""
    def __init__(self):
        self.content = None
        self.status = None

    def setContent(self, content):
        self.content = content

    def setStatus(self, status):
        self.status = status


def _runHandler(mailBehaviour, calls, form=None):
    """Drive the real handler with a stubbed DAO and a stubbed mailer."""
    form = form or {"type": "specie_request",
                    "message": "Please add Fusarium oxysporum",
                    "fromEmail": "requester@example.org",
                    "fromName": "A Researcher"}

    class _StubDAO(object):
        def insert(self, instance):
            calls.append(("insert", instance.report_type, instance.message))
            return "stub-report-id"

        def markDelivered(self, reportID, delivered, deliveryError=""):
            calls.append(("markDelivered", reportID, delivered))
            return True

    def _stubSendEmail(*args, **kwargs):
        calls.append(("sendEmail",))
        mailBehaviour()

    originalDAO, originalMail = AdminServlet.ReportDAO, AdminServlet.sendEmail
    AdminServlet.ReportDAO, AdminServlet.sendEmail = _StubDAO, _stubSendEmail
    try:
        response = _Response()
        AdminServlet.adminServletSendReport(_Request(form), response, "/tmp")
        return response
    finally:
        AdminServlet.ReportDAO, AdminServlet.sendEmail = originalDAO, originalMail


def _fail():
    raise Exception("SMTP_PASSWORD is not configured. Please set the environment variable.")


def _succeed():
    return None


class MailOutageTest(unittest.TestCase):
    def test_unset_credential_no_longer_produces_an_internal_error(self):
        calls = []
        response = _runHandler(_fail, calls)
        # The exact production failure must not reach the reporter as an error.
        self.assertIsNotNone(response.content, "handler produced no response")
        self.assertTrue(response.content.get("success"),
                        "a mail outage still fails the submission: %r" % (response.content,))
        self.assertFalse(response.content.get("delivered"),
                         "delivery must be reported honestly as not delivered")

    def test_the_report_is_stored_before_delivery_is_attempted(self):
        calls = []
        _runHandler(_fail, calls)
        kinds = [c[0] for c in calls]
        self.assertIn("insert", kinds, "the report was never stored")
        self.assertIn("sendEmail", kinds, "delivery was never attempted")
        self.assertLess(kinds.index("insert"), kinds.index("sendEmail"),
                        "the report must be stored BEFORE the fallible send")

    def test_the_stored_report_carries_the_users_words(self):
        calls = []
        _runHandler(_fail, calls)
        inserted = [c for c in calls if c[0] == "insert"][0]
        self.assertEqual(inserted[1], "specie_request")
        self.assertIn("Fusarium oxysporum", inserted[2])

    def test_a_failed_delivery_is_recorded_against_the_report(self):
        calls = []
        _runHandler(_fail, calls)
        marks = [c for c in calls if c[0] == "markDelivered"]
        self.assertTrue(marks, "delivery outcome was never recorded")
        self.assertFalse(marks[0][2])

    def test_the_happy_path_still_reports_delivered(self):
        calls = []
        response = _runHandler(_succeed, calls)
        self.assertTrue(response.content.get("success"))
        self.assertTrue(response.content.get("delivered"),
                        "a successful send must still be reported as delivered")
        marks = [c for c in calls if c[0] == "markDelivered"]
        self.assertTrue(marks and marks[0][2])

    def test_storage_failure_alone_does_not_fail_the_submission(self):
        """Mongo down AND mail down is still not an internal error."""
        class _BrokenDAO(object):
            def insert(self, instance):
                raise Exception("mongo unreachable")

            def markDelivered(self, *a, **k):
                raise Exception("mongo unreachable")

        originalDAO, originalMail = AdminServlet.ReportDAO, AdminServlet.sendEmail
        AdminServlet.ReportDAO = _BrokenDAO
        AdminServlet.sendEmail = lambda *a, **k: _fail()
        try:
            response = _Response()
            AdminServlet.adminServletSendReport(
                _Request({"type": "error", "message": "boom"}), response, "/tmp")
            self.assertTrue(response.content.get("success"))
        finally:
            AdminServlet.ReportDAO, AdminServlet.sendEmail = originalDAO, originalMail


class UwsgiIniTest(unittest.TestCase):
    def test_ini_does_not_use_the_nonexistent_env_file_option(self):
        path = os.path.join(REPO, "paintomics4.ini")
        if not os.path.isfile(path):
            self.skipTest("paintomics4.ini not present in this checkout")
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            self.assertNotEqual(
                key, "env-file",
                "paintomics4.ini:%d sets 'env-file', which uWSGI does not "
                "implement and silently ignores. Secrets must come from the "
                "systemd EnvironmentFile= drop-in instead." % number)


if __name__ == "__main__":
    unittest.main(verbosity=2)
