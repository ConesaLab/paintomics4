#!/usr/bin/env python3
"""Admin routes must check for an admin, and read-only jobs must stay read-only.

Why this exists
---------------
Two authorisation guards had no test at all. Found by mutation: deleting either
one leaves the whole suite green.

    AdminServlet:  UserSessionManager().isValidAdminUser(...)   -> pass
    PathwayAcquisitionServlet:
        if jobInstance.getReadOnly() and str(jobInstance.getUserID()) != str(userID):
                                                                -> if False:

The first is what stands between an ordinary session and installing organisms,
deleting users, or reading system information. The second is what stops someone
holding a shared read-only link from writing to the owner's job -- visual
options and replicate mapping both persist through it.

Checked statically, the way test_mutating_handlers_check_session already checks
its own family: these handlers take a Flask request and a job loaded from
MongoDB, so instantiating them costs more than it proves, while the property
worth pinning -- that the call is present in every handler that needs it -- reads
straight off the syntax tree. Comments are stripped first so a commented-out
guard does not count as one.

Two admin handlers are deliberately public and named here as exceptions:
adminServletGetMessage is the handler behind the welcome banner, which runs on
every page load for anonymous visitors, and adminServletSendReport is the
"Report error" button in the failure dialog. Both were confirmed to be reached
by normal users before being excluded, rather than assumed harmless.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_admin_and_readonly_guards
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_SERVLETS = os.path.join(os.path.dirname(__file__), "../servlets")

# Public by design; see the module docstring.
PUBLIC_ADMIN_HANDLERS = {"adminServletGetMessage", "adminServletSendReport"}

# Handlers that persist a change to a job someone else may own.
JOB_MUTATING_HANDLERS = {
    "pathwayAcquisitionSaveVisualOptions",
    "pathwayAcquisitionApplyReplicateMapping",
}


def _stripComments(text):
    """So a commented-out check does not read as a real one."""
    try:
        tokens = [tok for tok in tokenize.generate_tokens(io.StringIO(text).readline)
                  if tok.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


def _functionSources(fileName):
    path = os.path.join(_SERVLETS, fileName)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    tree = ast.parse(source)
    return {node.name: ast.get_source_segment(source, node)
            for node in tree.body if isinstance(node, ast.FunctionDef)}


class AdminRouteGuardTest(unittest.TestCase):

    def setUp(self):
        self.handlers = _functionSources("AdminServlet.py")

    def test_every_admin_handler_checks_for_an_admin(self):
        missing = [name for name, src in self.handlers.items()
                   if name.startswith("adminServlet")
                   and name not in PUBLIC_ADMIN_HANDLERS
                   and "isValidAdminUser" not in _stripComments(src)]

        self.assertEqual(sorted(missing), [],
                         "these admin handlers do not check for an admin, so an "
                         "ordinary session reaches them: %s" % sorted(missing))

    def test_the_check_is_not_only_a_comment(self):
        """Stripping comments is what makes the check above mean anything."""
        for name, src in self.handlers.items():
            if name in PUBLIC_ADMIN_HANDLERS or not name.startswith("adminServlet"):
                continue
            with self.subTest(handler=name):
                self.assertIn("isValidAdminUser", _stripComments(src))

    def test_the_public_handlers_are_still_the_only_exceptions(self):
        """If a new handler stops checking, it must be a decision, not a slip."""
        unguarded = {name for name, src in self.handlers.items()
                     if name.startswith("adminServlet")
                     and "isValidAdminUser" not in _stripComments(src)}

        self.assertEqual(unguarded, PUBLIC_ADMIN_HANDLERS,
                         "the set of admin handlers without an admin check "
                         "changed; if that is intended, update "
                         "PUBLIC_ADMIN_HANDLERS and say why")

    def test_the_handlers_are_actually_found(self):
        """Guards the check itself: an empty scan would pass vacuously."""
        adminHandlers = [n for n in self.handlers if n.startswith("adminServlet")]

        self.assertGreaterEqual(len(adminHandlers), 10,
                                "only %d admin handlers parsed; the scan is "
                                "not seeing the file" % len(adminHandlers))


class ReadOnlyJobGuardTest(unittest.TestCase):

    def setUp(self):
        self.handlers = _functionSources("PathwayAcquisitionServlet.py")

    def test_job_mutating_handlers_check_read_only(self):
        missing = []
        for name in JOB_MUTATING_HANDLERS:
            src = self.handlers.get(name)
            if src is None:
                missing.append("%s (handler not found)" % name)
            elif "getReadOnly" not in _stripComments(src):
                missing.append(name)

        self.assertEqual(missing, [],
                         "these handlers persist a change to a job without "
                         "checking whether it is read-only, so someone holding "
                         "a shared link can write to the owner's job: %s"
                         % missing)

    def test_the_check_compares_the_owner(self):
        """Present but not comparing userID would be a guard in name only."""
        for name in JOB_MUTATING_HANDLERS:
            src = _stripComments(self.handlers.get(name, ""))
            with self.subTest(handler=name):
                self.assertIn("getUserID", src,
                              "%s checks getReadOnly but never compares the "
                              "owner, so it refuses everyone or no one" % name)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
