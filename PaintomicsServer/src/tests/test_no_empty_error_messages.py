#!/usr/bin/env python3
"""An exception that reaches the user must say something.

Why this exists
---------------
Three servlets decide what to do from an `exampleMode` path segment:

    if exampleMode == False:      ... real upload
    elif exampleMode == "example": ... bundled example
    else:
        raise NotImplementedError

Anything else -- `/dm_fromBEDtoGenes/true`, a typo, an old bookmark -- takes the
`else`. `NotImplementedError()` has an empty `str()`, and `handleException`
formats the reply as "ERROR MESSAGE: " + str(ex), so the user is shown a dialog
whose message is the empty string:

    NotImplementedError: AT Bed2GenesServlet.py: fromBEDtoGenes_STEP1.
    ERROR MESSAGE:

Observed directly against the running server while testing the Regions2Genes
tool. It is a small defect -- the UI always sends "example" or nothing, so it
takes a hand-built URL to reach -- but it is the same failure shape as the
`StopIteration` escaping `MiRNA2GeneJob.validateInput`: an exception whose text
is empty tells the user nothing at all, and "nothing at all" is the one message
that cannot be acted on.

Deliberately out of scope: `common/DAO/DAO.py` raises bare
`NotImplementedError` eight times as abstract-method stubs. That is what the
exception is for, those never reach a user, and giving them messages would be
noise.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_no_empty_error_messages
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files whose exceptions are formatted into a reply by handleException.
USER_FACING = [
    os.path.join("servlets", "Bed2GenesServlet.py"),
    os.path.join("servlets", "MiRNA2GenesServlet.py"),
    os.path.join("servlets", "PathwayAcquisitionServlet.py"),
    os.path.join("servlets", "DataManagementServlet.py"),
    os.path.join("servlets", "MOREServlet.py"),
]


def _bareRaises(relativePath):
    """`raise SomeError` / `raise SomeError()` with nothing to say."""
    path = os.path.join(_SRC_ROOT, relativePath)
    if not os.path.isfile(path):
        return []
    tree = ast.parse(open(path).read())

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        if isinstance(exc, ast.Name):
            # `raise NotImplementedError` -- the class itself, no message.
            found.append("%s:%d  raise %s" % (relativePath, node.lineno, exc.id))
        elif isinstance(exc, ast.Call) and not exc.args and not exc.keywords:
            name = getattr(exc.func, "id", getattr(exc.func, "attr", "?"))
            found.append("%s:%d  raise %s()" % (relativePath, node.lineno, name))
    return found


class NoEmptyErrorMessageTest(unittest.TestCase):

    def test_no_user_facing_exception_is_raised_without_a_message(self):
        offending = []
        for relativePath in USER_FACING:
            offending.extend(_bareRaises(relativePath))

        self.assertEqual(
            offending, [],
            "these raise an exception whose str() is empty, so handleException "
            "shows the user 'ERROR MESSAGE: ' and nothing after it:\n  "
            + "\n  ".join(offending))


class AbstractStubsAreLeftAloneTest(unittest.TestCase):
    """The lint must not push noise into the DAO base class."""

    def test_the_dao_stubs_still_raise_bare_not_implemented(self):
        stubs = _bareRaises(os.path.join("common", "DAO", "DAO.py"))

        self.assertTrue(stubs,
                        "DAO.py's abstract stubs were 'fixed'; they are what "
                        "NotImplementedError is for and never reach a user")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
