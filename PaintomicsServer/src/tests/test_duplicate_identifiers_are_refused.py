#!/usr/bin/env python3
"""A repeated identifier must be caught before the submit, not by the R backend.

The behaviour this guards
-------------------------
A user's MORE run died on the server with:

    MORE ERROR: no data columns could be read from mirna_values.tab.
    Tried tab and comma separators.
    (tab: duplicate 'row.names' are not allowed: 'ENSMUSG00000092770')

The file has 1803 data rows and 503 distinct identifiers; one appears 65 times.
Both engines reject it -- runMORE.R reads with row.names=1, and the Rust port
reproduces the rejection deliberately (MORE/rust/src/data.rs) -- so switching
engines does not help.

The client-side check passed it. Fifteen problem codes across five roles and
not one of them looked at whether an identifier repeats, so the file got a
green tick reading "1,803 rows - 2 columns" and, because the strip only offers
the AI when it has a problem to offer it for, **the "Convert it for me" button
never appeared**. The AI agent that could have asked about the duplicates was
never reachable. That was the whole chain: no rule -> green tick -> no offer ->
the server dies.

The rule already existed and worked, in convert-agent.js, where it has graded
the AI's own output since the converter shipped. It just never ran on a file
the user picked themselves. It now lives in format-roles.js and runs for every
role whose identifier has to be unique.

Uniqueness is required for `values` and `design` and NOT for the association
roles, where many regulators to one target is the entire point of the file.
Getting that wrong in the other direction would refuse every valid
associations file in the repository.

No mechanical repair is offered. Measured on this file, 315 of 315 duplicate
groups disagree on their values and 165 span both signs -- they are distinct
miRNAs collapsed onto a host-gene Ensembl id, not repeated measurements -- so
averaging or taking the first would produce a file that runs and is wrong.
The refusal names the numbers and hands the question to the AI agent, which
asks what the duplicates mean instead of assuming.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_duplicate_identifiers_are_refused
"""
import glob
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
JS_DIR = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                      "PathwayAcquisitionViews", "InputFormat")
DATASETS = os.path.join(REPO, "PaintomicsServer", "src", "examplefiles", "datasets")

SCRIPT = """
const path = require("path");
const DIR = %(dir)s;
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));

const H = ["#gene", "s1", "s2"];
const clean  = [H, ["G1","1","2"], ["G2","3","4"], ["G3","5","6"]];
const dupes  = [H, ["G1","1","2"], ["G2","3","4"], ["G1","9","9"], ["G1","7","7"]];
const design = [["Sample","A","B"], ["s1","1","0"], ["s2","0","1"]];
const dupDesign = [["Sample","A","B"], ["s1","1","0"], ["s1","0","1"]];
// chr/start/end: column 0 repeats legitimately on every region of a chromosome.
const regions = [["chr","start","end","v"],
                 ["chr1","100","200","1"], ["chr1","300","400","2"],
                 ["chr1","500","600","3"]];
const dupRegions = [["chr","start","end","v"],
                    ["chr1","100","200","1"], ["chr1","100","200","2"]];
// Many regulators to one target is the POINT of an associations file.
const assoc = [["G1","R1"], ["G1","R2"], ["G2","R1"]];

const dupCode = (r) => (r.problems||[]).filter(p => p.code === "DUPLICATE_IDENTIFIER");
const out = {};
const check = (name, role, rows) => {
    const report = API.validateForRole(role, rows);
    const found = dupCode(report);
    out[name] = { ok: !!report.ok, flagged: found.length > 0,
                  detail: found.length ? found[0].detail : null };
};

check("values_clean",      "values", clean);
check("values_dupes",      "values", dupes);
check("design_clean",      "design", design);
check("design_dupes",      "design", dupDesign);
check("regions_clean",     "values", regions);
check("regions_dupes",     "values", dupRegions);
check("assoc_many_to_one", "associations", assoc);
check("relevant_repeats",  "relevant", [["G1"],["G1"],["G2"]]);

out.__direct = API.duplicateIdentifiers(dupes);
console.log(JSON.stringify(out));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-dupe-ids-")
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


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class DuplicateIdentifiersAreRefusedTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = run_node(SCRIPT % {"dir": json.dumps(JS_DIR)})

    # -- the rule ----------------------------------------------------------

    def test_a_repeated_identifier_is_refused_in_a_values_file(self):
        """The regression: this file got a green tick and killed the job."""
        self.assertTrue(self.r["values_dupes"]["flagged"])
        self.assertFalse(self.r["values_dupes"]["ok"])

    def test_a_repeated_sample_is_refused_in_a_design_file(self):
        """runMORE.R intersects sample names; a repeat breaks the same read."""
        self.assertTrue(self.r["design_dupes"]["flagged"])
        self.assertFalse(self.r["design_dupes"]["ok"])

    def test_the_message_carries_the_numbers(self):
        """"You have duplicates" sends someone hunting; the count says where."""
        detail = self.r["values_dupes"]["detail"]
        self.assertEqual(detail["ids"], 1)
        self.assertEqual(detail["worst"], "G1")
        self.assertEqual(detail["worstCount"], 3)
        self.assertEqual(detail["rows"], 2)

    # -- and the other direction, which matters just as much ---------------

    def test_a_clean_file_is_not_flagged(self):
        for name in ("values_clean", "design_clean", "regions_clean"):
            self.assertFalse(self.r[name]["flagged"], name)

    def test_an_associations_file_may_repeat_a_target(self):
        """Many regulators to one target is what the file is FOR."""
        self.assertFalse(self.r["assoc_many_to_one"]["flagged"])
        self.assertTrue(self.r["assoc_many_to_one"]["ok"])

    def test_a_relevant_list_may_repeat(self):
        self.assertFalse(self.r["relevant_repeats"]["flagged"])

    def test_a_region_file_keys_on_all_three_columns(self):
        """chr1 repeats on every region of the chromosome; that is not a dupe."""
        self.assertFalse(self.r["regions_clean"]["flagged"])
        self.assertTrue(self.r["regions_dupes"]["flagged"],
                        "the same chr/start/end twice IS a duplicate")

    def test_the_helper_is_exported_for_reuse(self):
        self.assertEqual(self.r["__direct"]["worst"], "G1")

    # -- the guarantee that this cannot start refusing valid uploads -------

    def test_no_shipped_example_file_is_refused_for_duplicates(self):
        # The role each shipped file is REALLY picked into, from the table the
        # slot-coverage suite already maintains -- guessing from the filename
        # gets mmu_mirBase_to_ensembl.tab wrong (it is the miRNA/gene/PLR
        # prediction table, whose slot is exempt from checking altogether, and
        # whose 898 repeated miRNAs are the file working as intended).
        from src.tests.test_input_check_covers_every_omic_slot import EXAMPLE_ROLES
        cases = []
        for path in sorted(glob.glob(os.path.join(DATASETS, "*", "data", "*"))):
            name = os.path.basename(path)
            role = EXAMPLE_ROLES.get(name)
            if role is None:
                continue
            cases.append({"file": name, "role": role, "path": path})
        self.assertGreater(len(cases), 20, "the example corpus did not load")
        script = """
const fs = require("fs"), path = require("path");
const DIR = %(dir)s;
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));
const out = [];
for (const c of %(cases)s) {
    const rows = API.readDelimited(new Uint8Array(fs.readFileSync(c.path))).rows;
    const report = API.validateForRole(c.role, rows);
    const dup = (report.problems||[]).filter(p => p.code === "DUPLICATE_IDENTIFIER");
    if (dup.length) out.push([c.file, c.role, dup[0].detail]);
}
console.log(JSON.stringify(out));
""" % {"dir": json.dumps(JS_DIR), "cases": json.dumps(cases)}
        refused = run_node(script)
        self.assertEqual(refused, [],
                         "these shipped files would now be refused: %s" % refused)


if __name__ == "__main__":
    unittest.main(verbosity=2)
