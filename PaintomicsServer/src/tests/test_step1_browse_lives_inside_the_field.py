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


class BrowseLivesInsideTheFieldTest(unittest.TestCase):

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
        apply = between(self.widget, "applyBrowseState: function()", "\n\t},")
        self.assertIn(".disabled = ", apply,
                      "the native disabled attribute is the one carrier")

    def test_the_widget_still_forwards_mark_invalid(self):
        """Eleven Step 1 validators call markInvalid() on the widget (a
        Container, which has none of its own) to mark a row that is missing
        its file; the forwarder to the path field must survive any rewrite
        of the widget or every such refusal throws instead of marking."""
        self.assertIn('up("myFilesSelectorButton")', self.step1)
        self.assertIn('.markInvalid("Please, provide', self.step1)
        forwarder = between(self.widget, "markInvalid: function(errorMessage)", "\n\t},")
        self.assertIn('queryById("visiblePathField").markInvalid(errorMessage)', forwarder)

    def test_the_control_is_measured_when_it_is_actually_drawn(self):
        """A row rendered inside a hidden container measures 0 at afterrender;
        writing that into the input's padding would let the file name run
        under Browse once the row is shown. Measure only a drawn control and
        again when the field is laid out."""
        wire = between(self.widget, "wireBrowse: function(field)", "\n\t},")
        self.assertRegex(wire, r"\bwidth\s*<=\s*0", "guard the zero measurement")
        self.assertRegex(wire, r"[\"']resize[\"']", "re-measure on the field's resize")
        self.assertRegex(wire, r"if \(!measure\(\)\)", "listen for resize only until a figure has landed")
        self.assertIn("document.fonts", wire, "the web font can land after the first measurement")
        self.assertIn("measuredWidths", self.widget, "one figure per label for every row on the page")

    def test_a_container_enable_cannot_lift_the_example_lock(self):
        """Example rows are locked through the widget's setDisabled; a panel
        that disables and re-enables the row's container (the miRNA
        correlation box, the Region-based own-associations toggle) fires the
        field's enable, which must not unlock them. Two flags, one state."""
        apply = between(self.widget, "applyBrowseState: function()", "\n\t},")
        self.assertIn("browseLocked", apply)
        # The field's own disabled state, not a mirror of it kept in step by hand.
        self.assertRegex(apply, r"field\s*&&\s*field\.disabled")
        listeners = between(self.field, "listeners: {", "\n\t\t\t\t},")
        self.assertNotIn("setDisabled(false)", listeners)
        self.assertEqual(listeners.count("applyBrowseState()"), 2, "disable and enable both re-apply")

    def test_the_caret_toggles_its_menu_without_a_timer(self):
        """Ext.menu.Manager hides every menu on a document mousedown, so a
        click on the caret would show its menu straight back. The caret's
        mousedown records whether the menu was open (element listeners run
        before the document's) and still propagates -- combos and tooltips
        listen to the same document mousedown to close -- and the click
        shows the menu only if it was not open."""
        wire = between(self.widget, "wireBrowse: function(field)", "\n\t},")
        self.assertRegex(wire, r"[\"']mousedown[\"'][^}]*menuWasOpen\s*=")
        self.assertNotIn("stopPropagation", wire)
        # A press released off the caret never becomes a click and would leave
        # the flag stale; a keyboard activation (detail 0) must not read it.
        self.assertIn("detail === 0", wire)
        toggle = between(self.widget, "toggleOptionsMenu: function(keyboard)", "\n\t},")
        self.assertIn("menuWasOpen", toggle)
        self.assertIn("isVisible()", toggle)

    def test_the_menu_still_offers_the_three_actions(self):
        for entry in ("Upload file from my PC", "Use a file from My Data",
                      "Clear selection"):
            self.assertIn(entry, self.widget)

    def test_a_row_disabled_through_its_container_fades_once(self):
        """Neptune fades a disabled row's label and input to .3 but not the
        control, which is the input's sibling: the control fades to the same
        .3 itself, and its buttons' own .45 does not stack on top."""
        self.assertRegex(self.css, r"\.x-item-disabled\s+\.po-browse\s*\{[^}]*opacity:\s*0?\.3")
        self.assertRegex(self.css, r"\.x-item-disabled\s+\.po-browse\s+button:disabled\s*\{[^}]*opacity:\s*1")

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


if __name__ == "__main__":
    unittest.main()
