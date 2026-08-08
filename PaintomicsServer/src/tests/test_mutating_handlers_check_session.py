#!/usr/bin/env python3
"""A handler that writes on the caller's behalf validates the session first.

Why this exists
---------------
`pathwayAcquisitionSaveImage` writes a PNG or SVG into a job's output directory
and its session check is commented out:

    # logging.info("STEP0 - CHECK IF VALID USER....")
    # userID  = request.cookies.get('userID')
    # sessionToken  = request.cookies.get('sessionToken')
    # UserSessionManager().isValidUser(userID, sessionToken)

Its two siblings -- `pathwayAcquisitionSaveVisualOptions` and
`pathwayAcquisitionSaveSharingOptions` -- both perform it. `git log -S` puts the
commenting in the 2021 bulk "update new version" commit rather than a
considered decision.

**What this is and is not.** It is not much of a vulnerability: `isValidUser`
returns True for the anonymous "nologin" case by design, so a request with no
cookies at all is admitted either way, and the endpoint already requires a job
ID that `loadRequestedJob` resolves. What the check actually rejects is a
request carrying a *userID with a wrong or stale token* -- someone half
logged-in, or replaying an old cookie. Restoring it buys consistency with the
handlers either side of it and one more thing that has to be right, not
protection against an attack that was otherwise open.

It is worth doing because the asymmetry is invisible: nothing about
`SaveImage`'s body tells a reader it is the one handler in the family that
skips the check, and the next person to copy a handler as a template may copy
that one.

The test reads source with comments stripped, because a commented-out check
looks exactly like a real one to grep -- which is how this survived.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_mutating_handlers_check_session
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_SERVLETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "servlets")

# Handlers that act on stored state for the caller. Named individually rather
# than pattern-matched, so adding one is a deliberate act.
MUST_VALIDATE = {
    "PathwayAcquisitionServlet.py": [
        "pathwayAcquisitionSaveImage",
        "pathwayAcquisitionSaveVisualOptions",
        "pathwayAcquisitionSaveSharingOptions",
        "pathwayAcquisitionStep1_PART1",
        "pathwayAcquisitionStep2_PART1",
        "pathwayAcquisitionStep3",
        "pathwayAcquisitionRecoverJob",
        "pathwayAcquisitionApplyReplicateMapping",
        "pathwayAcquisitionMetagenes_PART1",
    ],
    "DataManagementServlet.py": [
        "dataManagementDeleteFile",
        "dataManagementDeleteJob",
        "dataManagementUploadFile",
    ],
}


def _stripComments(text):
    """Remove comments so a commented-out check does not read as a real one."""
    try:
        tokens = [tok for tok in tokenize.generate_tokens(io.StringIO(text).readline)
                  if tok.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


def _functionSources(fileName):
    path = os.path.join(_SERVLETS, fileName)
    source = open(path).read()
    tree = ast.parse(source)
    return {node.name: ast.get_source_segment(source, node)
            for node in tree.body if isinstance(node, ast.FunctionDef)}


class MutatingHandlerSessionTest(unittest.TestCase):

    def test_each_named_handler_validates_the_session(self):
        missing = []
        for fileName, handlers in MUST_VALIDATE.items():
            sources = _functionSources(fileName)
            for handler in handlers:
                body = sources.get(handler)
                if body is None:
                    missing.append("%s: %s no longer exists" % (fileName, handler))
                    continue
                live = _stripComments(body)
                if "isValidUser" not in live:
                    commented = "isValidUser" in body
                    missing.append("%s: %s does not validate the session%s"
                                   % (fileName, handler,
                                      " (the check is commented out)" if commented else ""))

        self.assertEqual(missing, [],
                         "handlers that act on stored state without checking "
                         "the session:\n  " + "\n  ".join(missing))

    def test_the_check_is_not_merely_present_as_a_comment(self):
        """The specific way SaveImage's check was absent."""
        sources = _functionSources("PathwayAcquisitionServlet.py")
        body = sources["pathwayAcquisitionSaveImage"]

        self.assertIn("isValidUser", _stripComments(body),
                      "SaveImage's session check is commented out again")


class AnonymousStillAllowedTest(unittest.TestCase):
    """Restoring the check must not break the nologin flow it coexists with."""

    def test_a_fully_anonymous_caller_is_still_admitted(self):
        from src.common.UserSessionManager import UserSessionManager

        # No cookies at all: request.cookies.get returns None for both.
        UserSessionManager().isValidUser(None, None)   # must not raise

    def test_a_user_id_with_no_token_is_refused(self):
        from src.common.UserSessionManager import UserSessionManager

        with self.assertRaises(Exception):
            UserSessionManager().isValidUser("12345", None)

    def test_a_user_id_with_a_wrong_token_is_refused(self):
        """What restoring the check actually buys."""
        from src.common.UserSessionManager import UserSessionManager

        with self.assertRaises(Exception):
            UserSessionManager().isValidUser("12345", "not-the-real-token")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
