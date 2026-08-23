#!/usr/bin/env python3
"""The figure sandbox must exec a Python, never the web server.

Why this exists
---------------
`figure_sandbox` used to exec `sys.executable`. Under uWSGI that is the uwsgi
binary itself -- uWSGI embeds libpython and points `sys.executable` at its own
path -- so in production every figure render handed `figure.py` to the web
server's argument parser and died with rc=-1 RENDER FAILED. It was invisible
locally because `launch_server.py` runs under a real Python, which is where
every Chrome verification had been done.

`src/common/PythonExecutable.py` now resolves the interpreter by probing
candidates for `-I -c "import matplotlib"`, and the sandbox execs what it
resolves. These tests pin the contract:

  * what resolve() returns exists, is executable, and is named like a Python;
  * when `sys.executable` is NOT a Python (the uWSGI case), the resolver
    still finds a real interpreter and never returns the impostor;
  * the operator override (PYTHON_EXECUTABLE) wins when it probes clean;
  * a render's own child process reports the resolved interpreter, not
    whatever `sys.executable` says.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_figure_renderer_is_a_python
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.common import PythonExecutable  # noqa: E402


class ResolveTest(unittest.TestCase):

    def setUp(self):
        PythonExecutable.reset_cache_for_tests()
        self._env = os.environ.pop("PYTHON_EXECUTABLE", None)

    def tearDown(self):
        if self._env is not None:
            os.environ["PYTHON_EXECUTABLE"] = self._env
        else:
            os.environ.pop("PYTHON_EXECUTABLE", None)
        PythonExecutable.reset_cache_for_tests()

    def test_resolves_to_an_executable_python(self):
        path = PythonExecutable.resolve()
        self.assertTrue(os.path.isfile(path), path)
        self.assertTrue(os.access(path, os.X_OK), path)
        self.assertTrue(os.path.basename(path).lower().startswith("python"),
                        "resolved %r, which is not named like a Python" % path)

    def test_result_is_cached(self):
        first = PythonExecutable.resolve()
        with mock.patch.object(PythonExecutable, "_resolve_uncached",
                               side_effect=AssertionError("re-probed")):
            self.assertEqual(first, PythonExecutable.resolve())

    def test_uwsgi_case_never_returns_the_impostor(self):
        # Simulate uWSGI: sys.executable exists, is executable, is not Python.
        impostor = "/usr/bin/true"
        with mock.patch.object(sys, "executable", impostor):
            path = PythonExecutable.resolve()
        self.assertNotEqual(os.path.realpath(path),
                            os.path.realpath(impostor))
        self.assertTrue(os.path.basename(path).lower().startswith("python"),
                        "with sys.executable=%r the resolver picked %r"
                        % (impostor, path))

    def test_operator_override_wins(self):
        os.environ["PYTHON_EXECUTABLE"] = sys.executable
        PythonExecutable.reset_cache_for_tests()
        self.assertEqual(PythonExecutable.resolve(), sys.executable)

    def test_a_broken_override_is_skipped_not_obeyed(self):
        os.environ["PYTHON_EXECUTABLE"] = "/no/such/interpreter"
        PythonExecutable.reset_cache_for_tests()
        path = PythonExecutable.resolve()
        self.assertNotEqual(path, "/no/such/interpreter")
        self.assertTrue(os.path.isfile(path))

    def test_describe_tells_the_story(self):
        story = PythonExecutable.describe()
        self.assertIn("figure renderer:", story)
        self.assertIn(PythonExecutable.resolve(), story)


class SandboxUsesItTest(unittest.TestCase):
    """The render child must BE the resolved interpreter."""

    def setUp(self):
        PythonExecutable.reset_cache_for_tests()
        self.bundle = tempfile.mkdtemp(prefix="figbundle-")

    def tearDown(self):
        shutil.rmtree(self.bundle, ignore_errors=True)
        PythonExecutable.reset_cache_for_tests()

    def test_child_reports_the_resolved_interpreter(self):
        from src.classes.AIInterpret import figure_sandbox
        with open(os.path.join(self.bundle, "figure.py"), "w") as fh:
            fh.write("import sys\n"
                     "open('who.txt', 'w').write(sys.executable)\n")
        result = figure_sandbox.render(self.bundle, timeout=30)
        self.assertTrue(result.ok, getattr(result, "stderr_tail", ""))
        with open(os.path.join(self.bundle, "who.txt")) as fh:
            child = fh.read().strip()
        resolved = PythonExecutable.resolve()
        self.assertEqual(os.path.realpath(child), os.path.realpath(resolved))
        self.assertTrue(os.path.basename(child).lower().startswith("python"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
