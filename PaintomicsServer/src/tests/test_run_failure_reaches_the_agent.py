#!/usr/bin/env python3
"""A failure at run time must be able to reach the agent, with the whole job.

The behaviour this guards
-------------------------
The offer to hand a refused file to the AI agent existed, and was keyed to one
servlet's wording:

    if (text.indexOf("Errors detected while processing") === -1) return;

Every other failure says something else, and the ones that reach a user with
real data are the analysis-stage ones. So a user watched a MORE run fail with
the agent one click away and never offered it. Same shape as the rest of this
family: matching on a STRING instead of on the situation.

Worse, the error that prompted this names no file at all --

    MORE ERROR: No common sample names across input files.
    Target samples: DSSmEVs_vs_DSS
    Condition rows: 1-C1, 2-C2, 3-C3, ...
    miRNA-Seq_data samples: DSS_SDmEV_vs_DSS

-- only sample names and an omic. `miRNA-Seq_data` is what the user typed into
Omic Name, so the card is identifiable even when the file is not.

And the fault is not IN any one file. Each is individually valid; the format
check passes all of them. They are wrong TOGETHER. A per-file agent re-reads a
valid file and finds nothing, so it is now given a one-line summary of every
other file in the job -- headers only, never the measurements.

That cross-file context is powerful and dangerous in equal measure. Measured,
the first time it ran: given the siblings, the agent renamed a column so the
two VALUES files agreed with each other, ignored the design file, and reported
success -- a job that would have failed again in the same place. So the design
file is named as the authority, and an irreconcilable case is routed to the
ask channel rather than to a conversion. With that, on the same data, the agent
stops and offers "Provide per-sample expression values", "Use the contrast
as-is and adjust the design (not recommended)", "Cancel this analysis".

Usage:
    cd PaintomicsServer
    python -m src.tests.test_run_failure_reaches_the_agent
"""
import io
import os
import re
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FORMAT_DIR = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                          "PathwayAcquisitionViews", "InputFormat")
PANEL = os.path.join(FORMAT_DIR, "format-panel.js")
DRAWER = os.path.join(FORMAT_DIR, "convert-drawer.js")

# The error the user actually saw, verbatim.
MORE_ERROR = (
    "1 file(s) could not be prepared. miRNA-Seq data: RuntimeError: AT "
    "MOREServlet.py: fromMOREtoGenes_STEP2. The MORE analysis failed "
    "(more-rs backend). MORE ERROR: No common sample names across input files. "
    "Target samples: DSSmEVs_vs_DSS Condition rows: 1-C1, 2-C2, 3-C3, ... "
    "miRNA-Seq_data samples: DSS_SDmEV_vs_DSS"
)


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def uncommented(source):
    return re.sub(r"/\*.*?\*/", "", source, flags=re.S)


class RunFailureReachesTheAgentTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.panel = read(PANEL)
        cls.drawer = read(DRAWER)
        cls.panel_code = uncommented(cls.panel)
        cls.drawer_code = uncommented(cls.drawer)

    # -- the offer is no longer tied to one servlet's wording --------------

    def test_the_hard_coded_phrase_is_gone(self):
        """It gated the offer on one message out of every message we send."""
        self.assertNotIn('indexOf("Errors detected while processing")',
                         self.panel_code)

    def test_a_file_is_found_by_name_anywhere_in_the_message(self):
        hook = self.panel_code[self.panel_code.index("function attachDialogFix"):]
        self.assertIn("pickedFileMatching", hook)
        self.assertIn("tab|txt|csv", hook)

    def test_an_omic_is_found_when_no_file_is_named(self):
        """The reported error names sample names and an omic, and no file."""
        self.assertIn("function pickedFileForOmicNamedIn", self.panel_code)
        self.assertIn("pickedFileForOmicNamedIn(text)", self.panel_code)
        # The regression that made the first attempt match nothing at all:
        # ComponentQuery has no CSS class selector.
        self.assertNotIn('up(".omicbox")', self.panel_code)
        self.assertIn('up("[cls~=omicbox]")', self.panel_code)

    def test_the_reported_error_names_no_file_but_does_name_the_omic(self):
        """The premise of the fallback, asserted so it cannot rot silently."""
        names = re.findall(r"[\w./\\-]+\.(?:tab|txt|csv|tsv)\b", MORE_ERROR)
        self.assertEqual(names, [], "this error names a file after all")
        self.assertIn("miRNA-Seq_data", MORE_ERROR)

    def test_the_omic_must_be_named_as_a_subject_not_mentioned_in_prose(self):
        """Reported as "why do these two buttons always exist".

        Matching an omic NAME anywhere in the text is far too loose to stand on
        its own -- omic names are ordinary words. The form's own refusal,
        "Please provide at least: Gene expression /Metabolomics /Proteomics
        data", contains "Gene expression", so a card carrying the default name
        matched it and both buttons appeared on a dialog that names no file and
        reports no file problem at all.

        A failure that is ABOUT an omic writes it as a label -- the preparation
        dialog builds "<omic>: <what the server said>" -- and prose does not put
        a colon there.

        Measured in Chrome with a card named "Gene expression" holding
        myvalues.tab, after the change:

            form: no data (names no file)          no buttons
            form: field required                   no buttons
            session expired                        no buttons
            omic mentioned in prose                no buttons
            names the picked file                  Check / Ask
            "Gene expression: MORE ERROR: ..."     Check / Ask
        """
        matcher = self.panel_code[
            self.panel_code.index("function pickedFileForOmicNamedIn"):]
        matcher = matcher[:matcher.index("function pickedFileMatching")]
        self.assertIn('.toLowerCase() + ":"', matcher,
                      "a bare omic name is not evidence that a file failed")

    def test_both_offers_are_made_and_they_differ(self):
        """Re-checking repairs mechanically; the agent can be told what broke."""
        self.assertIn("Check this file again", self.panel_code)
        self.assertIn("Ask the PaintOmics AI agent", self.panel_code)

    # -- the agent is given the job, not one file --------------------------

    def test_the_other_files_are_summarised_for_the_agent(self):
        self.assertIn("function siblingSummaries", self.panel_code)
        self.assertIn("function siblingBrief", self.panel_code)
        summaries = self.panel_code[self.panel_code.index("function siblingSummaries"):]
        summaries = summaries[:summaries.index("function siblingBrief")]
        self.assertIn("roleForField(field)", summaries,
                      "every role must be summarised, not just values")
        self.assertIn("file.slice(0, 65536)", summaries,
                      "headers only -- the measurements stay in the browser")

    def test_the_summary_is_gathered_before_the_dialog_closes(self):
        """Closing it first would leave nothing to read the files from."""
        hook = self.panel_code[self.panel_code.index("function attachDialogFix"):]
        gather = hook.index("siblingSummaries(picked.input)")
        close = hook.index("closeButton.click()", gather)
        self.assertLess(gather, close)

    def test_the_server_s_words_and_the_siblings_both_reach_the_agent(self):
        self.assertIn("__paServerSaid", self.panel_code)
        self.assertIn("__paSiblings", self.panel_code)
        self.assertIn("input.__paServerSaid", self.drawer_code)
        self.assertIn("input.__paSiblings", self.drawer_code)

    # -- and the guard that stops a confident wrong answer -----------------

    def test_the_design_file_is_named_as_the_authority(self):
        """Without this the agent aligned two values files and ignored design."""
        self.assertIn("AUTHORITY on", self.drawer_code)
        self.assertIn("Never rename a column to make two", self.drawer_code)

    def test_an_irreconcilable_job_is_asked_about_not_converted(self):
        """The runtime has no "explain, do not convert" outcome; ask is the one
        channel that carries an explanation, and it is already used for the
        duplicate-identifier question."""
        self.assertIn("ASK THE USER rather", self.drawer_code)
        self.assertIn("one column per sample", self.drawer_code)

    def test_the_agent_is_told_it_can_rewrite_only_the_file_it_holds(self):
        """Reported as "the AI said it fixed the problem and it fails again".

        The sandbox receives exactly one file -- files: {fileKey: bytes} -- so
        every other file is read-only context. Without this the agent offered
        "use the contrast as-is and adjust the design to match it", an action it
        cannot perform, then edited the one file it holds and reported success.

        Measured on the reported job: MORE intersects sample names across the
        target, the condition file and every regulator file, so renaming this
        file's column to match the target leaves the design disagreeing, and
        renaming it to match the design leaves the target disagreeing -- both
        give 0 common samples. No edit to ONE file can satisfy a three-way
        intersection, so an agent that can only edit one must say so.
        """
        self.assertIn("rewrite ONLY the file you were given", self.drawer_code)
        self.assertIn("read-only", self.drawer_code)
        # Phrases that sit inside ONE string literal: the instruction is built
        # by concatenation, so anything spanning a `+ "` is not there to find.
        self.assertIn("you cannot edit them", self.drawer_code)
        self.assertIn("will fail", self.drawer_code)

    def test_the_sandbox_really_does_receive_one_file(self):
        """The premise above. If this ever becomes many, the instruction is
        wrong and this suite should be the thing that notices."""
        self.assertIn("f[fileKey] = bytes; return f;", self.drawer_code)

    def test_the_brief_is_only_added_when_the_server_refused(self):
        """A file the user picks themselves is still a per-file conversion."""
        block = self.drawer_code[self.drawer_code.index("instructions:"):]
        block = block[:block.index("ask:")]
        self.assertIn("input && input.__paServerSaid", block)
        self.assertIn(": undefined", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
