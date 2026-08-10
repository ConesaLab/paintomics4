#!/usr/bin/env python3
"""Static checks on the client wiring for example datasets.

These are string assertions over JavaScript, which is a blunt instrument, and
the suite already carries a few (test_index_html_revalidates,
test_versioned_assets_are_bumped) for the same reason: the alternative is no
coverage at all, and each of these guards a failure that is silent.

The one that matters most is the pipeline guard in step1OnFormSubmitHandler.
Loading a MORE, region or miRNA example runs a conversion step first, which
writes real files into the job's own directory; step 1 must then be an ordinary
upload of that output. Sending it to the example endpoint instead makes the
server re-read the dataset's raw inputs and throw the conversion away. Observed
before the guard existed:

    MORE_STEP1 - EXAMPLE 'regulatory-more' REGISTERED (2 regulatory omics)
    MORE: Analysis complete.
    POST /pa_step1/example/regulatory-more
    STEP1 - EXAMPLE MODE SELECTED (scenario: regulatory-more)
    STEP1 - EXAMPLE 'regulatory-more' REGISTERED (2 omics)   <-- raw inputs

and afterwards:

    POST /pa_step1
    STEP1 - FILE UPLOADING REQUEST RECEIVED                  <-- MORE's output

Both runs "succeed". Only the second analyses what MORE computed.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_mode_client_wiring
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

CLIENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "PaintomicsClient", "public_html"))

STEP1_VIEWS = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews",
                           "PA_Step1Views.js")
JOB_CONTROLLER = os.path.join(CLIENT, "app", "controller", "JobController.js")
SERVER_CONFIG = os.path.join(CLIENT, "resources", "ServerConfiguration.js")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class ClientFilesExistTest(unittest.TestCase):
    """Premise check: the assertions below are reading the files they name."""

    def test_the_three_client_files_are_where_this_test_thinks(self):
        for path in (STEP1_VIEWS, JOB_CONTROLLER, SERVER_CONFIG):
            self.assertTrue(os.path.isfile(path), "%s is missing" % path)


class PipelineGuardTest(unittest.TestCase):

    def test_step1_only_uses_the_example_endpoint_for_pathway_acquisition(self):
        source = read(JOB_CONTROLLER)
        self.assertIn("getExamplePipeline()", source,
                      "step1OnFormSubmitHandler no longer consults the example "
                      "pipeline, so a MORE/region/miRNA example would re-enter "
                      "example mode and discard the conversion output")
        self.assertIn('=== "pathway-acquisition"', source)

    def test_the_job_view_exposes_the_pipeline(self):
        self.assertIn("this.getExamplePipeline = function()", read(STEP1_VIEWS))

    def test_the_scenario_id_is_appended_to_every_example_url(self):
        """All four entry points must carry the chosen dataset, not just one."""
        source = read(JOB_CONTROLLER)
        self.assertIn("function withExampleScenario(", source)
        for constant in ("SERVER_URL_PA_EXAMPLE_STEP1",
                         "SERVER_URL_DM_EXAMPLE_FROMBED2GENES",
                         "SERVER_URL_DM_EXAMPLE_FROMMIRNA2GENES",
                         "SERVER_URL_DM_EXAMPLE_FROMMORE2GENES"):
            self.assertRegex(
                source, r"withExampleScenario\(\s*" + constant,
                "%s is not passed through withExampleScenario, so a chosen "
                "dataset would be ignored for that entry point" % constant)


class NoHardcodedExamplePathsTest(unittest.TestCase):
    """Filenames belong to the manifest, not to the form.

    Every literal here was wrong at some point while looking plausible:
    `example/mirna_unmapped.tab` (the file ships as `..._values.tab`),
    `example/undefined_example.tab` (built from a type the panel does not have),
    and `example/<type>_example.tab` (a name that has never existed in any
    release). A user who copied one got a file the server does not recognise.
    """

    def test_no_panel_hardcodes_an_example_filename(self):
        source = read(STEP1_VIEWS)
        offenders = re.findall(r'setValue\(\s*"example/[^"]*"', source)
        self.assertEqual(
            offenders, [],
            "hardcoded example paths are back in PA_Step1Views.js: %s"
            % offenders)

    def test_example_labels_go_through_the_shared_helper(self):
        source = read(STEP1_VIEWS)
        self.assertIn("function setExampleLabel(", source)
        # The helper passes an explicit origin so the widget does not render
        # "[MyData]/..." in front of a path that is not in the user's data.
        self.assertIn('field.setValue("[example dataset] " + text, "example");',
                      source)


class CatalogueEndpointTest(unittest.TestCase):

    def test_the_client_knows_the_catalogue_url(self):
        self.assertIn("SERVER_URL_EXAMPLE_DATASETS", read(SERVER_CONFIG))
        self.assertIn("SERVER_URL_EXAMPLE_DATASETS", read(STEP1_VIEWS))

    def test_the_picker_does_not_filter_out_the_other_pipelines(self):
        """MORE's example is only reachable because the picker lists it.

        MORE shipped with no example for its whole existence; a filter that
        quietly excluded non-pathway pipelines would restore that state without
        removing any code.
        """
        source = read(STEP1_VIEWS)
        self.assertNotIn('return scenario.pipeline === "pathway-acquisition";',
                         source)
        for pipeline in ("regions2genes", "mirna2genes", "more"):
            self.assertIn('"%s"' % pipeline, source,
                          "the picker does not mention the %s pipeline"
                          % pipeline)

    def test_every_pipeline_maps_to_a_panel_type(self):
        source = read(STEP1_VIEWS)
        self.assertIn("EXAMPLE_PANEL_FOR_PIPELINE", source)
        for panelType in ("bedbasedomic", "mirnabasedomic", "moreanalysis"):
            self.assertIn('"%s"' % panelType, source)


class MorePanelExampleTest(unittest.TestCase):
    """The MORE panel had no setExampleMode at all until this work."""

    def test_more_panel_has_an_example_mode(self):
        source = read(STEP1_VIEWS)
        morePanel = source[source.index("function MORESubmittingPanel("):]
        self.assertIn("this.setExampleMode = function(scenario)", morePanel,
                      "MORESubmittingPanel lost its setExampleMode, so the MORE "
                      "example would load with empty fields")

    def test_more_example_fills_the_required_omic_name(self):
        """`allowBlank: false` on that field; empty means checkForm() refuses.

        The example would load and then silently decline to run.
        """
        source = read(STEP1_VIEWS)
        morePanel = source[source.index("function MORESubmittingPanel("):]
        self.assertIn('component.queryById("omicNameField")', morePanel)


def exampleLoaderBody(source):
    """The body of setExampleModeHandler, so assertions can be scoped to it.

    Both delimiters are functions defined in this file's own object literal;
    an IndexError here means one was renamed and the assertion below is no
    longer reading what it claims to read.
    """
    start = source.index("this.setExampleModeHandler = function(scenario)")
    end = source.index("this.lockFormForExample = function(", start)
    return source[start:end]


class ExampleModeConsentTest(unittest.TestCase):
    """Loading an example must not answer the AI consent question for the user.

    The checkbox reads "sends analysis summaries to external AI service", and
    the server takes it straight off the form on the example branch too
    (PathwayAcquisitionServlet: setAIConsent(formFields.get("aiConsent",
    "false"))). Measured before this guard: unchecked on a fresh page, checked
    after clicking Load example, for every dataset -- so every example run
    called out to a third-party LLM on a permission nobody gave.
    """

    def test_the_example_loader_does_not_touch_the_ai_consent_checkbox(self):
        body = exampleLoaderBody(read(STEP1_VIEWS))
        self.assertNotIn(
            "[name=aiConsent]", body,
            "setExampleModeHandler reaches for the AI consent checkbox again; "
            "loading an example is not consent to transmit to a third party")

    def test_the_experiment_design_prefill_is_kept(self):
        """The other prefill is a visible, editable text field -- not a permission."""
        body = exampleLoaderBody(read(STEP1_VIEWS))
        self.assertIn("[name=experimentDesign]", body)
        self.assertIn("exampleExperimentDesignFor(scenario)", body)


class ExamplePanelClearOutTest(unittest.TestCase):
    """"=" is an exact match on the whole cls string, "~=" is per class name.

    Only the plain omic panel declares cls:"omicbox" alone. The region
    ("omicbox regionBasedOmic"), miRNA ("omicbox miRNABasedOmic") and MORE
    ("omicbox moreBasedOmic") panels are invisible to "[cls=omicbox]", so they
    survived the clear-out and were still in the form -- and still submitted --
    when the next example was loaded on top.
    """

    def test_the_clear_out_uses_the_whitespace_list_operator(self):
        source = read(STEP1_VIEWS)
        self.assertIn('query("[cls~=omicbox]")', source)
        self.assertNotIn(
            'query("[cls=omicbox]")', source,
            "the exact-match selector is back, so a MORE/region/miRNA panel "
            "would survive into the next example")

    def test_every_panel_type_the_selector_must_reach_still_declares_omicbox(self):
        """Premise check: "~=" only helps while the class list starts with it."""
        source = read(STEP1_VIEWS)
        for cls in ('cls: "omicbox regionBasedOmic"',
                    'cls: "omicbox miRNABasedOmic"',
                    'cls: "omicbox " + this.class'):
            self.assertIn(cls, source,
                          "%s is gone; the clear-out assertion above no longer "
                          "covers that panel" % cls)


class ExampleButtonStaysAvailableTest(unittest.TestCase):
    """Switching datasets used to require throwing the whole job away."""

    def test_the_toolbar_button_is_not_hidden_by_the_example_loader(self):
        source = read(STEP1_VIEWS)
        self.assertNotIn('$("#exampleButton").css("display", "none")', source)
        self.assertNotIn('$("#exampleButton").hide()', source)

    def test_the_button_is_relabelled_rather_than_removed(self):
        self.assertIn("Load another example", read(STEP1_VIEWS))


class ExampleFormIsReadOnlyTest(unittest.TestCase):
    """The form is decorative in example mode; it has to look decorative.

    Measured: loaded multiomics-integration, deleted the Metabolomics panel,
    ran -- and the job still contained Metabolomics, byte-identical to an
    untouched run, with the progress dialog announcing "mapping Metabolomics".
    """

    def test_the_lock_exists_and_is_called_when_an_example_loads(self):
        source = read(STEP1_VIEWS)
        self.assertIn("this.lockFormForExample = function(", source)
        self.assertIn("this.lockFormForExample(pipeline);", exampleLoaderBody(source))

    def test_the_lock_uses_read_only_and_not_disabled(self):
        """A disabled field returns null from getSubmitData() and never posts.

        The chained pipelines (regions2genes, mirna2genes, more) submit this
        form for real once their conversion has run, so disabling the database
        checkboxes there would silently drop Reactome/MapMan from the job.
        """
        source = read(STEP1_VIEWS)
        lock = source[source.index("this.lockFormForExample = function("):]
        lock = lock[:lock.index("this.submitFormHandler = function()")]
        self.assertIn("setReadOnly(true)", lock)
        self.assertNotIn("setDisabled(true)", lock)

    def test_the_database_checkboxes_are_locked_too(self):
        source = read(STEP1_VIEWS)
        self.assertIn('itemId: "databasesCheckboxGroup"', source)
        lock = source[source.index("this.lockFormForExample = function("):]
        self.assertIn('queryById("databasesCheckboxGroup")', lock)

    def test_the_user_is_told_the_dataset_is_fixed_and_how_to_get_out(self):
        source = read(STEP1_VIEWS)
        lock = source[source.index("this.lockFormForExample = function("):]
        lock = lock[:lock.index("this.submitFormHandler = function()")]
        self.assertIn("This example dataset is fixed.", lock)
        self.assertIn("Reset", lock,
                      "the note must name the way back to an upload form")


class RegionDefaultsMatchTheServerTest(unittest.TestCase):
    """The client shipped 50 where every other statement of the default says 90.

    Bed2GeneJob.py:50 (`self.geneAreaPercentage = 90`), Bed2GenesServlet.py:147
    (`formFields.get(namePrefix + "_geneAreaPercentage", 90)`) and the field's
    own helpTip all say 90. The field posts on every request, so the servlet's
    fallback never applied and the documented default was never used.
    """

    def test_the_overlapped_gene_area_default_is_90(self):
        source = read(STEP1_VIEWS)
        start = source.index('itemId: "geneAreaPercentageField"')
        block = source[start:start + 900]
        self.assertIn("value: 90,", block)
        self.assertNotIn("value: 50,", block[:block.index("helpTip")])

    def test_the_helptip_still_documents_90(self):
        """If the documented default moves, the value above must move with it."""
        source = read(STEP1_VIEWS)
        start = source.index('itemId: "geneAreaPercentageField"')
        block = source[start:start + 900]
        self.assertIn("Default: 90 (90%)", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
