#!/usr/bin/env python3
"""Browse is a quiet control inside the file field, not a button beside it.

The behaviour this guards
-------------------------
Every file row on Step 1 is a `myFilesSelectorButton`: a read-only path field
followed, until now, by an ExtJS split button reading "Browse..." with a menu
behind its arrow (upload from my PC / use a file from My Data / clear). The
button sat outside the field as a second, bordered box, so each row read as two
controls plus a tag, and the card's right edge was set by the widest of them.

Now "Browse..." is text at the right edge of the field itself, with a small
caret next to it that opens the same menu. The field keeps its single border;
the required/optional tag and the help tip stay where they were. Nothing is
lost: the file picker opens from the text, the three menu entries open from
the caret, and `setDisabled()` still greys the control out.

What is tested is the source the browser loads: the widget no longer builds a
split button, the path field renders the control through `afterSubTpl`, and the
stylesheet positions it inside the field and makes room for it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_step1_browse_lives_inside_the_field
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_ROOT = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "PaintomicsClient", "public_html"))
MY_DATA_VIEW = os.path.join(
    CLIENT_ROOT, "app", "view", "DataManagementViews", "DM_MyDataView.js")
MAIN_CSS = os.path.join(CLIENT_ROOT, "resources", "css", "main.css")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def widget_source(source):
    """The text of `Ext.define('Paintomics.view.common.MyFilesSelectorButton'`
    up to the next Ext.define."""
    start = source.index("Ext.define('Paintomics.view.common.MyFilesSelectorButton'")
    end = source.find("Ext.define(", start + 1)
    return source[start:end if end != -1 else len(source)]


class BrowseLivesInsideTheField(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.widget = widget_source(read(MY_DATA_VIEW))
        cls.css = read(MAIN_CSS)

    def test_the_widget_no_longer_builds_a_button_beside_the_field(self):
        self.assertNotIn('xtype: "splitbutton"', self.widget)
        self.assertNotIn("xtype: 'splitbutton'", self.widget)

    def test_the_path_field_renders_browse_and_caret_inside_itself(self):
        field = re.search(r'itemId:\s*"visiblePathField".*?\n\t\t\t\}', self.widget, re.S)
        self.assertIsNotNone(field, "visiblePathField config not found")
        config = field.group(0)
        self.assertIn("afterSubTpl", config)
        self.assertIn('class="po-browse-text"', config)
        self.assertIn('class="po-browse-caret"', config)

    def test_the_menu_still_offers_the_three_actions(self):
        for entry in ("Upload file from my PC", "Use a file from My Data",
                      "Clear selection"):
            self.assertIn(entry, self.widget)

    def test_disabling_still_reaches_the_control(self):
        """setDisabled() used to disable the split button; it must still do
        something visible now that there is no button."""
        self.assertIn("setDisabled: function(disabled)", self.widget)
        self.assertIn("po-browse-disabled", self.widget)

    def test_the_stylesheet_puts_browse_inside_the_field(self):
        self.assertIn(".po-browse {", self.css)
        self.assertRegex(self.css, r"\.po-browse\s*\{[^}]*position:\s*absolute")
        self.assertRegex(
            self.css, r"\.po-file-path \.x-form-text\s*\{[^}]*padding-right",
            "the input must leave room for the control at its right edge")


if __name__ == "__main__":
    unittest.main()
