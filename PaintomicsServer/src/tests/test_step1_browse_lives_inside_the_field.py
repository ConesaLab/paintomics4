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
the required/optional tag and the help tip stay where they were.

What the split button did for free, and the review of the first cut found
missing, is pinned here as contracts between files:

- The menu must have an owner. The Region-based and miRNA panels add entries
  through `extraButtons` whose handlers climb `this.up("myFilesSelectorButton")`
  from the menu item; an ownerless `Ext.menu.Menu` dead-ends that walk and the
  GTF / other-omic pickers throw instead of filling the row.
- Disabling the row's field must disable the control. Panels disable the
  widget's inner container (`down('container').setDisabled(...)`), which
  cascades to form fields and buttons only; the control listens to the path
  field's own disable/enable so every door converges on one mechanism.
- The controls are native `<button type="button">`s: Enter and Space, the
  `disabled` attribute (out of the tab order, click-inert) and non-navigation
  come with the element, and the dark theme's blanket anchor colour rule
  never touches them -- so dark.css needs no restatement to keep in sync.
- The split-arrow rules hand-drawn for the old buttons go with them; left
  behind they painted a fake menu caret on the MORE panel's plain button.

What is tested is the source the browser loads, in the style of the other
Step 1 tests; the runtime behaviour was verified in Chrome and is described
in the commit.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_step1_browse_lives_inside_the_field
"""
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_ROOT = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "PaintomicsClient", "public_html"))
MY_DATA_VIEW = os.path.join(
    CLIENT_ROOT, "app", "view", "DataManagementViews", "DM_MyDataView.js")
STEP1_VIEWS = os.path.join(
    CLIENT_ROOT, "app", "view", "PathwayAcquisitionViews", "PA_Step1Views.js")
MAIN_CSS = os.path.join(CLIENT_ROOT, "resources", "css", "main.css")
DARK_CSS = os.path.join(CLIENT_ROOT, "resources", "css", "dark.css")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def between(source, start_marker, end_marker):
    """The text from the first `start_marker` to the next `end_marker`."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def widget_source(source):
    """`Ext.define('Paintomics.view.common.MyFilesSelectorButton'` up to the
    next Ext.define."""
    return between(
        source,
        "Ext.define('Paintomics.view.common.MyFilesSelectorButton'",
        "Ext.define('Paintomics.view.common.MyFilesSelectorDialog'")


def path_field_config(widget):
    """The visiblePathField config: from its itemId to the hidden filefield
    that follows it in the widget's items."""
    return between(widget, 'itemId: "visiblePathField"', "xtype: 'filefield'")


class BrowseLivesInsideTheField(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.widget = widget_source(read(MY_DATA_VIEW))
        cls.field = path_field_config(cls.widget)
        cls.step1 = read(STEP1_VIEWS)
        cls.css = read(MAIN_CSS)
        cls.dark = read(DARK_CSS)

    def test_the_widget_no_longer_builds_a_button_beside_the_field(self):
        self.assertNotIn('xtype: "splitbutton"', self.widget)
        self.assertNotIn("xtype: 'splitbutton'", self.widget)

    def test_the_path_field_renders_native_buttons_inside_itself(self):
        self.assertIn("afterSubTpl", self.field)
        self.assertIn('<button type="button" class="po-browse-text"', self.field)
        self.assertIn('<button type="button" class="po-browse-caret"', self.field)
        self.assertNotIn("<a ", self.field, "anchors bring link drag, "
                         "link context menus and the dark anchor colour")

    def test_the_menu_can_be_climbed_from_its_items(self):
        """The panels' extraButtons handlers reach the widget with
        `this.up("myFilesSelectorButton")` from a menu item, which walks
        parentMenu -> ownerButton -> ownerCt; the menu must name the widget
        as its owner or those handlers throw."""
        self.assertIn('up("myFilesSelectorButton")', self.step1,
                      "the contract this test guards no longer exists")
        self.assertIn(".ownerButton = me", self.widget)

    def test_disabling_the_field_disables_the_control(self):
        """Callers disable the row through the field or its container; the
        control follows the field's own disable/enable events."""
        self.assertRegex(self.field, r"\bdisable:\s*function")
        self.assertRegex(self.field, r"\benable:\s*function")
        set_disabled = between(self.widget, "setDisabled: function(disabled)",
                               "openFilePicker: function")
        self.assertIn(".disabled = ", set_disabled,
                      "the native disabled attribute is the one carrier")

    def test_the_menu_still_offers_the_three_actions(self):
        for entry in ("Upload file from my PC", "Use a file from My Data",
                      "Clear selection"):
            self.assertIn(entry, self.widget)

    def test_the_stylesheet_puts_browse_inside_the_field(self):
        self.assertRegex(self.css, r"\.po-browse\s*\{[^}]*position:\s*absolute")
        self.assertRegex(
            self.css, r"\.po-file-path \.x-form-text\s*\{[^}]*padding-right",
            "the input must leave room for the control at its right edge")
        self.assertNotIn(".po-file-path .x-form-item-body", self.css,
                         "Neptune already positions .x-form-item-body")

    def test_the_split_arrow_rules_went_with_the_split_button(self):
        for name, sheet in (("main.css", self.css), ("dark.css", self.dark)):
            self.assertNotIn("a.x-btn .x-btn-wrap::after", sheet,
                             "%s still draws the split arrow" % name)
            self.assertNotIn("a.x-btn .x-btn-wrap::before", sheet,
                             "%s still draws the split divider" % name)

    def test_dark_theme_needs_no_restatement(self):
        """Native buttons are not caught by dark.css's blanket anchor rule and
        the control reads theme tokens, so a second copy to keep in sync
        would only ever drift."""
        self.assertNotIn(".po-browse", self.dark)


if __name__ == "__main__":
    unittest.main()
