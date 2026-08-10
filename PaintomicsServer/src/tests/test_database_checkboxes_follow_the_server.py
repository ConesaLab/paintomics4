#!/usr/bin/env python3
"""Step 1's database checkboxes must be drawn from what the server installed.

The behaviour these guard
-------------------------
There is one rule, and it has two halves:

  * a pathway database installed for the chosen organism is **ticked**, on
    every host, including when an example dataset is loaded;
  * a database that is not installed **cannot be ticked**.

Both halves were wrong before, in opposite directions. All three boxes were
always offered, and `PathwayAcquisitionServlet` then intersected the submission
with the organism's databases, so MapMan for mouse or Reactome for tomato was
accepted by the form and dropped without a word. Meanwhile Reactome was
pre-ticked when `window.location.hostname` was localhost and unticked
everywhere else -- the box tracked who was looking rather than what was
installed, so a deployment with Reactome fully installed offered it unticked.

Why source assertions
---------------------
Same reason as test_example_mode_client_wiring: the client has no test harness,
and these are contracts between two files that are edited months apart. The
behaviour itself was verified in a browser -- mmu offers Reactome ticked with
MapMan greyed out, ath the reverse, an uninstalled organism neither -- and
these keep the wiring that produced it from being quietly unpicked.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_database_checkboxes_follow_the_server
"""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

CLIENT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../PaintomicsClient/public_html"))
SERVER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

STEP1_VIEWS = os.path.join(
    CLIENT_ROOT, "app/view/PathwayAcquisitionViews/PA_Step1Views.js")
SERVER_CONFIG = os.path.join(CLIENT_ROOT, "resources/ServerConfiguration.js")
SERVER_MAIN = os.path.join(SERVER_ROOT, "src/paintomicsserver.py")
SERVLET = os.path.join(SERVER_ROOT, "src/servlets/PathwayAcquisitionServlet.py")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def functionBody(source, opening, following):
    """The text between two known markers, so an assertion cannot drift out."""
    start = source.index(opening)
    return source[start:source.index(following, start)]


class CheckboxDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.source = read(STEP1_VIEWS)

    def test_the_optional_boxes_start_unticked_and_disabled(self):
        """Before an organism is chosen, nothing optional is knowable yet.

        Any other starting state is a claim about databases the form has not
        asked the server about.
        """
        for database in ("MapMan", "Reactome"):
            marker = "inputValue: '%s'" % database
            block = self.source[self.source.index(marker):]
            block = block[:block.index("},")]
            self.assertIn("checked: false", block,
                          "%s must not start ticked" % database)
            self.assertIn("disabled: true", block,
                          "%s must not start selectable" % database)

    def test_both_optional_boxes_are_addressable(self):
        """applyDatabaseAvailability finds them by id; MapMan never had one."""
        for itemId in ("mapmanDB", "reactomeDB"):
            self.assertIn("itemId: '%s'" % itemId, self.source)

    def test_kegg_stays_required(self):
        block = self.source[self.source.index("inputValue: 'KEGG'"):]
        block = block[:block.index("},")]
        self.assertIn("checked: true", block)
        self.assertIn("disabled: true", block)


class AvailabilityWiringTest(unittest.TestCase):
    def setUp(self):
        self.source = read(STEP1_VIEWS)

    def test_the_organism_combo_reapplies_availability(self):
        """Without this the boxes are computed once and then lie."""
        block = self.source[self.source.index('itemId: "speciesCombobox"'):]
        block = block[:block.index("store: Ext.create")]
        self.assertIn("applyDatabaseAvailability", block)
        self.assertIn("change:", block,
                      "setValue() fires change and not select, and the example "
                      "loader sets the organism that way")

    def test_availability_both_ticks_and_locks(self):
        body = functionBody(self.source,
                            "this.applyDatabaseAvailability = function(",
                            "this.describeDatabaseAvailability = function(")
        self.assertIn("box.setValue(available)", body)
        self.assertIn("box.setDisabled(!available)", body)

    def test_the_value_is_set_before_the_box_is_disabled(self):
        """A disabled checkbox is excluded from getSubmitData().

        Disabling first and then setting the value would leave a box that reads
        as selected and can never be posted -- the exact confusion this change
        exists to remove, reintroduced one line later.
        """
        body = functionBody(self.source,
                            "this.applyDatabaseAvailability = function(",
                            "this.describeDatabaseAvailability = function(")
        self.assertLess(body.index("box.setValue(available)"),
                        body.index("box.setDisabled(!available)"))

    def test_an_unreadable_map_offers_everything(self):
        """Degrade to the old behaviour, never to an unusable step 1."""
        body = functionBody(self.source,
                            "function getInstalledDatabasesFor(",
                            "function PA_Step1JobView(")
        self.assertIn("if (!ORGANISM_DATABASES_READ) { return null; }", body)

    def test_an_organism_absent_from_a_readable_map_gets_kegg_only(self):
        """species.json lists what DBManager installed when it last ran.

        It can name an organism with no MongoDB database at all, and offering
        MapMan or Reactome for one of those is the same empty promise as
        before. "Missing entry" and "unreadable map" are opposite answers.
        """
        body = functionBody(self.source,
                            "function getInstalledDatabasesFor(",
                            "function PA_Step1JobView(")
        self.assertIn('return (installed && installed.length) ? installed : ["KEGG"];',
                      body)

    def test_the_map_is_fetched_once(self):
        body = functionBody(self.source, "function loadOrganismDatabases(",
                            "function getInstalledDatabasesFor(")
        self.assertIn("if (ORGANISM_DATABASES_REQUEST === null)", body)
        self.assertIn("SERVER_URL_GET_ORGANISM_DATABASES", body)

    def test_the_fetch_promise_always_resolves(self):
        """A .then() failure filter recovers the chain in jQuery 3 and not in 1 or 2.

        This file is loaded next to a jquery-migrate shim; a promise that stops
        resolving would leave every optional database disabled for good.
        """
        body = functionBody(self.source, "function loadOrganismDatabases(",
                            "function getInstalledDatabasesFor(")
        self.assertIn(".always(function() { ready.resolve(ORGANISM_DATABASES); });",
                      body)


class ExampleModeTest(unittest.TestCase):
    def setUp(self):
        self.source = read(STEP1_VIEWS)

    def test_the_example_loader_does_not_tick_from_the_manifest(self):
        """The manifest cannot know what the host running it installed.

        Five of the seven bundled scenarios declare KEGG alone while every one
        of them is mmu, an organism that ships with Reactome, so honouring the
        manifest ran the example against half the pathways the same files reach
        as an upload -- measured as 364 rather than 878 for
        gene-single-condition.
        """
        body = functionBody(self.source, "this.setExampleModeHandler = function(",
                            "this.applyDatabaseAvailability = function(")
        self.assertNotIn("scenario.databases", body)
        self.assertNotIn("queryById('reactomeDB')", body)

    def test_the_about_dialog_reports_the_applied_databases(self):
        """It printed the manifest's list, which would now understate the run."""
        body = functionBody(self.source, "this.setExampleModeHandler = function(",
                            "this.applyDatabaseAvailability = function(")
        self.assertIn("this.applyDatabaseAvailability(function(databases) {", body)
        self.assertIn("databases.join(', ')", body)


class NoHostnameGatingTest(unittest.TestCase):
    def test_the_reactome_default_no_longer_depends_on_the_hostname(self):
        """Whether Reactome is installed is not a fact about who is looking."""
        for path in (STEP1_VIEWS, SERVER_CONFIG):
            self.assertNotIn("DEFAULT_REACTOME_ENABLED = ", read(path))
            self.assertNotIn("&& DEFAULT_REACTOME_ENABLED", read(path))

    def test_the_ai_consent_default_is_untouched(self):
        """That one IS about who is looking: a pre-ticked consent is not consent."""
        config = read(SERVER_CONFIG)
        self.assertIn("DEFAULT_AI_CONSENT_ENABLED = IS_LOCAL_INSTANCE;", config)


class ServerContractTest(unittest.TestCase):
    def test_the_endpoint_the_client_reads_exists(self):
        url = re.search(r'SERVER_URL_GET_ORGANISM_DATABASES = SERVER_URL \+ "([^"]+)"',
                        read(SERVER_CONFIG))
        self.assertIsNotNone(url, "the client must declare the endpoint's URL")
        self.assertIn("'/%s'" % url.group(1), read(SERVER_MAIN),
                      "and paintomicsserver.py must route it")

    def test_the_form_and_the_job_share_one_rule(self):
        """The offer and the filter must not be able to drift apart.

        The servlet used to spell the filter out inline; the form had no idea
        what it was. Both now call resolveDatabases, so a database that survives
        the form survives the job.
        """
        servlet = read(SERVLET)
        self.assertIn("DatabaseAvailability.resolveDatabases(specie, databases)",
                      servlet)
        self.assertNotIn("dicDatabases", servlet,
                         "the inline copy of the rule must be gone, not duplicated")

    def test_an_example_job_resolves_its_own_databases(self):
        servlet = read(SERVLET)
        self.assertIn(
            "DatabaseAvailability.resolveDatabases(jobInstance.getOrganism())",
            servlet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
