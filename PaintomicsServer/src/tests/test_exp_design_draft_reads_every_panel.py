#!/usr/bin/env python3
""""Draft this for me" must read the files of every omic panel, MORE included.

The behaviour this guards
-------------------------
Step 1's "Draft this for me" writes an experiment-design description from the
header row of the files the user has picked. `collectPickedOmicFiles()` used to
keep only fields whose NAME matched `/^omic\\d+_file$/`:

    if (!/^omic\\d+_file$/.test(name)) { return; }

That is the naming convention of the plain, region-based and miRNA panels. It
is not the MORE panel's: MORE calls its five selectors `conditions`,
`rnaseqaux`, `file_0`, `relevant_file_0` and `assoc_file_0`, so their runtime
field names are `conditions_file`, `rnaseqaux_file`, `file_0_file` and so on,
and not one of them matched.

So a user who filled in a Regulatory Omic panel and nothing else collected
NOTHING, and the button answered

    "There is nothing to read yet. Add an omic under 3. Choose the files to
     upload and pick its Data file, then press Draft this for me again."

to someone who had done exactly that. Reported 2026-08-26, by the same user as
the Invalid Form report. Measured in Chrome with her four real files plus a
region-based file on the same form: five files picked, one collected.

The file it most wanted was the one it could not see -- for a MORE run the
conditions file *is* the experimental design.

The fix takes every picked file (one header row each costs nothing) and labels
it from the component tree instead of the field name, so a fifth panel type
cannot go blind the same way.

Why node runs a browser file
----------------------------
The client has no test harness of its own. The three functions are lifted out
of PA_Step1Views.js as shipped and driven against stand-ins for the panels and
the file inputs -- the pattern of test_step1_drops_empty_omic_panels and
test_organism_search.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_exp_design_draft_reads_every_panel
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

CLIENT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "PaintomicsClient", "public_html"))
STEP1_VIEWS = os.path.join(
    CLIENT_ROOT, "app", "view", "PathwayAcquisitionViews", "PA_Step1Views.js")

BLOCK_HEADERS = {
    "plainFieldLabel": "function plainFieldLabel(text) {",
    "typedOmicName": "function typedOmicName(panel, field) {",
    "pickedFileLabel": "function pickedFileLabel(field) {",
    "collectPickedOmicFiles": "function collectPickedOmicFiles() {",
}
MAX_FILES_STATEMENT = "var EXP_DESIGN_MAX_FILES ="


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _scan(source, start, stop):
    """Walk from `start`, skipping strings, comments and regex literals."""
    index, depth, length = start, 0, len(source)
    while index < length:
        char = source[index]
        if char in "\"'":
            quote = char
            index += 1
            while index < length and source[index] != quote:
                index += 2 if source[index] == "\\" else 1
        elif source.startswith("//", index):
            index = source.find("\n", index)
            if index == -1:
                break
            continue
        elif source.startswith("/*", index):
            index = source.index("*/", index) + 1
        else:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            if stop(char, depth):
                return index
        index += 1
    raise AssertionError("ran off the end from offset %d" % start)


def extract_block(source, header):
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from PA_Step1Views.js" % header)
    opening = source.index("{", start + len(header) - 1)
    end = _scan(source, opening, lambda char, depth: char == "}" and depth == 0)
    return source[start:end + 1]


def extract_statement(source, header):
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from PA_Step1Views.js" % header)
    end = _scan(source, start, lambda char, depth: char == ";" and depth == 0)
    return source[start:end + 1]


# The four panel types with their REAL field names and labels, so the test
# fails if the shipped naming and this drift apart.
HARNESS = """
var ALL_FIELDS = [];

var Ext = {
    each: function (list, fn) {
        for (var i = 0; i < list.length; i++) { if (fn(list[i], i) === false) { break; } }
    },
    ComponentQuery: {
        query: function (selector) {
            if (selector !== 'filefield') { throw new Error(selector); }
            return ALL_FIELDS;
        }
    }
};

/* nameFields: the #omicNameField list the panel answers query() with -- a
   region or pairwise card really holds two, the first disabled and empty.
   blocks: MORE's omic_name_<i> combos by index. */
function makePanel(cls, heading, omicNameValue, type, extra) {
    extra = extra || {};
    var nameFields = extra.nameFields || (omicNameValue === null ? [] :
        [{disabled: false, getValue: function () { return omicNameValue; }}]);
    var panel = {
        cls: cls,
        type: type,
        ownerCt: null,
        query: function (selector) {
            if (selector === '#omicNameField') { return nameFields; }
            var block = selector.match(/^\[name=omic_name_(\d+)\]$/);
            if (block) {
                var typed = (extra.blocks || {})[block[1]];
                return typed === undefined ? [] : [{getValue: function () { return typed; }}];
            }
            throw new Error(selector);
        },
        el: {dom: {querySelector: function (selector) {
            if (selector !== '.omicboxTitle h4') { throw new Error(selector); }
            return heading === null ? null : {textContent: heading};
        }}}
    };
    return panel;
}

function addSelector(panel, fieldLabel, fieldName, pickedFileName, itemId) {
    var selector = {xtype: 'myFilesSelectorButton', fieldLabel: fieldLabel, ownerCt: panel, itemId: itemId};
    var field = {
        xtype: 'filefield',
        name: fieldName,
        ownerCt: selector,
        fileInputEl: {dom: {files: pickedFileName ? [{name: pickedFileName}] : []}},
        up: function (query) {
            var node = field.ownerCt;
            while (node) {
                if (query === 'myFilesSelectorButton' && node.xtype === 'myFilesSelectorButton') { return node; }
                if (query === '[cls~=omicbox]' && node.cls &&
                    node.cls.split(' ').indexOf('omicbox') !== -1) { return node; }
                node = node.ownerCt;
            }
            return null;
        }
    };
    ALL_FIELDS.push(field);
    return field;
}

%(plainFieldLabel)s
%(typedOmicName)s
%(pickedFileLabel)s
%(EXP_DESIGN_MAX_FILES)s
%(collectPickedOmicFiles)s

function run(build) {
    ALL_FIELDS = [];
    build();
    var threw = null, picked = null;
    try { picked = collectPickedOmicFiles(); } catch (e) { threw = String(e && e.stack || e); }
    return {
        threw: threw,
        picked: picked && picked.map(function (p) { return {label: p.omicName, file: p.file.name}; })
    };
}

var results = {};

/* The MORE panel exactly as the view builds it: five selectors, none of whose
   field names match the old /^omic\\d+_file$/. The four files are the ones the
   reporting user uploaded. */
function buildMore(withFiles) {
    var more = makePanel('omicbox moreBasedOmic', 'Regulatory Omic - MORE', 'miRNA-Seq data', 'moreanalysis');
    addSelector(more, 'Conditions file', 'conditions_file', withFiles ? 'samplemetadata_miRNA.csv' : null);
    addSelector(more, 'Gene expression dataset', 'rnaseqaux_file', withFiles ? 'DEGs2.txt' : null);
    addSelector(more, 'Regulators expression file', 'file_0_file', withFiles ? 'DEmiRNA.txt' : null);
    addSelector(more, 'Relevant regulators file<br>(optional)', 'relevant_file_0_file', null);
    addSelector(more, 'Associations file', 'assoc_file_0_file', withFiles ? 'Targets3.txt' : null);
    return more;
}

// The report: a MORE panel and nothing else.
results.moreOnly = run(function () { buildMore(true); });

// Every panel type at once -- the three that already worked must keep working.
results.everyPanel = run(function () {
    var gene = makePanel('omicbox', 'Gene expression', '', 'geneexpression');
    addSelector(gene, 'Data file:', 'omic0_file', 'gene_expression_values.tab');
    addSelector(gene, 'Relevant features file:', 'omic0_relevant_file', 'gene_expression_relevant.tab');

    var region = makePanel('omicbox regionBasedOmic', 'Region-based omic', '', undefined);
    addSelector(region, 'Regions file (BED + Quantification):', 'omic3_file', 'dnase_regions_values.tab');
    addSelector(region, 'Annotations file (GTF):', 'omic3_annotations_file', 'synthetic_mmu.gtf');

    var mirna = makePanel('omicbox miRNABasedOmic', 'Regulatory Omic - Pairwise', 'miRNA-seq', undefined);
    addSelector(mirna, 'Data file:', 'omic2_file', 'mirna_values.tab');

    buildMore(true);
});

// Nothing chosen anywhere.
results.nothingPicked = run(function () { buildMore(false); });

// A form cannot hand over an unbounded number of files.
results.capped = run(function () {
    var panel = makePanel('omicbox', 'Other data type', '', 'otheromic');
    for (var i = 0; i < 40; i++) {
        addSelector(panel, 'Data file:', 'omic' + i + '_file', 'file' + i + '.tab');
    }
});

// No omic name typed: fall back to the heading the panel prints.
results.headingFallback = run(function () {
    var panel = makePanel('omicbox regionBasedOmic', 'Region-based omic', '', undefined);
    addSelector(panel, 'Regions file (BED + Quantification):', 'omic1_file', 'regions.tab');
});

// Neither a name nor a heading: the slot alone still says something.
results.slotOnly = run(function () {
    var panel = makePanel('omicbox', null, null, '');
    addSelector(panel, 'Data file:', 'omic1_file', 'orphan.tab');
});

// A region card holds two #omicNameField: the disabled, empty twin of the
// "already mapped" form comes FIRST, and down() used to return it.
results.twinNameFields = run(function () {
    var panel = makePanel('omicbox regionBasedOmic', 'Region-based omic', null, undefined, {
        nameFields: [{disabled: true, getValue: function () { return ""; }},
                     {disabled: false, getValue: function () { return "ATAC-seq"; }}]});
    addSelector(panel, 'Regions file (BED + Quantification):', 'omic1_file', 'peaks.bed');
});
// MORE's second regulator has its own omic_name_1 combo and no itemId at all;
// its files were labelled with regulator 0's name. The conditions and gene
// expression files belong to the panel, not to a regulator.
results.moreSecondRegulator = run(function () {
    var more = makePanel('omicbox moreBasedOmic', 'Regulatory Omic - MORE', 'miRNA-seq', 'moreanalysis',
                         {blocks: {"0": "miRNA-seq", "1": "Transcription factor"}});
    addSelector(more, 'Conditions file', 'conditions_file', 'design.tab');
    addSelector(more, 'Regulators expression file', 'file_0_file', 'mirna.tab');
    addSelector(more, 'Regulators expression file', 'file_1_file', 'tf.tab');
});
// The region panel's GTF is annotation rows, not column names: never sent.
results.gtfSkipped = run(function () {
    var panel = makePanel('omicbox regionBasedOmic', 'Region-based omic', 'DNase', undefined);
    addSelector(panel, 'Regions file (BED + Quantification):', 'omic1_file', 'regions.tab', 'mainFileSelector');
    addSelector(panel, 'Annotations file (GTF):', 'omic1_annotations_file', 'mmu.gtf', 'tertiaryFileSelector');
});
console.log(JSON.stringify(results));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-draft-collect-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        completed = subprocess.run(["node", path], capture_output=True,
                                   text=True, timeout=60)
        if completed.returncode != 0:
            raise AssertionError("node failed:\n%s" % completed.stderr)
        return json.loads(completed.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class DraftReadsEveryPanelTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = read(STEP1_VIEWS)
        pieces = {name: extract_block(source, header)
                  for name, header in BLOCK_HEADERS.items()}
        pieces["EXP_DESIGN_MAX_FILES"] = extract_statement(source, MAX_FILES_STATEMENT)
        cls.results = run_node(HARNESS % pieces)

    def files(self, name):
        return [entry["file"] for entry in self.results[name]["picked"]]

    def labels(self, name):
        return [entry["label"] for entry in self.results[name]["picked"]]

    def test_it_runs(self):
        for name, result in self.results.items():
            self.assertIsNone(result["threw"], "%s: %s" % (name, result["threw"]))

    def test_a_more_panel_on_its_own_is_read(self):
        """The reported bug, in one assertion: this used to collect nothing."""
        self.assertEqual(self.files("moreOnly"),
                         ["samplemetadata_miRNA.csv", "DEGs2.txt",
                          "DEmiRNA.txt", "Targets3.txt"])

    def test_the_conditions_file_is_named_as_what_it_is(self):
        """It is the experimental design; the drafter has to know that."""
        self.assertEqual(self.labels("moreOnly")[0],
                         "Regulatory Omic - MORE / Conditions file")

    def test_markup_never_reaches_the_label(self):
        for name in self.results:
            for label in self.labels(name):
                self.assertNotIn("<", label)
                self.assertNotIn(">", label)

    def test_the_panels_that_already_worked_still_do(self):
        self.assertEqual(self.files("everyPanel"), [
            "gene_expression_values.tab", "gene_expression_relevant.tab",
            "dnase_regions_values.tab", "synthetic_mmu.gtf",
            "mirna_values.tab",
            "samplemetadata_miRNA.csv", "DEGs2.txt", "DEmiRNA.txt", "Targets3.txt",
        ])

    def test_an_unpicked_selector_is_skipped(self):
        self.assertEqual(self.files("nothingPicked"), [])
        self.assertNotIn("relevant_file_0_file",
                         " ".join(self.labels("moreOnly")))

    def test_the_number_of_files_is_bounded(self):
        self.assertEqual(len(self.files("capped")), 24)

    def test_the_label_falls_back_to_the_panel_heading(self):
        self.assertEqual(self.labels("headingFallback"),
                         ["Region-based omic / Regions file (BED + Quantification)"])

    def test_the_typed_name_wins_over_the_disabled_twin(self):
        labels = [p["label"] for p in self.results["twinNameFields"]["picked"]]
        self.assertEqual(labels, ["ATAC-seq / Regions file (BED + Quantification)"])

    def test_each_more_regulator_carries_its_own_name(self):
        labels = [p["label"] for p in self.results["moreSecondRegulator"]["picked"]]
        self.assertEqual(labels, ["Regulatory Omic - MORE / Conditions file",
                                  "miRNA-seq / Regulators expression file",
                                  "Transcription factor / Regulators expression file"])

    def test_the_gtf_is_never_sent(self):
        files = [p["file"] for p in self.results["gtfSkipped"]["picked"]]
        self.assertEqual(files, ["regions.tab"])

    def test_the_server_keeps_every_entry_the_client_can_send(self):
        """The server cap was 10 against a client cap of 24: entries 11+ were
        silently dropped and the note under the button said nothing."""
        client = read(STEP1_VIEWS) if "STEP1_VIEWS" in globals() else read(SOURCE)
        server = read(os.path.join(os.path.dirname(__file__), "..", "servlets", "AIInterpretServlet.py"))
        clientCap = int(re.search(r"var EXP_DESIGN_MAX_FILES = (\d+);", client).group(1))
        serverCap = int(re.search(r"_EXPDESIGN_MAX_OMICS = (\d+)", server).group(1))
        self.assertGreaterEqual(serverCap, clientCap)

    def test_a_panel_with_no_identity_still_labels_the_slot(self):
        self.assertEqual(self.labels("slotOnly"), ["Data file"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
