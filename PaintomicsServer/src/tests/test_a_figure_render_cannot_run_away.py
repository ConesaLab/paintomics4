#!/usr/bin/env python3
"""A render that misbehaves must cost one figure, never the server.

This deployment runs `processes=1 threads=4` -- four uWSGI threads serve the
whole site -- so the blast radius of a plotting script that allocates forever,
spins forever, or writes forever is not "one bad figure", it is an outage. The
four cases below are the four ways that has happened to somebody:

  * the script works                 -> ok, and the artefacts are named
  * the script writes outside cwd    -> NOT contained (no root, no jail); the
                                        test pins the honest behaviour so that
                                        nobody later reads `files_written` as a
                                        containment guarantee
  * the script writes a huge file    -> RLIMIT_FSIZE stops it
  * the script never returns         -> the wall clock stops it

And one more that is easy to forget: a bundle with no `figure.py` at all must
come back as a VERDICT. `render()` is called from a tool whose contract is to
turn a failure into a GAP line; it cannot do that with a traceback.

Every fixture is hand-written text. matplotlib is deliberately not required --
it is not in this environment and not in requirements.txt, and a QA suite that
only runs where the plotting stack is installed is a QA suite that does not run.

    python -m src.tests.test_a_figure_render_cannot_run_away
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "../..")))

from src.classes.AIInterpret import figure_sandbox as SB      # noqa: E402


class FigureRenderCannotRunAway(unittest.TestCase):

    def setUp(self):
        self.dirs = []
        # Saved and restored because two tests lower a ceiling to keep the
        # suite fast; leaking that into the next test would make a real limit
        # look far tighter than it ships.
        self._fsize = SB.RLIMIT_FSIZE_BYTES

    def tearDown(self):
        SB.RLIMIT_FSIZE_BYTES = self._fsize
        for path in self.dirs:
            shutil.rmtree(path, ignore_errors=True)

    def _bundle(self, script):
        path = tempfile.mkdtemp(prefix="figbundle_")
        self.dirs.append(path)
        with open(os.path.join(path, SB.SCRIPT_NAME), "w") as fh:
            fh.write(script)
        return path

    # -- the happy path ----------------------------------------------------

    def test_a_clean_render_reports_what_it_wrote(self):
        """ok, rc 0, the artefacts named, and a log left behind.

        `files_written` is a diff of the bundle taken around the run, not a
        listing: a bundle that already held a stale figure.svg from a previous
        attempt must not report it as this render's output.
        """
        bundle = self._bundle(
            "with open('figure.svg', 'w') as fh:\n"
            "    fh.write('<svg xmlns=\"http://www.w3.org/2000/svg\"/>')\n"
            "print('rendered')\n")
        # A stale artefact from an earlier attempt, untouched by this render.
        with open(os.path.join(bundle, "data.tsv"), "w") as fh:
            fh.write("feature\tG12D\n")

        result = SB.render(bundle, timeout=30)

        self.assertTrue(result.ok, result.stderr_tail)
        self.assertEqual(0, result.returncode)
        self.assertIn("figure.svg", result.files_written)
        self.assertNotIn("data.tsv", result.files_written,
                         "files_written must be a diff, not a directory "
                         "listing")
        self.assertGreaterEqual(result.seconds, 0.0)
        log = os.path.join(bundle, SB.RENDER_LOG)
        self.assertTrue(os.path.isfile(log), "a render must leave forensics")
        with open(log) as fh:
            text = fh.read()
        self.assertIn("rendered", text, "stdout must reach render.log")
        self.assertIn("rlimits tried", text,
                      "the log must say which ceilings were attempted, since a "
                      "kernel that refuses one (macOS + RLIMIT_AS) is silent")

    def test_the_child_gets_four_variables_and_no_home(self):
        """A generated plot script has no business reading this process's env.

        The failure this prevents is the ordinary one: a subprocess that
        inherits `os.environ` puts an API key one `print(os.environ)` away from
        a render.log the user can download. HOME is absent as well, so the
        script cannot reach the service account's dotfiles by accident.
        """
        bundle = self._bundle(
            "import os, json\n"
            "print(json.dumps(sorted(os.environ)))\n")
        result = SB.render(bundle, timeout=30)
        self.assertTrue(result.ok, result.stderr_tail)
        with open(os.path.join(bundle, SB.RENDER_LOG)) as fh:
            text = fh.read()
        self.assertIn('"MPLBACKEND"', text)
        self.assertIn('"MPLCONFIGDIR"', text)
        self.assertNotIn('"HOME"', text, "HOME must not be inherited")
        self.assertNotIn('"PYTHONPATH"', text)

    # -- the three ways a script misbehaves --------------------------------

    def test_a_write_outside_the_bundle_is_not_credited_or_claimed(self):
        """There is NO filesystem jail here, and this test says so out loud.

        seccomp/unshare need root, which we have on neither Garnatxa nor UV, so
        an absolute path outside the bundle really is written. What the sandbox
        does provide is that (a) every RELATIVE path lands in the bundle because
        cwd is the bundle, (b) RLIMIT_FSIZE caps whatever it writes anywhere,
        and (c) `files_written` reports only the bundle, so a stray write is
        never mistaken for a produced artefact.

        Pinning the limitation in a test is the point: the day someone reads
        `files_written` as proof of containment, this test is the thing that
        tells them otherwise.
        """
        escape_dir = tempfile.mkdtemp(prefix="figescape_")
        self.dirs.append(escape_dir)
        stray = os.path.join(escape_dir, "stray.txt")
        bundle = self._bundle(
            "open('inside.txt', 'w').write('relative paths land in the bundle')\n"
            "open(%r, 'w').write('absolute paths are not blocked')\n" % stray)

        result = SB.render(bundle, timeout=30)

        self.assertIn("inside.txt", result.files_written,
                      "cwd must be the bundle, so a relative write lands here")
        self.assertNotIn("stray.txt", result.files_written)
        self.assertFalse(any("stray" in f for f in result.files_written),
                         "files_written must describe the bundle only")
        self.assertTrue(os.path.exists(stray),
                        "documenting the truth: without root the write "
                        "succeeds -- if this ever fails, a real jail was added "
                        "and the docstrings must stop apologising for its "
                        "absence")

    def test_the_module_admits_it_cannot_jail_the_filesystem(self):
        """The design says document it rather than pretend; check the document.

        A sandbox believed to do more than it does is worse than no sandbox,
        because the belief is what removes the review from the code paths that
        feed it.
        """
        doc = SB.__doc__ or ""
        self.assertIn("NOT contained: the filesystem", doc)
        self.assertIn("NOT contained: the network", doc)
        self.assertIn("root", doc)

    def test_a_runaway_write_is_stopped_by_rlimit_fsize(self):
        """RLIMIT_FSIZE, exercised through the real preexec_fn.

        The ceiling is lowered from 50 MB to 64 kB for speed only: the code path
        under test -- the limit plan, the fork, the setrlimit in the child -- is
        byte for byte the one that ships. Writing 50 MB to prove it would leave
        50 MB of junk behind and test nothing extra.

        The child's exit differs by platform and both are a failure: Linux
        delivers SIGXFSZ (returncode -25), macOS surfaces EFBIG to Python and
        the script dies with a traceback (returncode 1). The assertion is
        therefore "did not succeed", not a magic number.
        """
        if not SB._HAVE_RESOURCE:
            self.skipTest("no resource module: rlimits are POSIX-only")
        SB.RLIMIT_FSIZE_BYTES = 64 * 1024
        bundle = self._bundle(
            "with open('big.bin', 'wb') as fh:\n"
            "    for _ in range(64):\n"
            "        fh.write(b'x' * 65536)\n"
            "        fh.flush()\n"
            "print('a 4 MB write should never have completed')\n")

        result = SB.render(bundle, timeout=60)

        self.assertFalse(result.ok, "a 4 MB write under a 64 kB ceiling passed")
        self.assertNotEqual(0, result.returncode)
        self.assertLess(os.path.getsize(os.path.join(bundle, "big.bin")),
                        2 * 64 * 1024,
                        "the file grew past the ceiling")

    def test_a_script_that_never_returns_is_killed_by_the_wall_clock(self):
        """A sleep burns no CPU, so RLIMIT_CPU would never fire on it.

        That is the whole reason the wall-clock timeout exists alongside the CPU
        ceiling -- a script blocked on a socket or a lock looks idle to the
        kernel and would sit on a uWSGI thread until the request died.
        """
        bundle = self._bundle("import time\n"
                              "print('start', flush=True)\n"
                              "time.sleep(120)\n")
        started = time.monotonic()
        result = SB.render(bundle, timeout=2)
        elapsed = time.monotonic() - started

        self.assertFalse(result.ok)
        self.assertLess(elapsed, 30, "the timeout did not actually kill it")
        self.assertIn("TIMEOUT", result.stderr_tail,
                      "the caller must be able to tell a timeout from a crash")
        with open(os.path.join(bundle, SB.RENDER_LOG)) as fh:
            self.assertIn("start", fh.read(),
                          "partial output must survive the kill -- it is "
                          "usually the only clue to where it hung")

    # -- failures that are verdicts, not exceptions ------------------------

    def test_a_bundle_with_no_script_returns_a_verdict(self):
        path = tempfile.mkdtemp(prefix="figempty_")
        self.dirs.append(path)
        result = SB.render(path, timeout=5)
        self.assertFalse(result.ok)
        self.assertEqual(-1, result.returncode)
        self.assertIn("figure.py", result.stderr_tail)

    def test_a_missing_bundle_returns_a_verdict(self):
        result = SB.render("/nonexistent/bundle/definitely/not/here", timeout=5)
        self.assertFalse(result.ok)
        self.assertEqual(-1, result.returncode)
        self.assertIn("no such bundle", result.stderr_tail.lower())

    def test_a_script_that_raises_is_data_not_an_exception(self):
        bundle = self._bundle("raise ValueError('the slice was empty')\n")
        result = SB.render(bundle, timeout=30)
        self.assertFalse(result.ok)
        self.assertEqual(1, result.returncode)
        self.assertIn("the slice was empty", result.stderr_tail)


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(FigureRenderCannotRunAway))
    sys.exit(0 if r.wasSuccessful() else 1)
