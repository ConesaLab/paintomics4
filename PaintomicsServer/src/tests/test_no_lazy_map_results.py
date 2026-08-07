#!/usr/bin/env python3
"""A `map()` result must be materialised before it is stored or validated.

Why this exists
---------------
This codebase began on Python 2, where `map()` returned a list. On Python 3 it
returns a one-shot iterator, and the two failure modes that creates are both
silent:

  * `try: map(float, row) except: ...` converts nothing and raises nothing, so
    the except branch is unreachable and a file of text validates clean. Found
    in `MiRNA2GeneJob.validateFile` on 2026-08-08 -- the numeric check on every
    miRNA upload had never once run, and neither had the "perhaps you are using
    commas instead of dots" message it guards.

  * `omicValue.setValues(map(float, row))` stores the iterator itself. Read
    once it yields the values; read again it yields nothing. It has no `len()`
    and it is not JSON-serialisable, so it cannot reach MongoDB. Found in
    `MiRNA2GeneJob.fromMiRNA2Genes` the same day. Genes merge whenever several
    miRNAs target one gene -- which miRNA target tables are full of -- and the
    second read is where the values disappear.

Neither shows up as an exception; both produce a job that finishes and reports
success with values silently missing. That is the failure mode worth a lint.

What is allowed: a `map()` consumed on the spot, by `list`, `set`, `tuple`,
`sorted`, `sum`, `any`, `all`, `max`, `min`, `dict`, `str.join`, or a `for`.
What is not: assigning it to a name, passing it as an argument, returning it,
or evaluating it as a bare statement.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_no_lazy_map_results
"""
import ast
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_SRC_ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `map` handed straight to one of these is consumed immediately and is fine.
_CONSUMING_CALLS = {
    "list", "set", "tuple", "sorted", "sum", "any", "all", "max", "min",
    "dict", "frozenset", "len", "zip", "enumerate", "next", "filter",
}

_LAZY_BUILTINS = {"map", "filter", "zip"}


def _isLazyCall(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _LAZY_BUILTINS)


class _Visitor(ast.NodeVisitor):
    """Collect lazy-builtin results that outlive the expression producing them."""

    def __init__(self, relativePath):
        self.path = relativePath
        self.findings = []

    def _record(self, node, how):
        self.findings.append("%s:%d  %s() result %s"
                             % (self.path, node.lineno, node.func.id, how))

    def visit_Assign(self, node):
        if _isLazyCall(node.value):
            self._record(node.value, "assigned to a name")
        self.generic_visit(node)

    def visit_Return(self, node):
        if node.value is not None and _isLazyCall(node.value):
            self._record(node.value, "returned")
        self.generic_visit(node)

    def visit_Expr(self, node):
        # A bare `map(...)` statement: converts nothing, raises nothing.
        if _isLazyCall(node.value):
            self._record(node.value, "evaluated and discarded")
        self.generic_visit(node)

    def visit_Call(self, node):
        # map() passed as an argument to something that does not consume it.
        outerName = node.func.id if isinstance(node.func, ast.Name) else None
        isJoin = (isinstance(node.func, ast.Attribute) and node.func.attr == "join")
        if outerName not in _CONSUMING_CALLS and not isJoin:
            for argument in node.args:
                if _isLazyCall(argument):
                    self._record(argument, "passed as an argument unconsumed")
        self.generic_visit(node)


def _scan():
    findings = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        text = str(path)
        if "__pycache__" in text or "/src/src/" in text or "/tests/" in text:
            continue
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        visitor = _Visitor(str(path.relative_to(_SRC_ROOT)))
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return findings


class LazyMapResultTest(unittest.TestCase):

    def test_no_lazy_builtin_result_outlives_its_expression(self):
        findings = _scan()

        self.assertEqual(
            findings, [],
            "a map()/filter()/zip() result is stored or discarded rather than "
            "consumed. On Python 3 these are one-shot iterators: stored, they "
            "empty on second read and cannot be serialised; discarded inside a "
            "try, they validate nothing. Wrap in list(...).\n  "
            + "\n  ".join(findings))


class LazyMapContractTest(unittest.TestCase):
    """The behaviour the lint is protecting, stated directly."""

    def test_a_map_object_empties_on_second_read(self):
        values = map(float, ["1.0", "2.0"])

        self.assertEqual(list(values), [1.0, 2.0])
        self.assertEqual(list(values), [],
                         "if this ever passes, the lint above can go")

    def test_a_bare_map_in_a_try_never_raises(self):
        raised = False
        try:
            map(float, ["definitely not a number"])
        except Exception:
            raised = True

        self.assertFalse(raised,
                         "map() evaluated eagerly; the lint above can go")

    def test_a_list_wrapped_map_does_raise(self):
        """The fix, stated as behaviour."""
        with self.assertRaises(ValueError):
            list(map(float, ["definitely not a number"]))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
