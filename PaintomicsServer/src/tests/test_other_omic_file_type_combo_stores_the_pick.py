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
    inside a helpTip or a block comment cannot fool a brace walker.

    Known limit: a regex literal containing a quote (/'/) or a template literal
    would open a phantom string; the scan is scoped to the plain panel's
    constructor, which has neither."""
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


def combo_configs(source, item_id, span=None):
    """(line_number, config_text) for every *combo* whose `itemId` is
    `item_id`, looking only inside `span` (start, end) when given; at least
    one, or the test that asked cannot pass vacuously. Line numbers count
    from the top of the file, whatever the span.

    The named panels (Region-based, miRNA, MORE) carry a hidden `textfield`
    under the same itemId with a preset value; those never read
    file_types.json and are skipped."""
    start, end = span if span else (0, len(source))
    masked = mask_strings_and_comments(source[start:end])
    found = []
    for match in re.finditer(r'itemId:\s*"%s"' % re.escape(item_id), source[start:end]):
        config = enclosing_object(source[start:end], match.start(), masked)
        if not re.search(r"xtype:\s*['\"]combo(box)?['\"]", config):
            continue
        found.append((source.count("\n", 0, start + match.start()) + 1, config))
    if not found:
        raise AssertionError("no combo with itemId %s" % item_id)
    return found


def plain_panel_span(source):
    """(start, end) of the OmicSubmittingPanel constructor: the one panel whose
    File Type combos are visible, and the scope every scan here is anchored
    to so a quote or brace elsewhere in the file cannot shift it."""
    start = source.index("function OmicSubmittingPanel(nElem, options) {")
    return start, source.index("\nOmicSubmittingPanel.prototype", start)


def between(source, start_marker, end_marker):
    start = source.index(start_marker)
    return source[start:source.index(end_marker, start)]


def combo_declarations(source, item_id, span=None):
    """Yield (line_number, displayField, valueField) for every combo whose
    `itemId` is `item_id`."""
    for line, config in combo_configs(source, item_id, span):
        display = re.search(r"displayField:\s*" + QUOTED, config)
        value = re.search(r"valueField:\s*" + QUOTED, config)
        yield (line,
               display.group(1) if display else None,
               value.group(1) if value else None)


class TheBraceWalkerReadsTheSourceLikeAParserTest(unittest.TestCase):

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


class FileTypeComboStoresThePickTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.full = read(STEP1_VIEWS)
        cls.span = plain_panel_span(cls.full)
        cls.source = cls.full[cls.span[0]:cls.span[1]]
        cls.records = json.loads(read(FILE_TYPES))["types"]
        if not cls.records:
            raise AssertionError("file_types.json has no records")

    def configs(self, item_id):
        return combo_configs(self.full, item_id, self.span)

    def test_every_file_type_combo_stores_a_column_the_records_have(self):
        """Whatever column valueField names must exist on every record, or
        every pick from the list is stored as undefined -> null."""
        columns = set.intersection(*(set(r) for r in self.records))
        for item_id in COMBO_ITEM_IDS:
            for line, _display, value in combo_declarations(self.full, item_id, self.span):
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
            for line, display, value in combo_declarations(self.full, item_id, self.span):
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
        for line, config in self.configs("relevantFileTypeSelector"):
            self.assertNotRegex(
                config, r"allowBlank:\s*false",
                "relevantFileTypeSelector at PA_Step1Views.js:%d is "
                "allowBlank: false, so a panel with no relevant file cannot "
                "be submitted" % line)

    def test_a_line_number_in_a_failure_points_into_the_file(self):
        line, _config = self.configs("fileTypeSelector")[0]
        self.assertEqual(self.full.split("\n")[line - 1].strip(),
                         """xtype: 'combo', itemId: "fileTypeSelector",""")

    def test_a_whitespace_only_name_or_type_is_blank(self):
        """A single space typed into the Omic Name or the File Type box is
        not a value; it would have been posted and become the omic's or the
        file's label. The relevant File Type is blank-allowed (its file is
        optional), so there its validator does the trimming."""
        for item_id in ("omicNameField", "fileTypeSelector"):
            for line, config in self.configs(item_id):
                self.assertRegex(config, r"allowOnlyWhitespace:\s*false",
                                 "%s at %d accepts whitespace" % (item_id, line))
        for _line, config in self.configs("relevantFileTypeSelector"):
            self.assertIn("Ext.String.trim(", config)
        is_valid = between(self.source, "isValid: function() {", "isEmpty: function() {")
        self.assertIn('Ext.isEmpty(Ext.String.trim(this.queryById("omicNameField").getValue() || ""))', is_valid)

    def test_the_four_panels_share_one_field_validation(self):
        """Every field, not up to the first failure: the sibling loops
        `valid = valid && (...validate())` stopped marking after the first
        invalid field, so a user was refused twice for two mistakes."""
        self.assertIn("function validateAllFields(container)", self.full)
        helper = between(self.full, "function validateAllFields(container)", "\n}\n")
        self.assertIn("Ext.suspendLayouts();", helper)
        self.assertIn("Ext.resumeLayouts(true);", helper)
        self.assertEqual(self.full.count("validateAllFields("), 5,
                         "one definition and four isValid() call sites")
        self.assertNotIn("valid = valid && (this.items[i] || items[i].validate());", self.full)

    def test_the_relevant_file_type_keeps_its_own_rule_for_extjs(self):
        """With blank allowed, ExtJS's validate-on-blur would clear the mark
        the panel's isValid() put on the combo; a validator carrying the same
        rule -- a type is needed exactly when a relevant file is attached --
        keeps ExtJS and the panel in agreement."""
        for line, config in self.configs("relevantFileTypeSelector"):
            self.assertRegex(config, r"validator:\s*function",
                             "relevantFileTypeSelector at %d has no validator" % line)
            self.assertIn('queryById("secondaryFileSelector")', config)
            self.assertIn("Please, specify a File type.", config)

    def test_the_file_type_lists_are_filtered_locally(self):
        """A sixteen-row static list: the default remote queryMode re-fetched
        file_types.json on every dropdown open and every typed query."""
        for item_id in COMBO_ITEM_IDS:
            for line, config in self.configs(item_id):
                self.assertRegex(config, r"queryMode:\s*['\"]local['\"]",
                                 "%s at %d queries remotely" % (item_id, line))

    def test_the_omic_name_check_reads_null_as_blank(self):
        """Type an omic name and delete it: the combo's value is null, not "",
        and the old `=== ""` let checkForm() pass a form ExtJS then refused
        with no field named."""
        is_valid = between(self.source, "isValid: function() {", "isEmpty: function() {")
        self.assertIn('Ext.isEmpty(Ext.String.trim(this.queryById("omicNameField").getValue() || ""))', is_valid)
        self.assertNotIn('queryById("omicNameField").getValue() === ""', is_valid)

    def test_the_panel_runs_extjs_validation_before_its_own_checks(self):
        """Like the Region-based, miRNA and MORE panels, isValid() validates
        every field first, so a maxLength or an allowBlank refuses through
        checkForm() -- named and scrolled into view -- and the failure
        handler's client-abort branch stays the last resort."""
        is_valid = between(self.source, "isValid: function() {", "isEmpty: function() {")
        self.assertIn("validateAllFields(this)", is_valid)


class AClientSideAbortNamesTheFieldTest(unittest.TestCase):

    def test_extjs_error_handler_names_the_field_on_a_client_abort(self):
        """ExtJS's submit() runs form.isValid() again and, refusing, calls the
        failure handler with failureType "client" and no response. That must
        read like checkForm()'s refusal -- the field and its reason -- not
        like a server fault."""
        util = read(UTIL_JS)
        handler = between(util, "function extJSErrorHandler(form, responseObj)", "\n}\n")
        self.assertIn("Ext.form.action.Action.CLIENT_INVALID", handler)
        self.assertIn("showInvalidFieldMessage(", handler)
        self.assertNotIn("Please try again later", handler.split("CLIENT_INVALID")[0],
                         "the client-abort branch must come before the server fallback")

    def test_the_client_abort_survives_a_destroyed_form_and_names_no_hidden_field(self):
        """The complex-path caller destroys its temporary form before calling
        the handler (getFields() would throw), and a hidden field must never
        be the one named -- both fall through to the generic wording."""
        util = read(UTIL_JS)
        handler = between(util, "function extJSErrorHandler(form, responseObj)", "\n}\n")
        self.assertIn("form.monitor", handler)
        # DOM order, like checkForm()'s refusal: the form's Monitor keeps
        # insertion order, and a container put back on the form lands last.
        self.assertIn('form.owner.query("field")', handler)
        self.assertIn("firstVisibleInvalidField(", handler)
        helper = between(util, "function firstVisibleInvalidField(fields)", "\n}\n")
        self.assertIn("isVisible(true)", helper)
        self.assertIn("getEl()", helper)
        views = read(STEP1_VIEWS)
        first = between(views, "this.firstFormError = function() {", "\n\t};")
        self.assertIn("firstVisibleInvalidField(", first,
                      "checkForm()'s refusal and the client-abort branch pick the field the same way")

    def test_the_complex_path_routes_a_client_abort_to_the_named_refusal(self):
        """The Region-based, miRNA and MORE panels submit through a temporary
        form that their failure handler destroys before anything else runs;
        its fields are back on the main form by then, where checkForm()'s
        refusal knows how to name one."""
        controller = read(os.path.join(CLIENT_ROOT, "app", "controller", "JobController.js"))
        handler = between(controller, "_restoreElements();\n\n", "extJSErrorHandler(form, responseObj);")
        self.assertIn("Ext.form.action.Action.CLIENT_INVALID", handler)
        self.assertIn("showInvalidStep1FormMessage(jobView)", handler)

    def test_one_refusal_dialog_serves_checkform_and_extjs(self):
        """checkForm()'s refusal and the client-abort branch quote the field
        the same way, from one helper that also scrolls it into view."""
        util = read(UTIL_JS)
        self.assertIn("function showInvalidFieldMessage(field)", util)
        self.assertIn("function plainFieldText(html)", util)
        self.assertIn("function fieldErrorText(field)", util)
        helper = between(util, "function showInvalidFieldMessage(field)", "\n}\n")
        self.assertIn("scrollIntoView", helper)
        controller = read(os.path.join(CLIENT_ROOT, "app", "controller", "JobController.js"))
        refusal = between(controller, "function showInvalidStep1FormMessage(jobView)", "\n}\n")
        self.assertIn("showInvalidFieldMessage(", refusal)
        self.assertNotIn("function plainFieldText", controller)
        # step1FailureReason stays self-contained: its own test lifts it into
        # node verbatim, where no Util.js global exists.


if __name__ == "__main__":
    unittest.main()
