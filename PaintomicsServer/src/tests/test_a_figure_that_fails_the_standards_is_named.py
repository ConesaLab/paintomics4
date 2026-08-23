#!/usr/bin/env python3
"""Every line of figure-standards.md, and a fixture that breaks it.

A standard enforced by a prompt is a standard the model is asked to meet, and
this arm has measured what that is worth: a stage that graded itself passed by
changing nothing. So each of the eight QA checks gets a bundle here that is
correct in every respect except one, and the test asserts that the ONE check
named for that defect is the one that fails. Asserting only "the bundle failed"
would pass just as happily if every check were broken, or if a single check
were doing all the work.

Two properties are load-bearing beyond the individual checks:

  * **All eight always run.** A malformed SVG must not abort the pass -- the
    seven checks after it are the ones that tell the author what to fix. Every
    test below asserts eight result lines.
  * **Not-checked is not passed.** `values_match_job` with no job values, and
    `palette_membership` with no `figure_style`, both come back ok=False and
    say SKIPPED. A figure whose numbers were never re-checked must not look
    like a figure whose numbers were.

The fixtures are hand-built strings. matplotlib is not installed here and is
not in requirements.txt; a standards suite that only runs where the plotting
stack exists is a standards suite that does not run.

    python -m src.tests.test_a_figure_that_fails_the_standards_is_named
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "../..")))

from src.classes.AIInterpret import figure_qa as QA               # noqa: E402

# Where figure_style would live. Both arms of figure_qa's lazy import resolve to
# this absolute name, so putting a stub (or the ImportError sentinel None) here
# controls the palette check without figure_style.py needing to exist.
STYLE_MODULE = "src.classes.AIInterpret.figure_style"

# Okabe-Ito, the palette figure-standards.md names as the default.
OKABE_ITO = ("#000000", "#e69f00", "#56b4e9", "#009e73",
             "#f0e442", "#0072b2", "#d55e00", "#cc79a7")

# Real numbers from a real deposit (GSE261333, log2 CPM), so a fixture that
# drifts from the job's values drifts from something concrete.
JOB_VALUES = {
    "Acss2": {"G12D": 2.01, "G12R": 1.40, "G12V": 3.60, "G13D": 1.52},
    "Fdps": {"G12D": 7.81, "G12R": 6.73, "G12V": 8.02, "G13D": 6.58},
}

GOOD_TSV = ("feature\tG12D\tG12R\tG12V\tG13D\n"
            "Acss2\t2.01\t1.40\t3.60\t1.52\n"
            "Fdps\t7.81\t6.73\t8.02\t6.58\n")

CONCLUSION = "Acss2 rises only in KRAS G12V."

GOOD_LEGEND = (
    "**Fig. 1** - " + CONCLUSION + " Bars are the mean log2 CPM of three\n"
    "biological replicates per allele (n = 3); individual replicates are drawn\n"
    "as points because n < 10. One-way ANOVA across the four alleles,\n"
    "p = 0.0021. Colour encodes allele and is the same in every figure of this\n"
    "report.\n")


def _svg(body, extra_header=""):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="89mm" '
            'height="60mm" viewBox="0 0 252 170"%s>\n%s\n</svg>\n'
            % (extra_header, body))


# A correct panel: palette stroke, 6 pt labels, well separated, one rotated
# axis title (which the collision check must skip rather than mis-place).
GOOD_BODY = (
    '  <g><path d="M 10 100 L 60 40" '
    'style="fill:none;stroke:#0072b2;stroke-width:1"/></g>\n'
    '  <text x="10" y="20" style="font-size:6px;fill:#000000">Condition A</text>\n'
    '  <text x="10" y="40" style="font-size:6px;fill:#000000">Condition B</text>\n'
    '  <text x="4" y="90" transform="rotate(-90 4 90)" '
    'style="font-size:6px;fill:#000000">log2 CPM</text>\n')


class FigureQaNamesTheStandardItBroke(unittest.TestCase):

    def setUp(self):
        self.dirs = []
        self._saved_style = sys.modules.get(STYLE_MODULE, "absent")
        self._install_palette(OKABE_ITO)

    def tearDown(self):
        if self._saved_style == "absent":
            sys.modules.pop(STYLE_MODULE, None)
        else:
            sys.modules[STYLE_MODULE] = self._saved_style
        for path in self.dirs:
            shutil.rmtree(path, ignore_errors=True)

    # -- fixture plumbing --------------------------------------------------

    def _install_palette(self, palette):
        """Put a figure_style stub in sys.modules.

        figure_style.py is written by another hand on this branch. Injecting
        here means these tests neither wait for that file nor break when it
        lands with a different palette -- the check under test is "is the SVG's
        ink in the palette", not "is the palette this list".
        """
        stub = types.ModuleType(STYLE_MODULE)
        stub.PALETTE = palette
        sys.modules[STYLE_MODULE] = stub

    def _bundle(self, svg=None, tsv=None, legend=None, drop=()):
        path = tempfile.mkdtemp(prefix="figqa_")
        self.dirs.append(path)
        files = {
            "figure.svg": svg if svg is not None else _svg(GOOD_BODY),
            "figure.pdf": "%PDF-1.4\n% a real pdf is not needed to check "
                          "presence\n",
            "figure.png": "\x89PNG\r\n\x1a\n",
            "figure.py": "# the exact script that produced this figure\n",
            "data.tsv": tsv if tsv is not None else GOOD_TSV,
            "legend.md": legend if legend is not None else GOOD_LEGEND,
        }
        for name, text in files.items():
            if name in drop:
                continue
            with open(os.path.join(path, name), "w") as fh:
                fh.write(text)
        return path

    def _verdict(self, bundle, spec=None, values=JOB_VALUES):
        spec = spec if spec is not None else {"conclusion": CONCLUSION,
                                              "statistic": True,
                                              "centre_zero": False,
                                              "has_negative": False}
        passed, lines = QA.check(bundle, spec, values)
        self.assertEqual(8, len(lines),
                         "all eight checks must run every time; one that "
                         "aborts the pass hides the seven that would have said "
                         "what to fix")
        return passed, lines

    def _assert_only(self, lines, failing_check):
        """Exactly one check failed, and it is the one named for this defect."""
        failed = [ln for ln in lines if ln.startswith("FAIL")]
        self.assertEqual(1, len(failed),
                         "expected only %s to fail, got:\n%s"
                         % (failing_check, "\n".join(failed)))
        self.assertIn(failing_check, failed[0])
        return failed[0]

    # -- the bundle that meets every line ----------------------------------

    def test_a_bundle_that_meets_the_standards_passes_all_eight(self):
        """The control. Without it, every test below could pass for the wrong
        reason -- a check that always fails names the right defect too."""
        passed, lines = self._verdict(self._bundle())
        self.assertTrue(passed, "\n".join(lines))
        self.assertTrue(all(ln.startswith("PASS") for ln in lines),
                        "\n".join(lines))

    # -- 1. bundle_complete ------------------------------------------------

    def test_a_missing_pdf_is_an_incomplete_bundle(self):
        """Vector PDF is a deliverable, not a nicety: it is what a journal
        asks for and what a screenshot can never be."""
        passed, lines = self._verdict(self._bundle(drop=("figure.pdf",)))
        self.assertFalse(passed)
        line = self._assert_only(lines, "bundle_complete")
        self.assertIn("figure.pdf", line)

    def test_a_zero_byte_artefact_is_not_a_present_artefact(self):
        """A render killed mid-write leaves the file there and empty; presence
        alone would pass it."""
        bundle = self._bundle()
        open(os.path.join(bundle, "figure.png"), "w").close()
        passed, lines = self._verdict(bundle)
        self.assertFalse(passed)
        line = self._assert_only(lines, "bundle_complete")
        self.assertIn("empty", line)

    # -- 2. svg_text_is_text -----------------------------------------------

    def test_an_svg_that_is_really_a_raster_is_caught(self):
        """The `<svg>` wrapper around a PNG: vector by extension only. Every
        label in it is unsearchable, unselectable and blurred at print size."""
        raster = _svg('  <image x="0" y="0" width="252" height="170" '
                      'xlink:href="data:image/png;base64,iVBORw0KGgo="/>')
        passed, lines = self._verdict(self._bundle(svg=raster))
        self.assertFalse(passed)
        failed = [ln for ln in lines if ln.startswith("FAIL")]
        text_line = [ln for ln in failed if "svg_text_is_text" in ln]
        self.assertTrue(text_line, "\n".join(failed))
        self.assertIn("<image>", text_line[0])

    def test_labels_drawn_as_paths_are_caught(self):
        """The other half: `svg.fonttype` left at 'path' turns every label into
        a `<path>`, which looks perfect on screen and is dead in typesetting."""
        paths_only = _svg('  <g><path d="M 10 20 L 12 20 L 12 26 Z" '
                          'style="fill:#000000"/></g>')
        _passed, lines = self._verdict(self._bundle(svg=paths_only))
        failed = [ln for ln in lines if "svg_text_is_text" in ln]
        self.assertTrue(failed[0].startswith("FAIL"), failed)
        self.assertIn("no <text>", failed[0])

    # -- 3. font_size_floor ------------------------------------------------

    def test_a_four_point_label_is_below_the_print_floor(self):
        """5 pt is the floor in figure-standards.md; 4 pt is what a 183 mm
        figure becomes when it is dropped into an 89 mm column."""
        tiny = _svg(GOOD_BODY.replace(
            '<text x="10" y="40" style="font-size:6px',
            '<text x="10" y="40" style="font-size:4px'))
        passed, lines = self._verdict(self._bundle(svg=tiny))
        self.assertFalse(passed)
        line = self._assert_only(lines, "font_size_floor")
        self.assertIn("4.00 pt", line)

    def test_a_size_the_cascade_owns_is_reported_not_assumed(self):
        """`font-size:0.8em` cannot be resolved without the cascade. Counting it
        as passing would be the quiet kind of wrong."""
        relative = _svg('  <text x="10" y="20" style="font-size:0.8em">'
                        'Condition A</text>')
        _passed, lines = self._verdict(self._bundle(svg=relative))
        line = [ln for ln in lines if "font_size_floor" in ln][0]
        self.assertTrue(line.startswith("FAIL"), line)
        self.assertIn("could not be checked", line)

    # -- 4. palette_membership ---------------------------------------------

    def test_a_jet_colour_is_outside_the_house_palette(self):
        """Rainbow maps are banned outright by the standards: they invent
        boundaries the data does not have and fail colour-blind simulation."""
        jetty = _svg(GOOD_BODY.replace("stroke:#0072b2", "stroke:#00ffff"))
        passed, lines = self._verdict(self._bundle(svg=jetty))
        self.assertFalse(passed)
        line = self._assert_only(lines, "palette_membership")
        self.assertIn("#00ffff", line)

    def test_the_grey_ramp_is_always_allowed(self):
        """Axes, ticks and gridlines are grey and are not palette colours; a
        check that rejected them would be switched off within a day."""
        greys = _svg(GOOD_BODY.replace("stroke:#0072b2", "stroke:#4d4d4d")
                     .replace('fill:#000000">Condition A',
                              'fill:#cccccc">Condition A'))
        _passed, lines = self._verdict(self._bundle(svg=greys))
        line = [ln for ln in lines if "palette_membership" in ln][0]
        self.assertTrue(line.startswith("PASS"), line)

    def test_an_unimportable_palette_is_skipped_not_passed(self):
        """figure_style.py may not exist yet. The check must say it could not
        run -- and still count as not-ok, so the verdict cannot claim the
        palette was verified when nothing verified it."""
        sys.modules[STYLE_MODULE] = None      # makes `import` raise ImportError
        passed, lines = self._verdict(self._bundle())
        self.assertFalse(passed)
        line = self._assert_only(lines, "palette_membership")
        self.assertIn("SKIPPED", line)
        self.assertIn("figure_style", line)

    # -- 5. diverging_only_for_signed --------------------------------------

    def test_a_zero_centred_map_on_all_positive_data_is_caught(self):
        """A diverging map centred on zero over all-positive values draws a
        midpoint that is not in the data, and the eye reads it as a boundary."""
        spec = {"conclusion": CONCLUSION, "statistic": True,
                "centre_zero": True, "has_negative": False}
        passed, lines = self._verdict(self._bundle(), spec=spec)
        self.assertFalse(passed)
        line = self._assert_only(lines, "diverging_only_for_signed")
        self.assertIn("invented", line)

    def test_a_zero_centred_map_on_signed_data_is_correct(self):
        spec = {"conclusion": CONCLUSION, "statistic": True,
                "centre_zero": True, "has_negative": True}
        passed, lines = self._verdict(self._bundle(), spec=spec)
        self.assertTrue(passed, "\n".join(lines))

    # -- 6. legend_carries_stats -------------------------------------------

    def test_stars_alone_are_not_a_statistic(self):
        """"n, test name, and exact p ... never stars alone" -- the standards,
        verbatim. This is the single most common reviewer complaint."""
        starred = ("**Fig. 1** - " + CONCLUSION +
                   " Bars are mean log2 CPM. ***\n")
        passed, lines = self._verdict(self._bundle(legend=starred))
        self.assertFalse(passed)
        line = self._assert_only(lines, "legend_carries_stats")
        self.assertIn("stars alone", line)

    def test_a_legend_that_drops_the_conclusion_is_caught(self):
        """The conclusion sentence is the claim the figure exists to make; a
        legend that opens with methods makes the reader find the claim."""
        methods_first = ("**Fig. 1** - Bars are mean log2 CPM, n = 3 per "
                         "allele; one-way ANOVA, p = 0.0021.\n")
        passed, lines = self._verdict(self._bundle(legend=methods_first))
        self.assertFalse(passed)
        line = self._assert_only(lines, "legend_carries_stats")
        self.assertIn("conclusion", line)

    def test_a_descriptive_panel_owes_no_p_value(self):
        """Demanding a statistic of a panel that draws none trains the
        templates to print a p-value that means nothing."""
        spec = {"conclusion": CONCLUSION, "statistic": False,
                "centre_zero": False, "has_negative": False}
        plain = "**Fig. 1** - " + CONCLUSION + " Bars are mean log2 CPM.\n"
        passed, lines = self._verdict(self._bundle(legend=plain), spec=spec)
        self.assertTrue(passed, "\n".join(lines))

    # -- 7. values_match_job -----------------------------------------------

    def test_an_edited_value_in_data_tsv_is_caught(self):
        """The data-claim rule: a number on a figure gets the same verification
        as a sentence in the report. 3.60 is Acss2 at G12V in the job."""
        edited = GOOD_TSV.replace("\t3.60\t", "\t9.99\t")
        passed, lines = self._verdict(self._bundle(tsv=edited))
        self.assertFalse(passed)
        line = self._assert_only(lines, "values_match_job")
        self.assertIn("Acss2/G12V", line)
        self.assertIn("9.99", line)

    def test_only_the_first_three_mismatches_are_reported(self):
        """A wall of diffs is not a reason; the count still has to be exact."""
        broken = GOOD_TSV.replace("2.01", "0").replace("1.40", "0") \
                         .replace("3.60", "0").replace("1.52", "0")
        _passed, lines = self._verdict(self._bundle(tsv=broken))
        line = [ln for ln in lines if "values_match_job" in ln][0]
        self.assertIn("4 value(s)", line)
        self.assertIn("+1 more", line)

    def test_a_feature_the_job_never_had_is_a_mismatch(self):
        """An invented row is worse than a wrong number: nothing anchors it."""
        invented = GOOD_TSV + "Srebf1\t7.71\t7.51\t8.11\t7.47\n"
        _passed, lines = self._verdict(self._bundle(tsv=invented))
        line = [ln for ln in lines if "values_match_job" in ln][0]
        self.assertTrue(line.startswith("FAIL"), line)
        self.assertIn("Srebf1", line)

    def test_the_long_shape_is_read_as_well_as_the_wide_one(self):
        """Timecourse templates write long, heatmap templates write wide. A
        reader that guessed wrong would report every value as a mismatch."""
        long_tsv = ("feature\tcondition\tvalue\n"
                    "Acss2\tG12D\t2.01\n"
                    "Acss2\tG12V\t3.60\n"
                    "Fdps\tG12V\t8.02\n")
        passed, lines = self._verdict(self._bundle(tsv=long_tsv))
        self.assertTrue(passed, "\n".join(lines))

    def test_no_job_values_is_skipped_not_passed(self):
        passed, lines = self._verdict(self._bundle(), values=None)
        self.assertFalse(passed)
        line = self._assert_only(lines, "values_match_job")
        self.assertIn("SKIPPED", line)

    # -- 8. no_label_collisions --------------------------------------------

    def test_two_labels_on_top_of_each_other_are_caught(self):
        """Overlapping tick labels are the defect a reader sees first and the
        author never does, because the author looks at the on-screen render."""
        collided = _svg(GOOD_BODY.replace('<text x="10" y="40"',
                                          '<text x="10" y="22"'))
        passed, lines = self._verdict(self._bundle(svg=collided))
        self.assertFalse(passed)
        line = self._assert_only(lines, "no_label_collisions")
        self.assertIn("Condition", line)

    def test_the_collision_check_admits_it_is_coarse(self):
        """0.6 * size per character is an estimate, and rotated labels are
        skipped rather than mis-placed. A check that cries wolf on every y-axis
        title gets switched off, so its reason has to say what it did."""
        _passed, lines = self._verdict(self._bundle())
        line = [ln for ln in lines if "no_label_collisions" in ln][0]
        self.assertTrue(line.startswith("PASS"), line)
        self.assertIn("skipped", line,
                      "the rotated axis title must be reported as skipped")

    # -- the pass never aborts ---------------------------------------------

    def test_a_broken_svg_still_leaves_the_other_checks_running(self):
        """Unparseable markup must cost the SVG checks, not the pass."""
        passed, lines = self._verdict(
            self._bundle(svg="<svg><text>unclosed"))
        self.assertFalse(passed)
        self.assertTrue(any(ln.startswith("PASS") for ln in lines),
                        "one bad file silenced every check:\n%s"
                        % "\n".join(lines))


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(
            FigureQaNamesTheStandardItBroke))
    sys.exit(0 if r.wasSuccessful() else 1)
