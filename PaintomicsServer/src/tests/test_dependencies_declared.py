"""Every third-party module the application imports must be in requirements.txt.

Run from `PaintomicsServer/`:

    python -m src.tests.test_dependencies_declared

Three separate dependencies were found missing while preparing the release, one
of them only when the container refused to boot:

  * `requests`    -- imported by DBManager.py and downloadReactome.py
  * `chardet`     -- imported by PathwayAcquisitionJob.py; ModuleNotFoundError
                     at start-up in a clean image
  * `eval_type_backport` -- needed for `import agents` on Python 3.9

All three were invisible locally because the development environment had them
installed for unrelated reasons. This walks the AST of every module under src/
and checks each external import actually resolves, so the next one fails here
instead of in production.
"""
import ast
import importlib.util
import os
import pathlib
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_PASSED = []
_FAILED = []

_SRC_ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO_ROOT = _SRC_ROOT.parent.parent

# Packages resolved by the application's own sys.path manipulation rather than
# by installation. AdminTools scripts insert their parent directory and then
# import these as top-level modules.
_LOCAL_MODULES = {
    "src", "conf", "scripts", "common", "classes", "servlets", "resources",
    "paintomicsserver", "AdminTools", "tests", "bioscripts", "DAO",
    "JobInstances", "DBManager",
}

# Provided by the uWSGI runtime, not importable outside it.
_RUNTIME_ONLY = {"uwsgi", "uwsgidecorators"}


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print(f"PASS  {name}")
    except AssertionError as exc:
        _FAILED.append((name, str(exc)))
        print(f"FAIL  {name}: {exc}")
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print(f"ERROR {name}:\n{traceback.format_exc()}")


def _externalImports():
    """{module: first source file} for every non-local top-level import."""
    found = {}
    for path in _SRC_ROOT.rglob("*.py"):
        text = str(path)
        # src/src is a symlink back to src; skip it so files are not visited twice.
        if "__pycache__" in text or "/src/src/" in text:
            continue
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root in _LOCAL_MODULES or root in _RUNTIME_ONLY or root.startswith("_"):
                    continue
                found.setdefault(root, str(path.relative_to(_SRC_ROOT)))
    return found


def test_every_external_import_resolves():
    """Catches an undeclared dependency in whatever env the tests run in."""
    unresolved = []
    for module, source in sorted(_externalImports().items()):
        if importlib.util.find_spec(module) is None:
            unresolved.append(f"{module} (imported by {source})")

    assert not unresolved, (
        "modules are imported but not installed; add them to requirements.txt:\n  "
        + "\n  ".join(unresolved))


def test_there_is_exactly_one_requirements_file():
    """The root requirements.txt must be the only pip manifest in the tree.

    This asserted the opposite until 2026-08-11: that
    `PaintomicsServer/src/requirements.txt` still existed, reduced to a single
    `-r ../../requirements.txt` include. That stub was well intentioned -- it
    redirected anyone installing from the path they were used to -- and it cost
    33 open Dependabot alerts.

    GitHub's dependency graph never re-parsed it. A pip manifest whose only
    content is an `-r` include yields no requirements, and rather than clearing
    the manifest GitHub kept the last snapshot it had successfully read: the
    2020 pins, Flask 1.1.2 / Werkzeug 1.0.1 / Jinja2 2.11.2 / CairoSVG 2.7.0 /
    Pillow 10.3.0. Measured against the API, every open alert on this repository
    named this file and none named the root, whose 63 alerts are all fixed --
    and new ones were still being raised against the stale snapshot as recently
    as 2026-08-07 (alert 320, pillow < 12.3.0). The advisories were real; the
    versions they were raised against had not been installed by anything for
    months.

    Nothing read the stub: the image installs the root file
    (deploy/Dockerfile), and there are no CI workflows. Deleting it is what the
    deployment plan called for in the first place -- see
    docs/superpowers/plans/2026-08-05-drago-cloud-deployment.md, "Delete:
    PaintomicsServer/src/requirements.txt".

    So the guard is inverted: a second manifest anywhere in the tree is the
    defect, whether it duplicates the pins or merely points at them.
    """
    stray = [path for path in _REPO_ROOT.rglob("requirements*.txt")
             if ".git" not in path.parts
             and "node_modules" not in path.parts
             and path != _REPO_ROOT / "requirements.txt"]
    assert not stray, (
        "a second pip manifest exists; GitHub's dependency graph will scan it "
        "and raise alerts against whatever it last managed to parse there, "
        "which is what produced 33 phantom alerts against a file containing "
        "nothing but an -r include. The root requirements.txt is the only one. "
        f"Found: {[str(p.relative_to(_REPO_ROOT)) for p in stray]}")
    assert (_REPO_ROOT / "requirements.txt").is_file(), \
        "the root requirements.txt is missing"


def test_known_previously_missing_dependencies_are_declared():
    """Regression guard for the three that actually broke."""
    requirements = (_REPO_ROOT / "requirements.txt").read_text().lower()
    for package in ("requests", "chardet", "eval_type_backport"):
        assert package in requirements, \
            f"'{package}' is missing from requirements.txt again"


def main():
    tests = [
        test_every_external_import_resolves,
        test_there_is_exactly_one_requirements_file,
        test_known_previously_missing_dependencies_are_declared,
    ]
    for t in tests:
        _check(t.__name__, t)

    print()
    print(f"Passed: {len(_PASSED)} / {len(_PASSED)+len(_FAILED)}")
    if _FAILED:
        for name, msg in _FAILED:
            print(f"  - {name}: {msg.splitlines()[0] if msg else ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()
