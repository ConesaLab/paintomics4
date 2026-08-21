#!/usr/bin/env python3
"""Build reports/deadcode.md: one row per dead-code candidate with a verdict
and the evidence behind it.

Candidates come from two static tools and are judged against a third,
dynamic one:

  vulture   unused functions, methods, classes, attributes, variables and
            imports it cannot see a reference to (its confidence is kept)
  ruff      F401 unused import, F841 unused local variable, F811 redefinition
  coverage  which lines actually ran across the whole offline test sweep
            (233 suites) AND the 11-dataset regression -- a candidate that
            executed is by definition not dead, whatever the static tools say

plus a repository-wide reference index: every identifier token in every
Python, JavaScript, HTML, R, shell, config and template file, so a name
that is only ever reached through a string (a DAO field, a route, a
getattr, a JS call into the server) counts as referenced.

Verdict rules, in order:

  keep        it executed under coverage; or it is referenced anywhere else
              in the repository (by name, in any file type); or it is a
              parameter (vulture's "unused variable" on a def line); or it is
              an import in a module that paintomicsserver.py / DBManager.py
              star-import and the name is used there
  delete      an unused import (F401 / vulture 90%) with no other reference
              and no star-import consumer using it; an unused local variable
              whose assignment has no side effects (right-hand side is a
              name, attribute, constant or subscript); a function/method/
              class with zero references anywhere, never executed, and not
              reached through a decorator (routes, properties, handlers)
  uncertain   everything else: attributes (often set for serialisation),
              locals whose right-hand side is a call, names with one
              ambiguous textual hit, redefinitions

Only `delete` rows are removed. Re-run after deleting to confirm the rows
are gone rather than relocated.

    python scripts/deadcode_report.py --vulture vulture.txt --ruff ruff.json \
        --coverage coverage.json --out reports/deadcode.md
"""
import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
SERVER_SRC = os.path.join(REPO, "PaintomicsServer", "src")

# Modules whose namespace is re-exported by a `from X import *`, and who
# consumes them. An "unused" import in one of these may be used by the
# consumer.
STAR_EXPORTS = {
    "PaintomicsServer/src/conf/serverconf.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/resources/example_serverconf.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/DataManagementServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/UserManagementServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/Bed2GenesServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/MiRNA2GenesServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/AdminServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/servlets/AIInterpretServlet.py": ["PaintomicsServer/src/paintomicsserver.py"],
    "PaintomicsServer/src/AdminTools/scripts/downloadReactome.py": ["PaintomicsServer/src/AdminTools/DBManager.py"],
}

TEXT_SUFFIXES = (".py", ".js", ".html", ".tpl", ".R", ".r", ".sh", ".cfg", ".ini",
                 ".wsgi", ".yml", ".yaml", ".toml", ".txt", ".md", ".json", ".css")
SKIP_DIRS = {".git", "node_modules", "__pycache__", "examplefiles", "dist", "runs", "reports",
             "baseline"}
# References from here are tests exercising a name, not the product using it;
# they keep a name alive (deleting it would break the suite) but are reported
# as such.
TEST_DIR_MARKERS = ("/src/tests/", "/src/benchmarks/")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

VULTURE_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+): unused (?P<kind>import|variable|function|method|"
    r"class|attribute|property|code) '(?P<name>[^']+)' \((?P<conf>\d+)% confidence\)")


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def build_reference_index():
    """name -> {(relative file, line number)} over every text file in the
    repository that is not a test, a baseline or example data."""
    index = defaultdict(set)
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(TEXT_SUFFIXES):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, REPO)
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    for number, line in enumerate(handle, 1):
                        for token in set(IDENT.findall(line)):
                            index[token].add((rel, number))
            except OSError:
                continue
    return index


def load_coverage(path):
    """relative file -> (set of executed lines, set of statement lines)."""
    if not path or not os.path.isfile(path):
        return {}
    data = json.load(open(path, encoding="utf-8"))
    executed = {}
    marker = "PaintomicsServer/"
    for filename, info in data.get("files", {}).items():
        # The coverage run may have happened in another checkout of the
        # same tree (a git archive of the pre-deletion commit, a worktree);
        # key on the path from PaintomicsServer/ down, which is the same
        # everywhere.
        if marker in filename:
            rel = marker + filename.split(marker, 1)[1]
        elif os.path.isabs(filename):
            rel = os.path.relpath(os.path.abspath(filename), REPO)
        else:
            rel = filename
        executed[rel] = (set(info.get("executed_lines", [])),
                         set(info.get("executed_lines", [])) | set(info.get("missing_lines", [])))
    return executed


def load_vulture(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        match = VULTURE_LINE.match(line.strip())
        if not match:
            continue
        rel = os.path.relpath(os.path.abspath(os.path.join(REPO, match.group("file"))), REPO)
        rows.append({"file": rel, "line": int(match.group("line")),
                     "kind": match.group("kind"), "name": match.group("name"),
                     "tool": "vulture %s%%" % match.group("conf"),
                     "conf": int(match.group("conf"))})
    return rows


def load_ruff(path):
    rows = []
    for finding in json.load(open(path, encoding="utf-8")):
        code = finding["code"]
        if code not in ("F401", "F841", "F811"):
            continue
        filename = finding["filename"]
        marker = "PaintomicsServer/"
        if marker in filename:          # ruff writes absolute paths of the checkout it ran in
            rel = marker + filename.split(marker, 1)[1]
        else:
            rel = os.path.relpath(os.path.abspath(filename), REPO)
        message = finding["message"]
        name = re.search(r"`([^`]+)`", message)
        name = name.group(1) if name else message
        kind = {"F401": "import", "F841": "variable", "F811": "redefinition"}[code]
        rows.append({"file": rel, "line": finding["location"]["row"], "kind": kind,
                     "name": name.split(".")[-1] if kind == "import" else name,
                     "tool": "ruff " + code, "conf": 90 if code == "F401" else 60,
                     "fixable": bool(finding.get("fix"))})
    return rows


_AST_CACHE = {}


def parsed(rel):
    if rel not in _AST_CACHE:
        try:
            with open(os.path.join(REPO, rel), encoding="utf-8") as handle:
                _AST_CACHE[rel] = ast.parse(handle.read())
        except (OSError, SyntaxError):
            _AST_CACHE[rel] = None
    return _AST_CACHE[rel]


def node_at(rel, line):
    """The def/class/assign/import node starting on `line`, and whether a
    def on that line carries decorators."""
    tree = parsed(rel)
    if tree is None:
        return None, False
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) == line and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign,
                       ast.AnnAssign, ast.AugAssign, ast.Import, ast.ImportFrom, ast.For,
                       ast.With, ast.Tuple)):
            decorated = bool(getattr(node, "decorator_list", []))
            return node, decorated
        # decorated defs start on the decorator line in older parsers; check
        # the def line too
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.decorator_list and any(getattr(d, "lineno", 0) == line for d in node.decorator_list):
                return node, True
    return None, False


def side_effect_free(node):
    """An assignment whose right-hand side cannot do anything: a constant,
    a name, an attribute chain, a subscript of those, or a container of
    those."""
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return False
    value = node.value
    if value is None:
        return True

    def pure(expr):
        if isinstance(expr, (ast.Constant, ast.Name)):
            return True
        if isinstance(expr, ast.Attribute):
            return pure(expr.value)
        if isinstance(expr, ast.Subscript):
            return pure(expr.value) and pure(expr.slice)
        if isinstance(expr, (ast.Tuple, ast.List)):
            return all(pure(e) for e in expr.elts)
        if isinstance(expr, ast.Dict):
            return all(pure(k) for k in expr.keys if k) and all(pure(v) for v in expr.values)
        if isinstance(expr, ast.BinOp):
            return pure(expr.left) and pure(expr.right)
        if isinstance(expr, ast.UnaryOp):
            return pure(expr.operand)
        return False
    return pure(value)


_LINE_CACHE = {}


def line_text(rel, line):
    if rel not in _LINE_CACHE:
        try:
            with open(os.path.join(REPO, rel), encoding="utf-8", errors="replace") as handle:
                _LINE_CACHE[rel] = handle.read().splitlines()
        except OSError:
            _LINE_CACHE[rel] = []
    lines = _LINE_CACHE[rel]
    return lines[line - 1] if 0 < line <= len(lines) else ""


def enclosing_scope(rel, line):
    """Innermost function or class whose body contains `line`, or None when
    the line is at module level."""
    tree = parsed(rel)
    if tree is None:
        return None
    found = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.lineno < line <= getattr(node, "end_lineno", node.lineno):
            if found is None or node.lineno > found.lineno:
                found = node
    return found


def enclosing_class(rel, line):
    """Name of the class whose body contains `line`, or None."""
    tree = parsed(rel)
    if tree is None:
        return None
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.lineno < line <= getattr(node, "end_lineno", node.lineno):
            if found is None or node.lineno > found.lineno:
                found = node
    return found.name if found else None


def tracked_files():
    """Files git knows about; an untracked local file (the gitignored
    serverconf.py, a scratch script) is not a candidate for anything."""
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return set(out.split("\0")) - {""}


def uses_scriptine(rel):
    """scriptine.run() turns every module-level *_command function into a CLI
    sub-command, found by name at run time."""
    try:
        with open(os.path.join(REPO, rel), encoding="utf-8") as handle:
            return "scriptine.run()" in handle.read()
    except OSError:
        return False


def is_parameter(rel, line, name):
    tree = parsed(rel)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if getattr(node, "lineno", None) != line:
                continue
            args = node.args
            names = [a.arg for a in args.args + args.posonlyargs + args.kwonlyargs]
            if args.vararg:
                names.append(args.vararg.arg)
            if args.kwarg:
                names.append(args.kwarg.arg)
            if name in names:
                return True
    return False


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

def references(index, name, own_file, own_line):
    hits = {(f, n) for f, n in index.get(name, set()) if not (f == own_file and n == own_line)}
    return sorted(hits)


def _definition_at(rel, line):
    tree = parsed(rel)
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            starts = {node.lineno} | {d.lineno for d in node.decorator_list}
            if line in starts:
                return node
    return None


def _body_lines(node):
    """Lines that run only when the function is CALLED (for a class: when
    one of its methods is called). The def/class line itself executes at
    import time, so it says nothing about use."""
    if isinstance(node, ast.ClassDef):
        lines = set()
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines |= _body_lines(child)
        if lines:
            return lines
    lines = set()
    for statement in node.body:
        for child in ast.walk(statement):
            if hasattr(child, "lineno"):
                lines.add(child.lineno)
    return lines


def executed(coverage, rel, line):
    if rel not in coverage:
        return None
    ran, statements = coverage[rel]
    node = _definition_at(rel, line)
    if node is not None:
        body = _body_lines(node)
        if body & ran:
            return True
        if body & statements:
            return False
        return None
    if line in ran:
        return True
    if line in statements:
        return False
    return None


def is_test_path(rel):
    return any(marker in "/" + rel for marker in TEST_DIR_MARKERS)


def judge(row, index, coverage):
    rel, line, kind, name = row["file"], row["line"], row["kind"], row["name"]
    all_refs = references(index, name, rel, line)
    test_refs = [r for r in all_refs if is_test_path(r[0])]
    refs = [r for r in all_refs if not is_test_path(r[0])]
    same_file = [r for r in refs if r[0] == rel]
    other_files = [r for r in refs if r[0] != rel]
    ran = executed(coverage, rel, line)
    node, decorated = node_at(rel, line)
    evidence = []

    if ran is True:
        evidence.append("executed under coverage")
    elif ran is False:
        evidence.append("never executed")
    else:
        evidence.append("not measured")

    def where(hits, limit=3):
        return ", ".join("%s:%d" % h for h in hits[:limit]) + (" +%d" % (len(hits) - limit) if len(hits) > limit else "")

    # A name the test suite reaches for stays: removing it breaks the suite,
    # and a test-only helper is still a helper. For an import the only test
    # reference that counts is one importing that name FROM this module --
    # a test using its own `os` says nothing about this file's `import os`.
    if kind == "import":
        module = os.path.splitext(os.path.basename(rel))[0]
        test_refs = [r for r in test_refs
                     if (module in line_text(*r) and "import" in line_text(*r))
                     or (module + "." + name) in line_text(*r)]
    if test_refs and kind != "variable":
        product = (" and " + where(other_files)) if other_files else ""
        return "keep", "; ".join(evidence + ["used by tests: " + where(test_refs) + product])

    if kind == "import":
        consumers = STAR_EXPORTS.get(rel, [])
        used_by_star = [c for c in consumers if any(f == c for f, _ in refs)]
        if used_by_star:
            return "keep", "; ".join(evidence + ["used through `import *` in " + ", ".join(os.path.basename(c) for c in used_by_star)])
        if same_file:
            return "uncertain", "; ".join(evidence + ["name appears elsewhere in the file (%s) -- the tools call the import unused, check it is not a string/comment use" % where(same_file)])
        return "delete", "; ".join(evidence + ["no reference to the name in this module or its star-import consumers"])

    if kind == "variable":
        if is_parameter(rel, line, name):
            return "keep", "; ".join(evidence + ["a parameter; dropping it changes the signature"])
        # A module-level name is an attribute of the module: another file can
        # read or assign it as `module.NAME` (the species build scripts set
        # common_build_database.COMMON_RESOURCES that way), which vulture,
        # looking at one file, calls unused.
        if other_files and enclosing_scope(rel, line) is None:
            return "keep", "; ".join(evidence + ["module-level name referenced from " + where(other_files)])
        if "serverconf" in os.path.basename(rel):
            return "uncertain", "; ".join(evidence + ["a configuration value nothing reads; removing it is an operator-facing change, not a code deletion"])
        if isinstance(node, ast.AnnAssign) and enclosing_class(rel, line):
            return "keep", "; ".join(evidence + ["annotated class field (dataclass/typed record): part of the record's shape"])
        if isinstance(node, ast.Assign) and (len(node.targets) > 1 or not isinstance(node.targets[0], ast.Name)):
            return "uncertain", "; ".join(evidence + ["shares its statement with other bindings; dropping only this name is a rewrite"])
        if name.isupper() and enclosing_class(rel, line):
            return "uncertain", "; ".join(evidence + ["class-level constant (enum-style member) with no reader"])
        if node is not None and side_effect_free(node):
            return "delete", "; ".join(evidence + ["assignment has no side effects and the name is not read (%s)" % (("also appears at " + where(same_file)) if same_file else "no other occurrence in the file")])
        if isinstance(node, (ast.For, ast.With, ast.Tuple)) or node is None:
            return "uncertain", "; ".join(evidence + ["bound by unpacking/loop/with; renaming to _ is a rewrite, not a deletion"])
        return "uncertain", "; ".join(evidence + ["right-hand side is a call or expression that may have side effects; dropping the binding is a rewrite"])

    if kind == "redefinition":
        return "uncertain", "; ".join(evidence + ["redefinition; which definition wins needs reading"])

    if kind in ("attribute", "property"):
        if other_files or same_file:
            return "keep", "; ".join(evidence + ["referenced: " + where(refs)])
        return "uncertain", "; ".join(evidence + ["attributes are often read through serialisation or templates; no textual reference found"])

    # function / method / class
    if ran is True:
        return "keep", "; ".join(evidence)
    if decorated:
        return "keep", "; ".join(evidence + ["decorated (route/property/handler): reached without a call by name"])
    if kind == "function" and name.endswith("_command") and uses_scriptine(rel):
        return "keep", "; ".join(evidence + ["scriptine CLI command: dispatched by the *_command naming convention, never called by name"])
    if other_files:
        return "keep", "; ".join(evidence + ["referenced in " + where(other_files)])
    if same_file:
        return "uncertain", "; ".join(evidence + ["only referenced in its own file at " + where(same_file) + " (a string, comment or recursive use -- read it)"])
    if name.startswith("__") and name.endswith("__"):
        return "keep", "; ".join(evidence + ["dunder: called by the runtime"])
    return "delete", "; ".join(evidence + ["no reference to the name anywhere in the repository"])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def dedupe(rows):
    seen = {}
    for row in rows:
        key = (row["file"], row["line"], row["name"])
        if key in seen:
            seen[key]["tool"] += " + " + row["tool"]
            seen[key]["conf"] = max(seen[key]["conf"], row["conf"])
        else:
            seen[key] = dict(row)
    return sorted(seen.values(), key=lambda r: (r["file"], r["line"], r["name"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--vulture", required=True)
    parser.add_argument("--ruff", required=True)
    parser.add_argument("--coverage", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--overrides", default="",
                        help="JSON {\"file:line:name\": [verdict, reason]} applied last")
    args = parser.parse_args(argv)

    rows = dedupe(load_vulture(args.vulture) + load_ruff(args.ruff))
    tracked = tracked_files()
    if tracked is not None:
        rows = [row for row in rows if row["file"] in tracked]
    index = build_reference_index()
    coverage = load_coverage(args.coverage)
    overrides = json.load(open(args.overrides)) if args.overrides else {}

    counts = defaultdict(int)
    lines = []
    for number, row in enumerate(rows, 1):
        verdict, reason = judge(row, index, coverage)
        key = "%s:%d:%s" % (row["file"], row["line"], row["name"])
        if key in overrides:
            verdict, reason = overrides[key][0], overrides[key][1] + " (manual)"
        counts[verdict] += 1
        row["verdict"], row["reason"] = verdict, reason
        lines.append("| %d | `%s:%d` | %s | `%s` | %s | **%s** | %s |" % (
            number, row["file"].replace("PaintomicsServer/src/", ""), row["line"],
            row["kind"], row["name"], row["tool"], verdict, reason))

    covered_files = len(coverage)
    header = [
        "# Dead-code candidates",
        "",
        "Generated by `scripts/deadcode_report.py` from vulture (min confidence 60%%, "
        "tests and benchmarks excluded), ruff (F401/F841/F811) and coverage over the "
        "offline suite sweep plus the 11-dataset regression (%d source files measured). "
        "Paths are relative to `PaintomicsServer/src/`." % covered_files,
        "",
        "Verdicts: **keep** %d, **delete** %d, **uncertain** %d (%d candidates). "
        "Only `delete` rows are removed; the rules are in the script's docstring." % (
            counts["keep"], counts["delete"], counts["uncertain"], len(rows)),
        "",
        "| # | where | kind | name | tool | verdict | evidence |",
        "|---:|---|---|---|---|---|---|",
    ]
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(header + lines) + "\n")
    json.dump(rows, open(args.out + ".json", "w"), indent=1)
    print("%s: %d rows -- keep %d, delete %d, uncertain %d" % (
        args.out, len(rows), counts["keep"], counts["delete"], counts["uncertain"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
