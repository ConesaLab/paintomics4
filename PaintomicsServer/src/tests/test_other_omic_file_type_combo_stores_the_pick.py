#!/usr/bin/env python3
"""The File Type combo on the "Other data type" panel must store what is picked.

The behaviour this guards
-------------------------
An ExtJS combo keeps two copies of a selection: `displayField` names the record
column it prints in the box, `valueField` names the column it hands to the form
and to `isValid()`. Both must be columns the dropdown's records actually have.
The records come from `resources/data/file_types.json`:

    {"name": "Gene expression quantification", "type": "data"}

`OmicSubmittingPanel`'s `fileTypeSelector` was declared with
`valueField: ' name'` -- a leading space, since the 2021 initial commit. Picking
any entry therefore stored `record.get(" name")`, which is `undefined`, which
ExtJS 4.2.1 normalises to `null`; the box kept printing the choice (the display
column was spelled correctly) while `getValue()` returned `null`, and the
panel's `isValid()` refused the form with "Please, specify a File type." The
combo is only visible on the "Other data type" panel (the named panels hide it
behind a preset string), so every user who picked a file type from that list
was refused, and typing the text by hand was the accidental workaround.

That is the error report received on 2026-08-30 ("Invalid Form. File Type:
Please, specify a File type." with the box visibly showing a choice), reproduced
in Chrome on origin/master 919d6c95.

What is tested is the source the browser loads, in the style of the other
Step 1 tests: every File Type combo that reads file_types.json must store a
column that every record in that file has, so the assertion fails with the
offending spelling made visible (repr keeps the space).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_other_omic_file_type_combo_stores_the_pick
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_ROOT = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "PaintomicsClient", "public_html"))
STEP1_VIEWS = os.path.join(
    CLIENT_ROOT, "app", "view", "PathwayAcquisitionViews", "PA_Step1Views.js")
FILE_TYPES = os.path.join(CLIENT_ROOT, "resources", "data", "file_types.json")

# The two File Type combos an omic panel carries: the data file's and the
# relevant-features file's. Both load file_types.json.
COMBO_ITEM_IDS = ("fileTypeSelector", "relevantFileTypeSelector")

def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def enclosing_object(source, index):
    """The text of the `{ ... }` object literal that contains `index`.

    Walks back to the brace that opens this object, skipping any nested
    objects closed on the way, then forward to its matching close brace."""
    depth = 0
    start = index
    while start > 0:
        start -= 1
        if source[start] == "}":
            depth += 1
        elif source[start] == "{":
            if depth == 0:
                break
            depth -= 1
    depth = 0
    end = start
    while end < len(source):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                break
        end += 1
    return source[start:end + 1]


def combo_configs(source, item_id):
    """Yield (line_number, config_text) for every *combo* whose `itemId` is
    `item_id`.

    The named panels (Region-based, miRNA, MORE) carry a hidden `textfield`
    under the same itemId with a preset value; those never read
    file_types.json and are skipped."""
    for match in re.finditer(r'itemId:\s*"%s"' % re.escape(item_id), source):
        config = enclosing_object(source, match.start())
        if not re.search(r"xtype:\s*['\"]combo['\"]", config):
            continue
        yield source.count("\n", 0, match.start()) + 1, config


def combo_declarations(source, item_id):
    """Yield (line_number, displayField, valueField) for every combo whose
    `itemId` is `item_id`."""
    for line, config in combo_configs(source, item_id):
        display = re.search(r"displayField:\s*'([^']*)'", config)
        value = re.search(r"valueField:\s*'([^']*)'", config)
        yield (line,
               display.group(1) if display else None,
               value.group(1) if value else None)


class FileTypeComboStoresThePick(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = read(STEP1_VIEWS)
        cls.records = json.loads(read(FILE_TYPES))["types"]
        cls.assertTrue(cls.records, "file_types.json has no records")

    def test_every_file_type_combo_stores_a_column_the_records_have(self):
        """Whatever column valueField names must exist on every record, or
        every pick from the list is stored as undefined -> null."""
        columns = set.intersection(*(set(r) for r in self.records))
        for item_id in COMBO_ITEM_IDS:
            declarations = list(combo_declarations(self.source, item_id))
            self.assertTrue(declarations, "no combo with itemId %s" % item_id)
            for line, _display, value in declarations:
                self.assertIn(
                    value, columns,
                    "%s at PA_Step1Views.js:%d stores valueField %r, which is "
                    "not a column of file_types.json records %s -- a pick "
                    "from the list would be stored as null"
                    % (item_id, line, value, sorted(columns)))

    def test_the_stored_value_is_the_printed_name(self):
        """The server keeps the posted file type as the file's label, so the
        value must be the same human-readable name the box prints."""
        for item_id in COMBO_ITEM_IDS:
            for line, display, value in combo_declarations(self.source, item_id):
                self.assertEqual(
                    (display, value), ("name", "name"),
                    "%s at PA_Step1Views.js:%d prints %r but stores %r"
                    % (item_id, line, display, value))

    def test_the_relevant_file_type_may_stay_blank(self):
        """The relevant-features file is optional (its row is tagged so), and
        the panel's own isValid() already demands its File Type exactly when a
        relevant file is attached. `allowBlank: false` on that combo made
        ExtJS's form-level validation abort every submit with no relevant
        file -- after the valueField fix the form still never left the
        browser, and extJSErrorHandler showed "Unable to parse the error
        message." for a client-side abort."""
        for line, config in combo_configs(self.source, "relevantFileTypeSelector"):
            self.assertNotRegex(
                config, r"allowBlank:\s*false",
                "relevantFileTypeSelector at PA_Step1Views.js:%d is "
                "allowBlank: false, so a panel with no relevant file cannot "
                "be submitted" % line)


if __name__ == "__main__":
    unittest.main()
