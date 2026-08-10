#!/usr/bin/env python3
"""Cover for the MORE backend choice in src/servlets/MOREServlet.py.

MORE has two interchangeable engines behind one CLI: `Rscript runMORE.R`, and
`more-rs`, the Rust port of the PLS1 kernel. They were measured to agree on the
bundled `06-regulatory-more` example -- six of the seven output files
byte-identical, the seventh identical as a multiset and differing only in row
order -- so the choice between them is an operational one.

Two facts make the choice non-obvious, and both are pinned here:

* **The port implements PLS1 only.** `--method MLR` exits pointing back at
  runMORE.R rather than silently doing something different. Routing an MLR job
  to the binary would turn a working analysis into a failed one, so MLR must
  reach R whatever the configuration says.
* **The binary is optional.** It is absent from the deploy image today. A
  configured-but-missing path must degrade to R rather than raise, or a stale
  setting takes MORE down entirely.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_backend_selection
"""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import MOREServlet


R_SCRIPT = "/opt/paintomics/src/common/bioscripts/runMORE.R"


class ResolveMOREBackendTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="more_backend_")
        self.binary = os.path.join(self.tmp, "more-rs")
        with open(self.binary, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.binary, os.stat(self.binary).st_mode | stat.S_IXUSR)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pls1_uses_the_binary_when_one_is_configured(self):
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, self.binary),
            [self.binary])

    def test_pls1_discovers_a_binary_when_none_is_configured(self):
        """Blank means "go and find one", which is what makes the port default.

        This is the whole of the change: an operator who has configured nothing
        gets the Rust backend for PLS1, because that is the case the port was
        measured byte-equal for. Discovery is patched rather than relying on
        whatever happens to be installed on the machine running the tests.
        """
        with mock.patch.object(MOREServlet, "_discoverMoreRs",
                               return_value=self.binary):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, ""),
                [self.binary])

    def test_pls1_falls_back_to_r_when_nothing_can_be_discovered(self):
        """A host with no binary anywhere behaves exactly as it did before.

        This is what keeps the new default safe to ship: turning the port on by
        default must not be able to break a deployment that has never had one.
        """
        with mock.patch.object(MOREServlet, "_discoverMoreRs", return_value=""):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, ""),
                ["Rscript", R_SCRIPT])

    def test_the_off_switch_forces_r_even_though_a_binary_exists(self):
        """`off` is the documented opt-out, and it must beat discovery.

        Without it there would be no way back to R once a binary is installed,
        which matters for anyone reproducing an older result.
        """
        with mock.patch.object(MOREServlet, "_discoverMoreRs",
                               return_value=self.binary):
            for value in ("off", "OFF", " off ", "none", "false", "0", "no",
                          "disabled"):
                self.assertEqual(
                    MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, value),
                    ["Rscript", R_SCRIPT], "%r must force R" % value)

    def test_discovery_prefers_the_bundled_binary_over_path(self):
        """Beside runMORE.R first, so a deployment controls its own version."""
        with mock.patch.object(MOREServlet.os.path, "isfile",
                               lambda p: p == MOREServlet.MORE_RS_BUNDLED), \
             mock.patch.object(MOREServlet.os, "access", lambda p, m: True), \
             mock.patch.object(MOREServlet.shutil, "which",
                               return_value="/usr/bin/more-rs"):
            self.assertEqual(MOREServlet._discoverMoreRs(),
                             MOREServlet.MORE_RS_BUNDLED)

    def test_discovery_falls_through_to_path(self):
        with mock.patch.object(MOREServlet.os.path, "isfile", return_value=False), \
             mock.patch.object(MOREServlet.shutil, "which",
                               return_value="/usr/bin/more-rs"):
            self.assertEqual(MOREServlet._discoverMoreRs(), "/usr/bin/more-rs")

    def test_discovery_returns_empty_when_there_is_nothing(self):
        with mock.patch.object(MOREServlet.os.path, "isfile", return_value=False), \
             mock.patch.object(MOREServlet.shutil, "which", return_value=None):
            self.assertEqual(MOREServlet._discoverMoreRs(), "")

    def test_mlr_ignores_a_discoverable_binary_too(self):
        """MLR must not be reachable by the discovery path either.

        The port implements MLR, so this is not a capability guard: R's MLR
        draws from the RNG in three places and the port sits inside R's seed
        band rather than on it, which is a difference to opt into rather than
        have chosen silently.
        """
        with mock.patch.object(MOREServlet, "_discoverMoreRs",
                               return_value=self.binary):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("MLR", R_SCRIPT, ""),
                ["Rscript", R_SCRIPT])

    def test_a_configured_binary_that_is_not_on_disk_falls_back_to_r(self):
        """A stale path must not take MORE down; R is always installed."""
        self.assertEqual(
            MOREServlet._resolveMOREBackend(
                "PLS1", R_SCRIPT, os.path.join(self.tmp, "absent")),
            ["Rscript", R_SCRIPT])

    def test_a_configured_binary_that_is_not_executable_falls_back_to_r(self):
        """An unpacked-without-the-mode-bit binary would fail with EACCES."""
        os.chmod(self.binary, stat.S_IRUSR | stat.S_IWUSR)
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, self.binary),
            ["Rscript", R_SCRIPT])

    def test_mlr_always_uses_r_even_when_the_binary_is_present(self):
        """MLR stays on R by policy, not because the port lacks it.

        `more-rs` accepts `--method MLR` and implements it in full (elastic
        net, collinearity grouping, group expansion). It is routed to R because
        R's MLR path is stochastic -- `sample(correlacionados, 1)` picks the
        surviving member of a collapsed clique -- so the port can only be
        measured inside R's own seed band, never equal to it. PLS1 has no such
        problem, which is why only PLS1 gets switched by default.
        """
        self.assertEqual(
            MOREServlet._resolveMOREBackend("MLR", R_SCRIPT, self.binary),
            ["Rscript", R_SCRIPT])

    def test_an_unrecognised_method_uses_r(self):
        """R owns the full method surface, so it is the safe default."""
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS2", R_SCRIPT, self.binary),
            ["Rscript", R_SCRIPT])

    def test_a_non_canonical_method_string_goes_to_r(self):
        """The match is exact on purpose.

        jobInstance.method comes from a form field, not a validated enum, and
        the port is stricter than R about it -- measured: `--method pls1` and
        `--method " PLS1 "` both exit with "must be PLS1 or MLR". Normalising
        here would route a string the port refuses away from the backend that
        might accept it, converting a slow analysis into a failed one.
        """
        for method in ("pls1", " PLS1 ", "Pls1"):
            self.assertEqual(
                MOREServlet._resolveMOREBackend(method, R_SCRIPT, self.binary),
                ["Rscript", R_SCRIPT], "method %r must go to R" % method)

    def test_a_missing_method_goes_to_r(self):
        """MOREJob defaults method to PLS1, but None must not crash routing."""
        self.assertEqual(
            MOREServlet._resolveMOREBackend(None, R_SCRIPT, self.binary),
            ["Rscript", R_SCRIPT])


class ConfigCompatibilityTest(unittest.TestCase):
    """The setting must be optional in serverconf.py.

    serverconf.py is gitignored and generated from example_serverconf.py by
    deploy/entrypoint.sh -- but only `if [ ! -f "${CONFIG_PATH}" ]`. An upgraded
    container therefore keeps the config it already has, which predates this
    setting. A hard `from src.conf.serverconf import MORE_RS_BINARY` would then
    raise at import time and take the whole servlet down, turning a new optional
    feature into an outage on every existing deployment.
    """

    def test_the_servlet_imports_when_serverconf_predates_the_setting(self):
        import importlib
        from src.conf import serverconf

        had = hasattr(serverconf, "MORE_RS_BINARY")
        saved = getattr(serverconf, "MORE_RS_BINARY", None)
        savedEnv = os.environ.get("PAINTOMICS_MORE_RS")
        try:
            if had:
                del serverconf.MORE_RS_BINARY
            os.environ["PAINTOMICS_MORE_RS"] = "/tmp/more-rs-from-env"
            reloaded = importlib.reload(MOREServlet)
            self.assertEqual(reloaded.MORE_RS_BINARY, "/tmp/more-rs-from-env",
                             "the servlet must fall back to the environment")
        finally:
            if had:
                serverconf.MORE_RS_BINARY = saved
            if savedEnv is None:
                os.environ.pop("PAINTOMICS_MORE_RS", None)
            else:
                os.environ["PAINTOMICS_MORE_RS"] = savedEnv
            importlib.reload(MOREServlet)

    def test_the_shipped_config_template_carries_the_setting(self):
        """A fresh container should get the setting without hand-editing."""
        template = os.path.join(
            os.path.dirname(__file__), "..", "resources", "example_serverconf.py")
        with open(template) as fh:
            body = fh.read()
        self.assertIn("MORE_RS_BINARY", body)
        self.assertIn("PAINTOMICS_MORE_RS", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
