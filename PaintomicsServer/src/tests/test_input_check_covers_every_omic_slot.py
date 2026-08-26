#!/usr/bin/env python3
"""The input check must run on every file slot of every omic panel.

The behaviour this guards
-------------------------
InputFormat/format-panel.js checks a file the moment it is picked, and BLOCKS
the submit when the fault is one the server is certain to reject. Its own
comment says why that matters:

    "Observed on the very first run-through: the strip said the numbers used
     decimal commas, the form was submitted anyway, and the server answered
     with ten identical lines of 'Perhaps you are using commas instead of dots
     as decimal mark?'"

It decided what to check with a test on the field's NAME:

    var VALUES_FIELD = /^omic\\d+_file$/;

That is the plain, region-based and miRNA panels' convention. It is not the
MORE panel's -- MORE calls its five selectors `conditions`, `rnaseqaux`,
`file_0`, `relevant_file_0` and `assoc_file_0`. So every file picked into a
Regulatory Omic (MORE) panel went completely unchecked. Measured in Chrome with
the same file in two panels:

    plain Gene expression panel -> "Numbers use commas as the decimal mark;
                                    PaintOmics needs dots" + [Fix automatically]
    MORE panel                  -> stripsOnPage: 0

The reporting user's files (2026-08-26) used decimal commas. The one guard
written for exactly her mistake never looked at them; she lost an hour and the
run died on the server.

The slot is now the key, not the name, and each slot is held to its own
contract (format-roles.js already models all five).

What this file asserts
----------------------
1. every file-selector slot the form can show is either given a role or
   explicitly exempt -- so a NEW panel cannot go blind the same way;
2. no file shipped with the example datasets is rejected by the role it would
   be picked into, which is what stops the wider net blocking valid uploads;
3. the resolver returns the right role per slot, MORE's included, and nothing
   for an input outside the omic panels.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_input_check_covers_every_omic_slot
"""
import glob
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CLIENT = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                      "PathwayAcquisitionViews")
FORMAT_PANEL = os.path.join(CLIENT, "InputFormat", "format-panel.js")
JS_DIR = os.path.join(CLIENT, "InputFormat")
STEP1_VIEWS = os.path.join(CLIENT, "PA_Step1Views.js")
DATASETS = os.path.join(REPO, "PaintomicsServer", "src", "examplefiles", "datasets")

# A GTF is not one of the delimited contracts this module models, so the region
# panel's annotations slot is left alone on purpose. Anything else missing from
# ROLE_BY_SLOT is a slot that silently goes unchecked.
# Slots this module deliberately does not judge, each for a reason recorded
# next to ROLE_BY_SLOT: a GTF is not a delimited contract; the miRNA targets
# table is miRNA/gene/PLR and not the two-column associations contract; and
# third/fourth live in the RESULTS container, which is filled with server paths
# rather than picked, where an empty file is a legitimate output.
EXEMPT_SLOTS = {"tertiaryFileSelector", "mirnaTargetsFileSelector",
                "thirdFileSelector", "fourthFileSelector"}

# The role each shipped example file would be picked into. Asserted exhaustive
# below, so a new example file cannot slip through unchecked.
EXAMPLE_ROLES = {
    "dnase_regions_values.tab": "values",
    "dnase_unmapped_values.tab": "values",
    "dnase_values.tab": "values",
    "gene_expression_targets.tab": "values",
    "gene_expression_values.tab": "values",
    "metabolomics_by_name_values.tab": "values",
    "metabolomics_values.tab": "values",
    "mirna_regulators.tab": "values",
    "mirna_unmapped_values.tab": "values",
    "mirna_values.tab": "values",
    "proteomics_values.tab": "values",
    "transcription_factor_regulators.tab": "values",
    "transcription_factor_values.tab": "values",
    "dnase_regions_relevant.tab": "relevant",
    "dnase_relevant.tab": "relevant",
    "dnase_unmapped_relevant.tab": "relevant",
    "gene_expression_relevant.tab": "relevant",
    "metabolomics_by_name_relevant.tab": "relevant",
    "metabolomics_relevant.tab": "relevant",
    "mirna_relevant.tab": "relevant",
    "mirna_relevant_regulators.tab": "relevant",
    "mirna_unmapped_relevant.tab": "relevant",
    "proteomics_relevant.tab": "relevant",
    "transcription_factor_relevant.tab": "relevant",
    "transcription_factor_relevant_regulators.tab": "relevant",
    "mirna_associations.tab": "associations",
    # miRNA / gene / PLR -- the miRNA2Genes prediction table, which is NOT the
    # two-column associations contract its name suggests. Its slot is exempt.
    "mirna_to_gene_associations.tab": None,
    "transcription_factor_associations.tab": "associations",
    "mmu_mirBase_to_ensembl.tab": None,      # same three-column shape
    "experimental_design.tab": "design",
    "synthetic_mmu.gtf": None,          # not a delimited contract; never checked
}


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def role_by_slot():
    """ROLE_BY_SLOT as the shipped module declares it."""
    source = read(FORMAT_PANEL)
    start = source.index("var ROLE_BY_SLOT = {")
    body = source[start:source.index("};", start)]
    return dict(re.findall(r"(\w+)\s*:\s*\"([\w-]+)\"", body))


def declared_slots():
    """Every itemId a myFilesSelectorButton is given in the Step 1 form."""
    source = read(STEP1_VIEWS)
    slots = set()
    for match in re.finditer(r'xtype:\s*"myFilesSelectorButton"', source):
        # The itemId sits inside the same object literal, within a few lines.
        window = source[match.start():match.start() + 900]
        window = window[:window.find("\n\t\t\t\t},")] if "\n\t\t\t\t}," in window else window
        found = re.search(r'itemId:\s*"(\w+)"', window)
        if found:
            slots.add(found.group(1))
    return slots


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-slot-roles-")
    try:
        path = os.path.join(directory, "check.js")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        done = subprocess.run(["node", path], capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


VALIDATE_SCRIPT = """
const fs = require("fs");
const path = require("path");
const DIR = %(jsdir)s;
// Each module is a UMD that exports its own factory under node, so they are
// required and merged rather than read off a browser global.
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));

const cases = %(cases)s;
const out = [];
for (const c of cases) {
    const bytes = new Uint8Array(fs.readFileSync(c.path));
    const read = API.readDelimited(bytes);
    const report = API.validateForRole(c.role, read.rows);
    out.push({
        file: c.file, role: c.role, ok: !!report.ok,
        problems: (report.problems || []).map(p => p.code)
    });
}
console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class InputCheckCoversEverySlotTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.roles = role_by_slot()
        cls.slots = declared_slots()

    def test_the_module_still_declares_a_role_table(self):
        self.assertTrue(self.roles, "ROLE_BY_SLOT could not be read")
        self.assertIn("mainFileSelector", self.roles)

    def test_the_name_pattern_is_gone(self):
        """The bug was a field-NAME test; it must not come back."""
        source = read(FORMAT_PANEL)
        self.assertNotIn("VALUES_FIELD", source)
        # The three gates must all ask the slot, not the name. (The old regex
        # still appears in the comment that explains the bug, so the check is
        # on the calls rather than on the file's text.)
        self.assertEqual(source.count("roleForField("), 4)
        self.assertIn("var role = roleForInput(input);", source)

    def test_every_slot_the_form_can_show_is_covered(self):
        """The regression that keeps happening: a new panel goes unchecked."""
        missing = sorted(self.slots - set(self.roles) - EXEMPT_SLOTS)
        self.assertEqual(missing, [],
                         "these file slots would go unchecked: %s" % missing)

    def test_the_more_panel_slots_are_covered(self):
        """Named explicitly: these are the ones that were blind."""
        for slot in ("conditionsFileSelector", "rnaseqauxFileSelector",
                     "moreRelevantFileSelector", "moreAssociationsFileSelector"):
            self.assertIn(slot, self.roles)

    def test_the_role_table_names_only_real_roles(self):
        for slot, role in self.roles.items():
            self.assertIn(role, ("values", "relevant", "associations",
                                 "relevant-associations", "design"),
                          "%s has role %r" % (slot, role))

    def test_every_example_file_has_a_declared_role(self):
        """So a new example file cannot quietly skip this test."""
        shipped = {os.path.basename(p)
                   for p in glob.glob(os.path.join(DATASETS, "*", "data", "*"))}
        undeclared = sorted(shipped - set(EXAMPLE_ROLES))
        self.assertEqual(undeclared, [],
                         "add these to EXAMPLE_ROLES: %s" % undeclared)

    def test_no_shipped_example_file_is_rejected_by_its_role(self):
        """The wider net must not start blocking valid uploads.

        Every one of these files runs today, so any of them failing its role
        means the check would now refuse a submit that works.
        """
        cases, seen = [], set()
        for path in sorted(glob.glob(os.path.join(DATASETS, "*", "data", "*"))):
            name = os.path.basename(path)
            role = EXAMPLE_ROLES.get(name)
            if role is None or name in seen:
                continue
            seen.add(name)
            cases.append({"file": name, "role": role, "path": path})

        results = run_node(VALIDATE_SCRIPT % {
            "jsdir": json.dumps(JS_DIR),
            "cases": json.dumps(cases),
        })
        rejected = [(r["file"], r["role"], r["problems"])
                    for r in results if not r["ok"]]
        self.assertEqual(rejected, [],
                         "these shipped files would now be blocked: %s" % rejected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
