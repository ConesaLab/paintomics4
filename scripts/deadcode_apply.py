#!/usr/bin/env python3
"""Apply the `delete` rows of reports/deadcode.md.json to the source tree.

Three kinds of deletion, each the smallest edit that removes the dead name
and nothing else:

  import     drop ONE name from an import statement (`from x import a, b`
             keeps `b`; `import os` goes entirely); a statement left with no
             names is removed, parentheses and trailing commas included
  variable   remove the assignment statement (the report only marks
             side-effect-free, single-target assignments for deletion)
  function / method / class
             remove the whole definition, decorators and the blank lines
             that separated it from what follows

Edits are made bottom-up per file so line numbers stay valid, and every
touched file is re-parsed afterwards; a block that would be left empty gets
a `pass` so the file still compiles. Run the report again after applying:
the delete rows must be gone, and the regression and the test suite must
be unchanged.

    python scripts/deadcode_apply.py --report reports/deadcode.md.json [--dry-run]
"""
import argparse
import ast
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))


def statement_at(tree, line, kind=None):
    """The statement node starting at `line` (decorators count as the start
    of their def/class), or None. For imports the reported line is the line
    of the NAME, which inside a parenthesised multi-line import is not the
    statement's first line, so an import is matched on its whole extent."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if kind == "import" and isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.lineno <= line <= node.end_lineno:
                return node
            continue
        starts = {node.lineno}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            starts |= {d.lineno for d in node.decorator_list}
        if line in starts:
            return node
    return None


def extent(node):
    """(first line, last line) of a statement including its decorators."""
    first = node.lineno
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        first = min([first] + [d.lineno for d in node.decorator_list])
    return first, node.end_lineno


def remove_import_names(lines, node, names_to_drop):
    """Rewrite the import statement without the given names, all at once --
    several rows can point at one parenthesised statement. Returns the
    replacement lines (possibly empty)."""
    first, last = extent(node)
    if isinstance(node, ast.Import):
        keep = [a for a in node.names
                if (a.asname or a.name.split(".")[-1]) not in names_to_drop and a.name not in names_to_drop]
        if not keep:
            return []
        indent = lines[first - 1][:len(lines[first - 1]) - len(lines[first - 1].lstrip())]
        return [indent + "import " + ", ".join(a.name + (" as " + a.asname if a.asname else "") for a in keep)]
    # the report names the imported symbol; ruff names the alias, vulture the
    # module-side name, so either identifies the entry
    keep = [a for a in node.names
            if (a.asname or a.name) not in names_to_drop and a.name not in names_to_drop]
    if not keep:
        return []
    indent = lines[first - 1][:len(lines[first - 1]) - len(lines[first - 1].lstrip())]
    module = ("." * node.level) + (node.module or "")
    names = [a.name + (" as " + a.asname if a.asname else "") for a in keep]
    one_line = "%sfrom %s import %s" % (indent, module, ", ".join(names))
    if len(one_line) <= 100 or last == first:
        return [one_line]
    body = [indent + "    " + n + "," for n in names]
    return ["%sfrom %s import (" % (indent, module)] + body + [indent + ")"]


def parent_block_would_empty(tree, node):
    """True when removing `node` leaves its parent's body empty."""
    for parent in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(parent, field, None)
            if isinstance(block, list) and any(child is node for child in block):
                return len(block) == 1
    return False


def apply_file(rel, rows, dry_run):
    path = os.path.join(REPO, rel)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    lines = source.splitlines()
    tree = ast.parse(source)

    edits = []   # (first, last, replacement lines)
    skipped = []
    import_groups = {}   # id(node) -> (node, [names], [rows])
    for row in rows:
        node = statement_at(tree, row["line"], row["kind"])
        if node is None:
            skipped.append((row, "no statement starts on that line"))
            continue
        kind = row["kind"]
        if kind == "import":
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                skipped.append((row, "not an import statement"))
                continue
            group = import_groups.setdefault(id(node), (node, [], []))
            group[1].append(row["name"])
            group[2].append(row)
            continue
        elif kind == "variable":
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                skipped.append((row, "not an assignment"))
                continue
            replacement = []
        elif kind in ("function", "method", "class"):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    or node.name != row["name"]:
                skipped.append((row, "definition not found at that line"))
                continue
            replacement = []
        else:
            skipped.append((row, "kind %s is not deletable" % kind))
            continue
        first, last = extent(node)
        if not replacement and parent_block_would_empty(tree, node):
            indent = lines[first - 1][:len(lines[first - 1]) - len(lines[first - 1].lstrip())]
            replacement = [indent + "pass"]
        edits.append((first, last, replacement, [row]))

    for node, names, group_rows in import_groups.values():
        first, last = extent(node)
        replacement = remove_import_names(lines, node, set(names))
        if not replacement and parent_block_would_empty(tree, node):
            indent = lines[first - 1][:len(lines[first - 1]) - len(lines[first - 1].lstrip())]
            replacement = [indent + "pass"]
        edits.append((first, last, replacement, group_rows))

    # bottom-up so earlier line numbers stay valid
    edits.sort(key=lambda e: -e[0])
    applied = []
    for first, last, replacement, edit_rows in edits:
        # a deleted definition also takes the blank lines that followed it,
        # so two definitions do not end up separated by four blank lines
        end = last
        if not replacement and edit_rows[0]["kind"] in ("function", "method", "class"):
            while end < len(lines) and lines[end].strip() == "" and (end - last) < 2:
                end += 1
        lines[first - 1:end] = replacement
        applied.extend(edit_rows)

    new_source = "\n".join(lines) + ("\n" if source.endswith("\n") else "")
    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        print("%s: result does not parse (%s); file left untouched" % (rel, exc), file=sys.stderr)
        return [], [(row, "syntax after edit") for *_, edit_rows in edits for row in edit_rows]
    if not dry_run and new_source != source:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new_source)
    return applied, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--report", required=True, help="reports/deadcode.md.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rows = [r for r in json.load(open(args.report, encoding="utf-8")) if r["verdict"] == "delete"]
    by_file = defaultdict(list)
    for row in rows:
        by_file[row["file"]].append(row)

    total_applied, total_skipped = 0, []
    for rel in sorted(by_file):
        applied, skipped = apply_file(rel, by_file[rel], args.dry_run)
        total_applied += len(applied)
        total_skipped += skipped
        print("%-70s %d removed%s" % (rel, len(applied), ", %d skipped" % len(skipped) if skipped else ""))
    print("\n%d of %d delete rows applied%s" % (total_applied, len(rows), " (dry run)" if args.dry_run else ""))
    for row, why in total_skipped:
        print("  skipped %s:%d %s %s -- %s" % (row["file"], row["line"], row["kind"], row["name"], why))
    return 1 if total_skipped else 0


if __name__ == "__main__":
    sys.exit(main())
