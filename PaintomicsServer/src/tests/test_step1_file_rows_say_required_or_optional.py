#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Every file row on Step 1 says whether the job needs it.

The labels used to carry it in words -- "Relevant associations file
(optional)" over a field that refused the form when the correlation box was
off -- and most rows said nothing at all. Each `myFilesSelectorButton` now
declares `requiredTag: "required" | "optional"`; a row without one is a row
somebody forgot, not a row with nothing to say, so this test refuses it. The
rows whose requiredness follows a choice made elsewhere on the card flip it
with setRequiredTag() from the same expression the validator reads.

How it is shown: the convention every form reader already knows. A required
row carries a red asterisk after its label ("Data file *:") and an optional
row carries nothing -- the words "required" / "optional" that used to sit
after the Browse button are gone, and the card's help column says once what
the asterisk means. The label template renders the mark (afterLabelTextTpl),
so the label text the refusal dialog quotes stays the plain words; the mark
itself carries the word "required" (role="img") for readers that cannot see
it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_step1_file_rows_say_required_or_optional
"""
import os
import re
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
CLIENT_ROOT = os.path.abspath(os.path.join(SERVER_ROOT, "..", "PaintomicsClient", "public_html"))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

STEP1_VIEWS = os.path.join(CLIENT_ROOT, "app", "view", "PathwayAcquisitionViews", "PA_Step1Views.js")
MY_DATA_VIEW = os.path.join(CLIENT_ROOT, "app", "view", "DataManagementViews", "DM_MyDataView.js")
MAIN_CSS = os.path.join(CLIENT_ROOT, "resources", "css", "main.css")


def read(path):
    with open(path, "r") as handle:
        return handle.read()


def _fileRows(source):
    """(line number, the item's text up to its closing brace) for every live
    myFilesSelectorButton item; commented-out rows are skipped."""
    rows = []
    # Block comments are blanked (not removed, so line numbers hold): the
    # miRNA panel keeps one retired row inside /* ... */.
    source = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), source, flags=re.S)
    for match in re.finditer(r'xtype:\s*"myFilesSelectorButton"', source):
        lineStart = source.rfind("\n", 0, match.start()) + 1
        line = source[lineStart:match.start()]
        if line.lstrip().startswith("//") or line.lstrip().startswith("*"):
            continue
        # The item's own braces: walk to the brace that closes the object
        # this xtype sits in.
        depth = 1
        i = match.end()
        while i < len(source) and depth > 0:
            depth += {"{": 1, "}": -1}.get(source[i], 0)
            i += 1
        rows.append((source.count("\n", 0, match.start()) + 1, source[match.start():i]))
    return rows


class EveryFileRowIsTaggedTest(unittest.TestCase):

    def setUp(self):
        self.source = read(STEP1_VIEWS)
        self.rows = _fileRows(self.source)

    def test_there_are_file_rows_to_check(self):
        self.assertGreater(len(self.rows), 20)

    def test_every_file_row_declares_a_tag(self):
        untagged = [line for line, text in self.rows if "requiredTag:" not in text]
        self.assertEqual(untagged, [], "file rows without a requiredTag at lines %s" % untagged)

    def test_a_tag_is_required_or_optional(self):
        for line, text in self.rows:
            match = re.search(r'requiredTag:\s*"([^"]+)"', text)
            if match:
                self.assertIn(match.group(1), ("required", "optional"), "line %d" % line)

    def test_the_experimental_design_row_is_optional(self):
        """The job runs without it -- the binomial route -- and the server
        reads it only when present (JobInformationManager: `_design_file`)."""
        design = [text for line, text in self.rows if 'itemId: "designFileSelector"' in text]
        self.assertEqual(len(design), 1)
        self.assertIn('requiredTag: "optional"', design[0])

    def test_the_mirna_rows_that_depend_on_the_correlation_box_flip_together(self):
        """Correlation on: the gene expression file is needed and the relevant
        associations are derived; off: the list is needed. Both flips sit in
        the one change handler, driven by the same reading the validator makes."""
        handler = self.source[self.source.find('_corrOptions").change('):]
        handler = handler[:handler.find("});") + 3]
        self.assertIn('queryById("secondaryAssociationFileSelector").setRequiredTag(corrEnabled ? "optional" : "required")', handler)
        self.assertIn('queryById("rnaseqauxFileSelector").setRequiredTag(corrEnabled ? "required" : "optional")', handler)

    def test_the_help_column_says_once_what_the_asterisk_means(self):
        """One legend per form, next to the rows, instead of a word per row."""
        self.assertIn('po-required-mark', self.source)
        self.assertRegex(self.source, r"marks? (the )?files? (the job|this job|a job) needs",
                         "the help text must explain the asterisk")


class TheTagIsOneComponentTest(unittest.TestCase):

    def test_the_selector_renders_the_mark_in_its_label(self):
        source = read(MY_DATA_VIEW)
        self.assertIn("requiredTag: null", source)
        self.assertIn("afterLabelTextTpl", source)
        self.assertIn("setRequiredTag: function(tag)", source)
        # The mark is part of the label, not a box after the Browse button.
        self.assertIn('class="po-required-mark" role="img" aria-label="required">*<', source)
        # After the words and before the colon: ExtJS emits the template after
        # its separator, so the separator is blank and the colon is in the
        # template.
        self.assertIn('labelSeparator: "",', source)
        self.assertIn("'</span>:',", source)
        self.assertNotIn('itemId: "requiredTag"', source)
        self.assertNotIn("buildRequiredTag", source)
        self.assertNotIn("po-file-tag", source)

    def test_flipping_the_tag_shows_or_hides_the_mark(self):
        """The conditional miRNA rows flip after render; the mark is always in
        the label and the setter only shows or hides it."""
        source = read(MY_DATA_VIEW)
        setter = source[source.index("setRequiredTag: function(tag)"):]
        setter = setter[:setter.index("\n\t},") + 4]
        self.assertIn('setDisplayed(tag === "required")', setter)

    def test_the_mark_is_red_and_the_words_are_gone(self):
        css = read(MAIN_CSS)
        self.assertRegex(css, r"\.po-required-mark\s*\{[^}]*var\(--pa-status-error")
        self.assertNotIn(".po-file-tag {", css)
        self.assertNotIn(".po-file-tag-required {", css)


if __name__ == "__main__":
    unittest.main()
