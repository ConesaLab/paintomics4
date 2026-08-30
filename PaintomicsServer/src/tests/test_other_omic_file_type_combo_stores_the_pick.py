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

Behind that first gate stood a second one. ExtJS runs `form.isValid()` again
inside `submit()`, and when one of its own validators refuses -- `allowBlank:
false` on a combo the panel calls optional, a `maxLength`, an omic name typed
and deleted (whose value is then `null`, not "") -- it calls the failure handler
with no response, which `extJSErrorHandler` used to report as "Oops..Internal
error! Unable to parse the error message." So: the optional relevant-features
File Type may stay blank at the ExtJS level (its own validator demands it
exactly when a relevant file is attached, as the panel does), the panel reads
`null` as blank, and a client-side abort names the field the way checkForm()'s
refusal does.

What is tested is the source the browser loads, in the style of the other
Step 1 tests. The brace walker that isolates a combo's config skips string
literals and comments, so a brace in a helpTip cannot shift it.

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
UTIL_JS = os.path.join(CLIENT_ROOT, "app", "view", "common", "Util.js")
FILE_TYPES = os.path.join(CLIENT_ROOT, "resources", "data", "file_types.json")

# The two File Type combos an omic panel carries: the data file's and the
# relevant-features file's. Both load file_types.json.
COMBO_ITEM_IDS = ("fileTypeSelector", "relevantFileTypeSelector")

QUOTED = r"""['"]([^'"]*)['"]"""


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def mask_strings_and_comments(source):
    """The source with the *contents* of string literals and comments replaced
    by spaces, same length, so indices into the original still hold and a brace
    inside a helpTip or a block comment cannot fool a brace walker."""
    out = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            while i < n and source[i] != quote:
                if source[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append("\n" if source[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append(quote)
                i += 1
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(re.sub(r"[^\n]", " ", source[i:end]))
            i = end
        elif source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i))
            i = end
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def enclosing_object(source, index, masked=None):
    """The text of the `{ ... }` object literal that contains `index`.

    Walks back to the brace that opens this object, skipping any nested
    objects closed on the way, then forward to its matching close brace.
    Braces are counted on the masked source, so ones inside strings and
    comments do not count."""
    masked = mask_strings_and_comments(source) if masked is None else masked
    depth = 0
    start = index
    while start > 0:
        start -= 1
        if masked[start] == "}":
            depth += 1
        elif masked[start] == "{":
            if depth == 0:
                break
            depth -= 1
    depth = 0
    end = start
    while end < len(masked):
        if masked[end] == "{":
            depth += 1
        elif masked[end] == "}":
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
    masked = mask_strings_and_comments(source)
    for match in re.finditer(r'itemId:\s*"%s"' % re.escape(item_id), source):
        config = enclosing_object(source, match.start(), masked)
        if not re.search(r"xtype:\s*['\"]combo(box)?['\"]", config):
            continue
        yield source.count("\n", 0, match.start()) + 1, config


def combo_declarations(source, item_id):
    """Yield (line_number, displayField, valueField) for every combo whose
    `itemId` is `item_id`."""
    for line, config in combo_configs(source, item_id):
        display = re.search(r"displayField:\s*" + QUOTED, config)
        value = re.search(r"valueField:\s*" + QUOTED, config)
        yield (line,
               display.group(1) if display else None,
               value.group(1) if value else None)


class TheBraceWalkerReadsTheSourceLikeAParser(unittest.TestCase):

    SNIPPET = """{
\t\txtype: "combobox", itemId: "fileTypeSelector",
\t\thelpTip: "e.g. {gene} or }weird{",  // a } in a line comment
\t\t/* a { in a block comment */
\t\tdisplayField: "name", valueField: 'name'
\t}, {
\t\txtype: 'combo', itemId: "mapToSelector", valueField: 'value'
\t}"""

    def test_braces_inside_strings_and_comments_do_not_count(self):
        (line, display, value), = list(combo_declarations(self.SNIPPET, "fileTypeSelector"))
        self.assertEqual((display, value), ("name", "name"))

    def test_combobox_alias_and_double_quotes_are_the_same_combo(self):
        self.assertEqual(len(list(combo_configs(self.SNIPPET, "fileTypeSelector"))), 1)
        self.assertEqual(len(list(combo_configs(self.SNIPPET, "mapToSelector"))), 1)


class FileTypeComboStoresThePick(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = read(STEP1_VIEWS)
        cls.records = json.loads(read(FILE_TYPES))["types"]
        if not cls.records:
            raise AssertionError("file_types.json has no records")

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

    def test_the_relevant_file_type_keeps_its_own_rule_for_extjs(self):
        """With blank allowed, ExtJS's validate-on-blur would clear the mark
        the panel's isValid() put on the combo; a validator carrying the same
        rule -- a type is needed exactly when a relevant file is attached --
        keeps ExtJS and the panel in agreement."""
        for line, config in combo_configs(self.source, "relevantFileTypeSelector"):
            self.assertRegex(config, r"validator:\s*function",
                             "relevantFileTypeSelector at %d has no validator" % line)
            self.assertIn('queryById("secondaryFileSelector")', config)
            self.assertIn("Please, specify a File type.", config)

    def test_the_file_type_lists_are_filtered_locally(self):
        """A sixteen-row static list: the default remote queryMode re-fetched
        file_types.json on every dropdown open and every typed query."""
        for item_id in COMBO_ITEM_IDS:
            for line, config in combo_configs(self.source, item_id):
                self.assertRegex(config, r"queryMode:\s*['\"]local['\"]",
                                 "%s at %d queries remotely" % (item_id, line))

    def test_the_omic_name_check_reads_null_as_blank(self):
        """Type an omic name and delete it: the combo's value is null, not "",
        and the old `=== ""` let checkForm() pass a form ExtJS then refused
        with no field named."""
        is_valid = self.source[self.source.index("isValid: function() {"):]
        is_valid = is_valid[:is_valid.index("isEmpty: function() {")]
        self.assertIn('Ext.isEmpty(this.queryById("omicNameField").getValue())', is_valid)
        self.assertNotIn('queryById("omicNameField").getValue() === ""', is_valid)


class AClientSideAbortNamesTheField(unittest.TestCase):

    def test_extjs_error_handler_names_the_field_on_a_client_abort(self):
        """ExtJS's submit() runs form.isValid() again and, refusing, calls the
        failure handler with failureType "client" and no response. That must
        read like checkForm()'s refusal -- the field and its reason -- not
        like a server fault."""
        util = read(UTIL_JS)
        handler = util[util.index("function extJSErrorHandler(form, responseObj)"):]
        handler = handler[:handler.index("\n}\n")]
        self.assertIn("Ext.form.action.Action.CLIENT_INVALID", handler)
        self.assertIn("form.getFields()", handler)
        self.assertIn("Invalid Form.", handler)
        self.assertNotIn("Please try again later", handler.split("CLIENT_INVALID")[0],
                         "the client-abort branch must come before the server fallback")


if __name__ == "__main__":
    unittest.main()
