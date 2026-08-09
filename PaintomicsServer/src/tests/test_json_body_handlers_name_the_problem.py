#!/usr/bin/env python3
"""A request without a JSON body must be told what is missing, not crash.

Why this exists
---------------
Three handlers in PathwayAcquisitionServlet read their input with
`request.get_json()`. Flask returns None from that when the request did not
arrive as application/json, and every one of them then called `.get()` on it:

    visualOptions = request.get_json()
    jobID = visualOptions.get("jobID")     ->  AttributeError on None

Measured against a running server, posting form-encoded data to each:

    /pa_save_visual_options   HTTP 400   AttributeError: ... 'NoneType' object
    /pa_adjust_pvalues        HTTP 400   AttributeError: ... 'NoneType' object

That is the failure `loadRequestedJob` was written to stop -- an error naming
neither the field nor the handler's actual complaint, which the client cannot
render into anything a user can act on. `pathwayAcquisitionApplyReplicateMapping`
already had the fix (`request.get_json() or {}` followed by explicit checks);
the other two did not, 300 lines apart in the same file.

After, the same two requests:

    /pa_save_visual_options   Missing jobID parameter for saving visual options.
    /pa_adjust_pvalues        Missing pValues parameter for adjusting p-values.

pValues is checked explicitly because it is not merely absent-and-caught later:
the loops below it do `pvalues.items()`, so a missing one surfaced as an
AttributeError several frames from the cause.

This is a diagnostics fix. A correct client sends JSON and never sees it; what
it changes is what happens when something is wrong.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_json_body_handlers_name_the_problem
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVLET = os.path.join(os.path.dirname(__file__),
                       "../servlets/PathwayAcquisitionServlet.py")


def _stripComments(text):
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                  if t.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


class JsonBodyHandlersTest(unittest.TestCase):

    def setUp(self):
        with open(SERVLET, "r", encoding="utf-8", errors="replace") as handle:
            self.source = handle.read()
        self.tree = ast.parse(self.source)
        self.handlers = {n.name: _stripComments(ast.get_source_segment(self.source, n))
                         for n in self.tree.body if isinstance(n, ast.FunctionDef)}

    def _jsonHandlers(self):
        """Every handler that reads its input with request.get_json()."""
        return {name: body for name, body in self.handlers.items()
                if "get_json()" in body}

    def test_the_handlers_were_actually_found(self):
        found = self._jsonHandlers()

        self.assertGreaterEqual(len(found), 3,
                                "expected at least three get_json handlers, "
                                "found %d -- if the file was reorganised this "
                                "test may be checking nothing" % len(found))

    def test_every_json_handler_tolerates_a_missing_body(self):
        """None.get() is the bug; `or {}` is how the file already fixes it."""
        unguarded = [name for name, body in self._jsonHandlers().items()
                     if "get_json() or {}" not in body]

        self.assertEqual(unguarded, [],
                         "these call .get() on request.get_json() without a "
                         "fallback, so a request that is not application/json "
                         "fails with AttributeError instead of naming the "
                         "missing field: %s" % unguarded)

    def test_adjust_pvalues_names_the_missing_field(self):
        body = self.handlers["pathwayAcquisitionAdjustPvalues"]

        self.assertIn("Missing pValues", body,
                      "a request with no pValues reaches `pvalues.items()` "
                      "and fails with AttributeError several frames from the "
                      "cause")

    def test_the_check_precedes_the_first_use(self):
        body = self.handlers["pathwayAcquisitionAdjustPvalues"]

        checkAt = body.find("Missing pValues")
        useAt = body.find("pvalues.items()")

        self.assertNotEqual(checkAt, -1, "no check at all")
        self.assertNotEqual(useAt, -1,
                            "pvalues.items() is gone; if the flow changed, "
                            "re-read what this test pins")
        self.assertLess(checkAt, useAt,
                        "the check happens after pvalues is already iterated")

    def test_the_guard_is_real_code_not_a_comment(self):
        for name in ("pathwayAcquisitionSaveVisualOptions",
                     "pathwayAcquisitionAdjustPvalues"):
            with self.subTest(handler=name):
                node = ast.parse(self.handlers[name].lstrip())
                hasFallback = any(
                    isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or)
                    for n in ast.walk(node))
                self.assertTrue(hasFallback,
                                "%s has no `or` fallback in its parsed body, "
                                "so the guard is prose rather than code" % name)

    def test_apply_replicate_mapping_keeps_the_pattern_it_set(self):
        """It is the precedent the other two were brought in line with."""
        body = self.handlers["pathwayAcquisitionApplyReplicateMapping"]

        self.assertIn("get_json() or {}", body)
        self.assertIn("Missing jobID", body)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
