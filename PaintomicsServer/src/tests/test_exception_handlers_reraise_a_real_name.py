#!/usr/bin/env python3
"""An except handler must not raise a name that does not exist.

Why this exists
---------------
`KeggInformationManager.createTranslationCache` ended with

    except Exception as ex:
            raise exTran

and `exTran` is defined nowhere -- not in that file, not anywhere in the tree.
So the handler whose whole job is to propagate a failure raised a different
failure instead, and the real cause was lost:

    createTranslationCache(<unhashable jobID>)
      -> NameError: name 'exTran' is not defined

where the actual error was `TypeError: unhashable type`. Measured, not
supposed. Every other method in that class re-raises `ex`; this one was the
single outlier out of 168 server files, which is what a typo looks like rather
than an intention.

Reachability is narrow -- the guarded block only assigns a dict entry under a
lock, so it takes an unhashable jobID or memory pressure to enter the handler
at all. That is also why it survived: nothing routine executes this path, so
the first real failure here would have been reported as a NameError pointing at
the wrong line, in a manager that sits under every job's identifier mapping.

The check is written over the whole server rather than that one function,
because a handler that cannot re-raise is invisible until the day it matters,
and the cost of scanning is a syntax parse.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_exception_handlers_reraise_a_real_name
"""
import ast
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _sourceFiles():
    """Server sources, excluding tests and vendored libraries."""
    result = subprocess.run(
        ["find", SERVER_ROOT, "-name", "*.py",
         "-not", "-path", "*/tests/*", "-not", "-path", "*/lib/*"],
        capture_output=True, text=True)
    return [p for p in result.stdout.split() if p.endswith(".py")]


def _namesInScope(tree, handler):
    """Every name the module could plausibly bind, plus the handler's own."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.Global):
            names.update(node.names)
    if handler.name:
        names.add(handler.name)
    return names


class ExceptionHandlersReraiseTest(unittest.TestCase):

    def setUp(self):
        self.files = _sourceFiles()

    def test_the_scan_actually_sees_the_tree(self):
        """A find that matched nothing would make everything below vacuous."""
        self.assertGreater(len(self.files), 100,
                           "only %d server sources found; the scan below would "
                           "pass without checking anything" % len(self.files))

    def test_no_handler_raises_an_undefined_name(self):
        offenders = []
        for path in self.files:
            try:
                source = open(path, encoding="utf-8", errors="replace").read()
                tree = ast.parse(source)
            except Exception:
                continue
            for handler in (n for n in ast.walk(tree)
                            if isinstance(n, ast.ExceptHandler)):
                scope = _namesInScope(tree, handler)
                for node in ast.walk(handler):
                    if (isinstance(node, ast.Raise)
                            and isinstance(node.exc, ast.Name)
                            and node.exc.id not in scope
                            and not hasattr(__builtins__, node.exc.id)
                            and node.exc.id not in dir(__builtins__)):
                        offenders.append("%s:%d raises undefined %r"
                                         % (os.path.relpath(path, SERVER_ROOT),
                                            node.lineno, node.exc.id))

        self.assertEqual(offenders, [],
                         "these handlers raise a name that does not exist, so "
                         "they fail with NameError and hide the real error: %s"
                         % offenders)

    def test_a_handler_that_binds_reraises_that_binding(self):
        """The narrower rule: `except X as e` should re-raise e, not something else."""
        offenders = []
        for path in self.files:
            try:
                source = open(path, encoding="utf-8", errors="replace").read()
                tree = ast.parse(source)
            except Exception:
                continue
            for handler in (n for n in ast.walk(tree)
                            if isinstance(n, ast.ExceptHandler) and n.name):
                for node in ast.walk(handler):
                    if (isinstance(node, ast.Raise)
                            and isinstance(node.exc, ast.Name)
                            and node.exc.id != handler.name):
                        offenders.append("%s:%d binds %r but raises %r"
                                         % (os.path.relpath(path, SERVER_ROOT),
                                            node.lineno, handler.name, node.exc.id))

        self.assertEqual(offenders, [], "\n".join(offenders))


class CreateTranslationCacheTest(unittest.TestCase):
    """The specific function, exercised rather than read."""

    def test_the_real_error_reaches_the_caller(self):
        from src.common.KeggInformationManager import KeggInformationManager

        manager = KeggInformationManager("/tmp/does-not-matter/")

        with self.assertRaises(TypeError):
            # Unhashable jobID -> the dict assignment inside the guarded block
            # raises, which is the only routine way into that handler.
            manager.createTranslationCache(["unhashable"])

    def test_it_is_not_a_nameerror(self):
        """Naming the old failure explicitly, so a regression is unmistakable."""
        from src.common.KeggInformationManager import KeggInformationManager

        manager = KeggInformationManager("/tmp/does-not-matter/")

        try:
            manager.createTranslationCache(["unhashable"])
        except NameError as exc:
            self.fail("the handler raised NameError (%s) instead of "
                      "propagating the real error" % exc)
        except TypeError:
            pass

    def test_the_lock_is_released_either_way(self):
        """A leaked lock here would wedge every other request thread.

        Checked from a *second* thread on purpose. `self.lock` is an RLock
        (`from threading import RLock as threading_lock`), which is reentrant,
        so `acquire(blocking=False)` on the calling thread returns True whether
        or not the lock is still held -- an assertion made here would pass no
        matter what. Deleting the `finally: self.lock.release()` and running
        this proved it: same-thread version green, which is how the vacuity was
        found.

        A foreign thread is what the server actually has. Flask serves each
        request on its own thread, so a lock leaked by one of them blocks every
        later translation-cache call in the process, not the one that leaked it.
        """
        import threading

        from src.common.KeggInformationManager import KeggInformationManager

        manager = KeggInformationManager("/tmp/does-not-matter/")

        try:
            manager.createTranslationCache(["unhashable"])
        except Exception:
            pass

        result = {}

        def probe():
            result["acquired"] = manager.lock.acquire(timeout=5)
            if result["acquired"]:
                manager.lock.release()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=10)

        self.assertTrue(result.get("acquired"),
                        "another thread could not take the lock within 5s, so "
                        "the failed call left it held and every later "
                        "translation-cache call in this process would block")

    def test_the_ordinary_path_still_works(self):
        from src.common.KeggInformationManager import KeggInformationManager

        manager = KeggInformationManager("/tmp/does-not-matter/")

        manager.createTranslationCache("JOB123")
        self.assertIn("JOB123", manager.translationCache)

        manager.clearTranslationCache("JOB123")
        self.assertNotIn("JOB123", manager.translationCache)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
