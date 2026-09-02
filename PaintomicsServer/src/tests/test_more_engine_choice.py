#!/usr/bin/env python3
"""Cover for the three-way regulatory engine choice in MOREServlet.

What changed and why it needs its own file
------------------------------------------
`test_more_backend_selection` pins the *automatic* choice: with no engine named,
PLS1 goes to `more-rs` when one is installed and everything else goes to R. That
behaviour is unchanged and still pinned there.

This file pins what sits on top of it: the user can now name the engine, and the
server can now say which engines it is able to run. The catalogue is three
entries -- `rust-pls1` (the default), `r-pls1`, `r-mlr` -- and the three
properties worth guarding are:

* **An explicit choice beats the automatic one.** `r-pls1` exists precisely to
  be the slow reference; if it silently resolved to the port it would be a lie,
  and the runtime guard would cost the job on the port's constant -- roughly
  660x under -- and wave through a job it exists to refuse.
* **Availability is probed on the PACKAGES, not the interpreter.** The deployed
  image carries `/usr/bin/Rscript` and none of MORE, optparse, ropls or glmnet.
  A check built on `shutil.which("Rscript")` therefore passes there, concludes
  the R engines are available, and lets the job die deep in the run -- the exact
  failure the check exists to prevent, wearing the disguise of a working guard.
* **Refusal happens at submission, not in the dropdown.** Hiding an option is
  necessary and not sufficient: a stale client, a resubmitted job or a scripted
  POST all reach the servlet directly.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_engine_choice
"""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import MOREServlet
from src.classes.JobInstances.MOREJob import MOREJob

R_SCRIPT = "/opt/paintomics/src/common/bioscripts/runMORE.R"

ALL_INSTALLED = {"rscript": "/usr/bin/Rscript", "more": True,
                 "optparse": True, "error": ""}
# What the deploy image actually reports: R present, every package absent.
DRAGO = {"rscript": "/usr/bin/Rscript", "more": False, "optparse": False,
         "error": "there is no package called 'MORE'"}
NO_R = {"rscript": "", "more": False, "optparse": False,
        "error": "Rscript is not on PATH"}


class EngineIdTest(unittest.TestCase):
    """(method, engine) -> catalogue id, which is the whole wire contract."""

    def test_auto_reproduces_the_behaviour_that_predates_the_choice(self):
        """A client that names no engine must keep getting what it got."""
        self.assertEqual(MOREServlet.engineIdFor("PLS1", None), "rust-pls1")
        self.assertEqual(MOREServlet.engineIdFor("PLS1", "auto"), "rust-pls1")
        self.assertEqual(MOREServlet.engineIdFor("MLR", None), "r-mlr")

    def test_an_explicit_engine_is_honoured(self):
        self.assertEqual(MOREServlet.engineIdFor("PLS1", "r"), "r-pls1")
        self.assertEqual(MOREServlet.engineIdFor("PLS1", "rust"), "rust-pls1")

    def test_mlr_on_the_port_resolves_to_the_port(self):
        """There is no rust-MLR entry, and asking for one is not an error.

        The port reproduces R's RNG stream now -- R's Mersenne-Twister,
        `set.seed`'s scrambling and `R_unif_index`'s rejection sampling -- so
        the collinearity representatives that `sample()` picks match exactly and
        the catalogue can offer the pair. It is still opt-in rather than the
        default, because reproducing R's *draws* is not reproducing R's
        *rounding*; see `test_mlr_defaults_to_r_even_with_a_binary_installed`.
        """
        self.assertEqual(MOREServlet.engineIdFor("MLR", "rust"), "rust-mlr")

    def test_an_unknown_method_resolves_to_nothing_rather_than_something(self):
        """None is the answer that lets a caller tell "not offered" apart from
        "offered but unavailable"; inventing an id would collapse the two."""
        self.assertIsNone(MOREServlet.engineIdFor("PLS2", None))
        self.assertIsNone(MOREServlet.engineIdFor("", "rust"))

    def test_the_catalogue_ids_are_unique_and_the_default_is_one_of_them(self):
        ids = [entry["id"] for entry in MOREServlet.MORE_ENGINES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(MOREServlet.DEFAULT_MORE_ENGINE, ids)

    def test_every_catalogue_entry_resolves_back_to_itself(self):
        """The round trip the client depends on: it posts an id, the server
        derives (method, engine) from it, and that pair must name the same id
        again -- otherwise the job runs something other than what was picked."""
        for entry in MOREServlet.MORE_ENGINES:
            self.assertEqual(
                MOREServlet.engineIdFor(entry["method"], entry["engine"]),
                entry["id"], entry["id"])


class ResolveWithAnExplicitEngineTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="more_engine_")
        self.binary = os.path.join(self.tmp, "more-rs")
        with open(self.binary, "w") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.binary, os.stat(self.binary).st_mode | stat.S_IXUSR)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_asking_for_r_gets_r_even_though_the_binary_is_right_there(self):
        """The point of the r-pls1 option, and the one that silently breaks.

        `auto` would send this to the port. If the explicit choice did not win,
        the option would be indistinguishable from the default in everything
        except the label.
        """
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, self.binary,
                                            engine="r"),
            ["Rscript", R_SCRIPT])

    def test_asking_for_r_wins_over_discovery_too(self):
        with mock.patch.object(MOREServlet, "_discoverMoreRs",
                               return_value=self.binary):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, "", engine="r"),
                ["Rscript", R_SCRIPT])

    def test_asking_for_rust_gets_the_binary(self):
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, self.binary,
                                            engine="rust"),
            [self.binary])

    def test_asking_for_rust_where_there_is_none_still_runs_the_job(self):
        """Degrade to R rather than fail. The picker refuses this combination
        up front, so reaching here means a stale client or a scripted POST --
        which should get the reference answer slowly, not an error."""
        with mock.patch.object(MOREServlet, "_discoverMoreRs", return_value=""):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, "",
                                                engine="rust"),
                ["Rscript", R_SCRIPT])

    def test_asking_for_rust_for_mlr_runs_mlr_on_the_port(self):
        self.assertEqual(
            MOREServlet._resolveMOREBackend("MLR", R_SCRIPT, self.binary,
                                            engine="rust"),
            [self.binary])

    def test_mlr_defaults_to_r_even_with_a_binary_installed(self):
        """The invariant that protects numbers users have already seen.

        PLS1 goes to the port unasked because swapping it is invisible --
        byte-identical output. MLR does not: MORE runs glmnet at a tolerance
        where coordinate descent has not converged, and where permuting the
        design columns moves glmnet's own answer by 3.0e-03 relative, so a
        cross-validated (alpha, lambda) tie can fall either way and a few edges
        differ. A stored job, an older client and a scripted POST all arrive
        here with no engine or with `auto`, and every one of them must keep
        getting R.
        """
        for engine in (None, "", "auto", "AUTO"):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("MLR", R_SCRIPT, self.binary,
                                                engine=engine),
                ["Rscript", R_SCRIPT],
                "MLR with engine=%r must stay on R" % (engine,))

    def test_rust_mlr_falls_back_to_r_when_no_binary_is_installed(self):
        """Same rule as PLS1: a host without the port answers slowly, not with
        an error. `engineRefusal` is what turns this into a message; this is the
        belt to that's braces."""
        with mock.patch.object(MOREServlet, "_discoverMoreRs", return_value=""):
            self.assertEqual(
                MOREServlet._resolveMOREBackend("MLR", R_SCRIPT, "",
                                                engine="rust"),
                ["Rscript", R_SCRIPT])

    def test_the_off_switch_still_beats_an_explicit_rust_request(self):
        """`off` is the operator's decision and outranks the user's."""
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, "off",
                                            engine="rust"),
            ["Rscript", R_SCRIPT])

    def test_case_and_padding_do_not_change_the_engine(self):
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, self.binary,
                                            engine="  R  "),
            ["Rscript", R_SCRIPT])

    def test_no_engine_argument_leaves_the_old_behaviour_alone(self):
        """Regression guard for every existing caller."""
        self.assertEqual(
            MOREServlet._resolveMOREBackend("PLS1", R_SCRIPT, self.binary),
            [self.binary])
        self.assertEqual(
            MOREServlet._resolveMOREBackend("MLR", R_SCRIPT, self.binary),
            ["Rscript", R_SCRIPT])


class EngineForCostingTest(unittest.TestCase):
    """_engineFor is what the runtime guard costs a job with."""

    def test_the_r_option_is_costed_as_r(self):
        """The bug this exists to stop.

        `_engineFor(method)` resolved under `auto`, which was correct while the
        engine could not be chosen. Once it can, a user picking r-pls1 would be
        costed on the port's constant -- 0.00092 s/gene against 0.607 -- so a
        9,835-gene job is quoted at 9 seconds, the guard stays silent, and the
        job is killed at the 1800 s timeout having produced nothing.
        """
        with mock.patch.object(MOREServlet, "_discoverMoreRs",
                               return_value="/usr/local/bin/more-rs"):
            self.assertEqual(MOREServlet._engineFor("PLS1", "r"), "r")
            self.assertEqual(MOREServlet._engineFor("PLS1", "rust"), "rust")
            self.assertEqual(MOREServlet._engineFor("PLS1", None), "rust")
            self.assertEqual(MOREServlet._engineFor("MLR", None), "r")


class AvailabilityTest(unittest.TestCase):

    def setUp(self):
        MOREServlet._R_PROBE = None

    def tearDown(self):
        MOREServlet._R_PROBE = None

    def _describe(self, rProbe, binary):
        with mock.patch.object(MOREServlet, "probeR", return_value=rProbe), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value=binary):
            return MOREServlet.describeMOREBackends()

    def test_everything_installed_offers_all_four(self):
        report = self._describe(ALL_INSTALLED, "/usr/local/bin/more-rs")
        self.assertEqual([e["id"] for e in report["engines"] if e["available"]],
                         ["rust-pls1", "r-pls1", "r-mlr", "rust-mlr"])
        self.assertEqual(report["default"], "rust-pls1")

    def test_the_catalogue_covers_both_methods_on_both_engines(self):
        """A missing cell reads as "does not exist" rather than "not installed
        here", which is the whole reason unavailable entries stay listed."""
        pairs = {(e["method"], e["engine"]) for e in MOREServlet.MORE_ENGINES}
        self.assertEqual(pairs, {("PLS1", "r"), ("PLS1", "rust"),
                                 ("MLR", "r"), ("MLR", "rust")})

    def test_r_present_but_its_packages_absent_disables_both_r_engines(self):
        """The deploy image, exactly.

        Note *both*: it is easy to think only MLR is at risk, because MLR was
        the R-only method. R PLS1 is equally dead there, and a check that
        disabled MLR alone would leave a reference option that cannot run.

        Since `rust-mlr` exists this image can run MLR at all for the first
        time -- the static musl binary needs neither R nor the MORE package,
        both of which are absent there.
        """
        report = self._describe(DRAGO, "/opt/paintomics/more-rs")
        available = {e["id"]: e["available"] for e in report["engines"]}
        self.assertEqual(available,
                         {"rust-pls1": True, "r-pls1": False,
                          "r-mlr": False, "rust-mlr": True})
        self.assertEqual(report["default"], "rust-pls1")
        for entry in report["engines"]:
            if not entry["available"]:
                self.assertIn("MORE package", entry["unavailableReason"])

    def test_no_binary_falls_the_default_back_to_something_runnable(self):
        """The picker has to open on an option that works, not on the one we
        would have preferred."""
        report = self._describe(ALL_INSTALLED, "")
        self.assertFalse(report["engines"][0]["available"])
        self.assertEqual(report["default"], "r-pls1")
        self.assertTrue(report["anyAvailable"])

    def test_a_host_with_neither_reports_that_honestly(self):
        report = self._describe(NO_R, "")
        self.assertFalse(report["anyAvailable"])
        self.assertIsNone(report["default"])
        self.assertTrue(all(not e["available"] for e in report["engines"]))

    def test_optparse_alone_missing_is_named_as_such(self):
        """MORE does not import optparse; runMORE.R uses it for its own CLI, so
        it can be missing while MORE is fine. A message blaming MORE would send
        the operator to install the wrong thing."""
        probe = dict(ALL_INSTALLED, optparse=False)
        report = self._describe(probe, "/usr/local/bin/more-rs")
        reasons = [e["unavailableReason"] for e in report["engines"]
                   if not e["available"]]
        self.assertEqual(len(reasons), 2)
        for reason in reasons:
            self.assertIn("optparse", reason)


class ProbeTest(unittest.TestCase):

    def setUp(self):
        MOREServlet._R_PROBE = None

    def tearDown(self):
        MOREServlet._R_PROBE = None

    def test_the_probe_asks_about_packages_and_not_about_the_interpreter(self):
        """The whole point. `which("Rscript")` answers a different question and
        answers it wrongly on the host that matters."""
        self.assertIn("requireNamespace", MOREServlet._R_PROBE_SCRIPT)
        self.assertIn("MORE", MOREServlet._R_PROBE_SCRIPT)
        self.assertIn("optparse", MOREServlet._R_PROBE_SCRIPT)

    def test_the_probe_runs_once_and_is_then_remembered(self):
        """R startup is several hundred ms to a second and this sits on the
        request path; probing per submission would be felt."""
        calls = []

        class FakeCompleted(object):
            stdout = b"TRUE TRUE"
            stderr = b""

        def fakeRun(*args, **kwargs):
            calls.append(args)
            return FakeCompleted()

        with mock.patch.object(MOREServlet.shutil, "which",
                               return_value="/usr/bin/Rscript"), \
             mock.patch.object(MOREServlet.subprocess, "run", fakeRun):
            first = MOREServlet.probeR()
            second = MOREServlet.probeR()

        self.assertEqual(len(calls), 1)
        self.assertIs(first, second)
        self.assertTrue(first["more"])
        self.assertTrue(first["optparse"])

    def test_a_probe_that_cannot_run_reports_unavailable_rather_than_raising(self):
        """Refusing a job that would have worked is recoverable and explained;
        a traceback out of a route that only reports configuration is not."""
        def explode(*args, **kwargs):
            raise OSError("no such file")

        with mock.patch.object(MOREServlet.shutil, "which",
                               return_value="/usr/bin/Rscript"), \
             mock.patch.object(MOREServlet.subprocess, "run", explode):
            probe = MOREServlet.probeR(refresh=True)

        self.assertFalse(probe["more"])
        self.assertIn("no such file", probe["error"])

    def test_a_partial_answer_is_not_read_as_a_yes(self):
        """`cat` of two logicals gives "TRUE TRUE". Anything shorter means the
        probe did not complete, and must not be scored as success."""
        class Partial(object):
            stdout = b"TRUE"
            stderr = b"Error: object 'optparse' not found"

        with mock.patch.object(MOREServlet.shutil, "which",
                               return_value="/usr/bin/Rscript"), \
             mock.patch.object(MOREServlet.subprocess, "run",
                               lambda *a, **k: Partial()):
            probe = MOREServlet.probeR(refresh=True)

        self.assertTrue(probe["more"])
        self.assertFalse(probe["optparse"])


class RefusalTest(unittest.TestCase):

    def setUp(self):
        MOREServlet._R_PROBE = None

    def tearDown(self):
        MOREServlet._R_PROBE = None

    def test_an_available_engine_is_not_refused(self):
        with mock.patch.object(MOREServlet, "probeR", return_value=ALL_INSTALLED), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value="/x/more-rs"):
            self.assertIsNone(MOREServlet.engineRefusal("PLS1", "r"))
            self.assertIsNone(MOREServlet.engineRefusal("MLR", "r"))

    def test_an_unavailable_engine_is_refused_with_a_reason_and_an_alternative(self):
        with mock.patch.object(MOREServlet, "probeR", return_value=DRAGO), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value="/x/more-rs"):
            message = MOREServlet.engineRefusal("MLR", "r")

        self.assertIsNotNone(message)
        self.assertIn("MORE package", message)
        # Naming what CAN be run is the difference between a dead end and a
        # next step; a refusal with no alternative is a bug report.
        self.assertIn("Rust engine", message)

    def test_a_host_with_nothing_says_so_instead_of_offering_nothing(self):
        with mock.patch.object(MOREServlet, "probeR", return_value=NO_R), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value=""):
            message = MOREServlet.engineRefusal("PLS1", "rust")

        self.assertIn("administrator", message)

    def test_a_method_the_catalogue_does_not_cover_is_refused_by_name(self):
        self.assertIn("PLS2", MOREServlet.engineRefusal("PLS2", None))

    def test_naming_no_engine_falls_back_instead_of_being_refused(self):
        """A host with no more-rs must still accept a PLS1 job that named none.

        `auto` is what a client predating the picker, a resubmitted job and a
        scripted POST all send, and _resolveMOREBackend answers it by running
        PLS1 on R when there is no binary. engineRefusal used to resolve `auto`
        straight to rust-pls1 and then refuse it, so on such a host every one of
        those callers was turned away with the reference engine available -- the
        whole of test_more_servlet_step1's 18 broken tests, and a real refusal
        for real users, not only a test artefact.
        """
        with mock.patch.object(MOREServlet, "probeR", return_value=ALL_INSTALLED), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value=""):
            self.assertIsNone(MOREServlet.engineRefusal("PLS1", None))
            self.assertIsNone(MOREServlet.engineRefusal("PLS1", "auto"))
            self.assertIsNone(MOREServlet.engineRefusal("PLS1", ""))
            # The explicit ask is still refused: only "decide for me" may bend.
            self.assertIsNotNone(MOREServlet.engineRefusal("PLS1", "rust"))

    def test_naming_no_engine_is_still_refused_when_nothing_can_run_it(self):
        """Falling back needs somewhere to fall back to."""
        with mock.patch.object(MOREServlet, "probeR", return_value=NO_R), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value=""):
            message = MOREServlet.engineRefusal("PLS1", None)

        self.assertIsNotNone(message)
        self.assertIn("administrator", message)

    def test_naming_no_engine_for_mlr_is_refused_when_r_is_missing(self):
        """The fallback runs from the port to R, never the other way.

        A host with a more-rs binary and no R: `auto` PLS1 runs on the port,
        so it is accepted. `auto` MLR points at R, and _resolveMOREBackend will
        NOT swap an unnamed MLR onto the port (its output is not byte-identical
        to R's), so accepting it hands the job to an Rscript that is not there.
        The first version of the fallback accepted it because "some engine for
        the method" -- rust-mlr -- was available; the review of pull request
        #124 read the router and caught it. Naming the port is still fine.
        """
        with mock.patch.object(MOREServlet, "probeR", return_value=NO_R), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value="/x/more-rs"):
            self.assertIsNone(MOREServlet.engineRefusal("PLS1", None))
            self.assertIsNone(MOREServlet.engineRefusal("MLR", "rust"))
            message = MOREServlet.engineRefusal("MLR", None)

        self.assertIsNotNone(message)
        self.assertIn("no R installation", message)
        # The way out is to ask for the port by name, so the refusal says so.
        self.assertIn("MLR \u2014 Rust engine", message)

    def test_naming_no_engine_is_accepted_exactly_when_the_routers_pick_can_run(self):
        """The invariant behind the two tests above, over every host state.

        engineRefusal and _resolveMOREBackend are two functions with one
        decision between them: a job that is not refused must land on an
        engine this host can run. So for each method and each combination of
        {binary, no binary} x {R, no R}, ask the router where `auto` goes, look
        that engine up in the availability report, and check the refusal
        agrees. A host with a real more-rs on PATH must not leak into the
        no-binary rows, hence the discovery mock.
        """
        tmp = tempfile.mkdtemp(prefix="more_engine_")
        binary = os.path.join(tmp, "more-rs")
        with open(binary, "w") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(binary, os.stat(binary).st_mode | stat.S_IXUSR)
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)

        for probe in (ALL_INSTALLED, NO_R):
            for hostBinary in (binary, ""):
                for method in ("PLS1", "MLR"):
                    with mock.patch.object(MOREServlet, "probeR", return_value=probe), \
                         mock.patch.object(MOREServlet, "_rustBinary",
                                           return_value=hostBinary), \
                         mock.patch.object(MOREServlet, "_discoverMoreRs",
                                           return_value=hostBinary):
                        argv = MOREServlet._resolveMOREBackend(
                            method, R_SCRIPT, binaryPath=hostBinary, engine=None)
                        picked = MOREServlet.engineIdFor(
                            method, "r" if argv[0] == "Rscript" else "rust")
                        canRun = any(
                            e["id"] == picked and e["available"]
                            for e in MOREServlet.describeMOREBackends()["engines"])
                        refusal = MOREServlet.engineRefusal(method, None)
                    self.assertEqual(
                        refusal is None, canRun,
                        "%s/auto with R=%s binary=%s: router picks %s (%s), "
                        "refusal says %r" % (
                            method, bool(probe["rscript"]), bool(hostBinary),
                            picked, "runnable" if canRun else "NOT runnable",
                            refusal))


class ApplyEngineChoiceTest(unittest.TestCase):
    """What STEP1 does with the form field."""

    def setUp(self):
        MOREServlet._R_PROBE = None
        self.job = MOREJob("job1", "user1", "/tmp")

    def tearDown(self):
        MOREServlet._R_PROBE = None

    def _apply(self, formFields, rProbe=ALL_INSTALLED, binary="/x/more-rs"):
        with mock.patch.object(MOREServlet, "probeR", return_value=rProbe), \
             mock.patch.object(MOREServlet, "_rustBinary", return_value=binary):
            return MOREServlet._applyEngineChoice(self.job, formFields)

    def test_a_new_job_defaults_to_auto(self):
        """MOREJob's own default, so a job built and never submitted through
        the form still resolves rather than carrying None."""
        self.assertEqual(MOREJob("j", "u", "/tmp").engine, "auto")

    def test_the_picked_id_sets_both_method_and_engine(self):
        self.assertIsNone(self._apply({"more_engine": "r-mlr"}))
        self.assertEqual(self.job.method, "MLR")
        self.assertEqual(self.job.engine, "r")

    def test_r_pls1_sets_pls1_on_r(self):
        self.assertIsNone(self._apply({"more_engine": "r-pls1"}))
        self.assertEqual(self.job.method, "PLS1")
        self.assertEqual(self.job.engine, "r")

    def test_no_engine_field_leaves_the_method_the_form_already_set(self):
        """Backward compatibility with a client that posts more_method only."""
        self.job.method = "MLR"
        self.assertIsNone(self._apply({}))
        self.assertEqual(self.job.method, "MLR")
        self.assertEqual(self.job.engine, "auto")

    def test_an_unknown_id_is_ignored_rather_than_obeyed(self):
        self.job.method = "PLS1"
        self._apply({"more_engine": "quantum-pls"})
        self.assertEqual(self.job.engine, "auto")
        self.assertEqual(self.job.method, "PLS1")

    def test_an_unavailable_engine_comes_back_as_a_refusal(self):
        message = self._apply({"more_engine": "r-mlr"}, rProbe=DRAGO)
        self.assertIsNotNone(message)
        self.assertIn("MORE package", message)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
