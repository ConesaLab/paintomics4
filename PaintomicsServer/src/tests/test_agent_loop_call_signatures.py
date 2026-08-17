#!/usr/bin/env python3
"""Every cross-module call in agent_loop.py must match the callee's signature.

Why this exists
---------------
The first live run of the full-agent loop died 66 s in with

    TypeError: render_partition_table() missing 1 required positional
               argument: 'pathway_ctx_by_id'

The module imported fine, the stub end-to-end test passed (its job produced no
clusters, so the call was never reached), and `py_compile` is blind to arity by
construction. The defect only existed at a *call site*, in a branch that needs
a real clustered dataset to enter -- which is the cheapest possible bug and the
most expensive possible way to find it: a wasted arm of a timed benchmark.

So this test reads agent_loop.py as a syntax tree, finds every call to a
function imported from a sibling module (clusters, context_builder,
verification, prompts, shared, tools), and binds the call's arguments against
the real function's signature with `inspect.Signature.bind`. Wrong arity,
misspelled keyword, or a positional that does not exist fails here in
milliseconds, offline, without Mongo, a gateway, or a job.

It deliberately checks the *callee's* live signature rather than a recorded
list: if a helper in clusters.py grows a required parameter, this fails at the
call site that did not follow -- which is the failure mode above, in reverse.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_agent_loop_call_signatures
"""
import ast
import inspect
import os
import sys

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SERVER_ROOT)

from src.classes.AIInterpret import agent_loop

# module alias in agent_loop -> the imported module object
MODULE_ALIASES = {
    "clusters_mod": "src.classes.AIInterpret.clusters",
    "prompts_mod": "src.classes.AIInterpret.prompts",
    "tools_mod": "src.classes.AIInterpret.tools",
}
# bare names imported into agent_loop from sibling modules, checked too
BARE_TARGETS = (
    "build_pathway_context", "build_gene_symbol_whitelist", "get_organism_name",
    "build_cross_omic_matrix", "build_key_regulators_block",
    "render_pathway_table", "triage_pathways",
    "count_body_citations", "normalize_citation_markers",
    "parse_references_section", "redact_unverified_v2",
    "render_references_section", "renumber_citations", "resolve_pmid_mentions",
    "sort_references_section", "verify_report_v2",
    "_collect_cited_quotes", "_parse_json_verdict",
)

_PASSED, _FAILED = [], []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  " + name)
    except Exception as exc:
        _FAILED.append((name, "%s: %s" % (type(exc).__name__, exc)))
        print("FAIL  %s\n      %s: %s" % (name, type(exc).__name__, exc))


def _resolve(node):
    """(callable, label) for a call this test knows how to check, else None."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        alias = func.value.id
        if alias in MODULE_ALIASES:
            module = sys.modules[MODULE_ALIASES[alias]]
            target = getattr(module, func.attr, None)
            if callable(target):
                return target, "%s.%s" % (alias, func.attr)
            raise AssertionError("%s.%s does not exist" % (alias, func.attr))
    if isinstance(func, ast.Name) and func.id in BARE_TARGETS:
        target = getattr(agent_loop, func.id, None)
        if callable(target):
            return target, func.id
        raise AssertionError("%s is not imported in agent_loop" % func.id)
    return None


def _bind(target, node, label, lineno):
    """Bind the call's shape to the signature; values are irrelevant."""
    signature = inspect.signature(target)
    args = []
    for a in node.args:
        if isinstance(a, ast.Starred):
            return          # *args at a call site: arity is not statically known
        args.append(object())
    kwargs = {}
    for kw in node.keywords:
        if kw.arg is None:
            return          # **kwargs likewise
        kwargs[kw.arg] = object()
    try:
        signature.bind(*args, **kwargs)
    except TypeError as exc:
        raise AssertionError(
            "%s:%d calls %s(%s) but its signature is %s%s -- %s"
            % (os.path.basename(agent_loop.__file__), lineno, label,
               ", ".join(["<pos>"] * len(args)
                         + ["%s=" % k for k in kwargs]),
               label, signature, exc))


def test_every_sibling_call_matches_its_signature():
    source = inspect.getsource(agent_loop)
    tree = ast.parse(source)
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        resolved = _resolve(node)
        if resolved is None:
            continue
        target, label = resolved
        _bind(target, node, label, node.lineno)
        checked += 1
    # A guard that checks nothing passes silently; assert it had work to do.
    assert checked >= 15, ("only %d cross-module calls found in agent_loop.py; "
                           "the walker is not seeing the module" % checked)
    print("      (%d cross-module calls bound)" % checked)


def test_the_cluster_table_call_is_the_one_that_broke():
    """The specific regression: render_partition_table takes two arguments."""
    signature = inspect.signature(
        sys.modules["src.classes.AIInterpret.clusters"].render_partition_table)
    assert len(signature.parameters) == 2, signature
    source = inspect.getsource(agent_loop)
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "render_partition_table"]
    assert calls, "agent_loop no longer renders the cluster table at all"
    for call in calls:
        assert len(call.args) + len(call.keywords) == 2, (
            "line %d passes %d argument(s) to render_partition_table"
            % (call.lineno, len(call.args) + len(call.keywords)))


def test_the_toolbelt_is_wired():
    """Each tool the loop advertises is a real SDK tool with a description."""
    names = []
    for tool in agent_loop.TOOLBELT:
        assert getattr(tool, "name", None), tool
        assert getattr(tool, "description", None), (
            "%s has no description, so the model cannot know what it does"
            % tool.name)
        names.append(tool.name)
    assert "submit_report" in names, "the loop has no door out"
    assert len(set(names)) == len(names), "duplicate tool names: %s" % names


def test_the_checker_rejects_the_original_defect():
    """A guard that cannot fail is decoration.

    Feed the checker the exact call that killed the first live run -- as a
    synthetic snippet, so the real module is never edited and no stale .pyc can
    be left behind -- and require it to complain.
    """
    snippet = "clusters_mod.render_partition_table(partition)"
    node = ast.parse(snippet).body[0].value
    target, label = _resolve(node)
    try:
        _bind(target, node, label, 1)
    except AssertionError as exc:
        assert "render_partition_table" in str(exc), exc
        return
    raise AssertionError(
        "the checker accepted render_partition_table(partition), the very "
        "call that failed in production -- it is not checking arity")


def main():
    for t in (test_every_sibling_call_matches_its_signature,
              test_the_cluster_table_call_is_the_one_that_broke,
              test_the_checker_rejects_the_original_defect,
              test_the_toolbelt_is_wired):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
