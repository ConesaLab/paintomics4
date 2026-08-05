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


def test_requirements_file_is_the_single_source_of_truth():
    """src/requirements.txt must defer to the root file, not duplicate it."""
    nested = _SRC_ROOT / "requirements.txt"
    assert nested.is_file(), "PaintomicsServer/src/requirements.txt is missing"

    content = nested.read_text()
    pins = [line for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#") and "==" in line]
    assert not pins, (
        "PaintomicsServer/src/requirements.txt pins versions again; it drifted out of sync "
        "with the root file once already (CairoSVG 2.4.2 vs 2.7.0, Pillow 8.0.1 vs 10.3.0). "
        f"It must only contain an -r include. Found: {pins}")
    assert "-r " in content, "expected an '-r' include pointing at the root requirements.txt"


def test_known_previously_missing_dependencies_are_declared():
    """Regression guard for the three that actually broke."""
    requirements = (_REPO_ROOT / "requirements.txt").read_text().lower()
    for package in ("requests", "chardet", "eval_type_backport"):
        assert package in requirements, \
            f"'{package}' is missing from requirements.txt again"


def main():
    tests = [
        test_every_external_import_resolves,
        test_requirements_file_is_the_single_source_of_truth,
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
