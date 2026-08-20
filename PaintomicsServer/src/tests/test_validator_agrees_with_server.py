"""The client-side validator must agree with the server's own validation loop.

A client check that merely looks reasonable is worse than no check: it tells a
user their file is fine and the server then rejects it, or it flags a file the
server would happily take. This test pins the two together by running BOTH over
every values file shipped with the example datasets and asserting they reach the
same verdict.

The server's rules live in PathwayAcquisitionJob.py:660-745; the client's in
PaintomicsClient/.../InputFormat/format-validator.js.
"""

import glob
import json
import os
import subprocess
import unittest
from csv import reader as csv_reader

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
JS_DIR = os.path.join(
    REPO, "PaintomicsClient", "public_html", "app", "view",
    "PathwayAcquisitionViews", "InputFormat",
)
MAX_NUMBER_FEATURES = 1000000


def server_verdict(path):
    """Re-implementation of the server's loop, kept deliberately literal.

    Importing PathwayAcquisitionJob would drag in Mongo, the job queue and the
    KEGG manager; the loop itself is thirty lines, so transcribing it keeps the
    test runnable as a standalone script (this repo has no pytest -- tests are
    __main__ scripts).
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                delimiter = "\t" if "\t" in stripped else ("," if "," in stripped else "\t")
                break
        else:
            delimiter = "\t"

    n_conditions = -1
    n_line = -1
    erroneous = 0

    with open(path, newline="", encoding="utf-8-sig") as handle:
        for line in csv_reader(handle, delimiter=delimiter):
            n_line += 1
            if n_line == 0:
                try:
                    float(line[1])
                except Exception:
                    continue
            if n_conditions == -1:
                if len(line) < 2:
                    return False
                n_conditions = len(line)
            if n_line > MAX_NUMBER_FEATURES:
                return False
            bad = False
            if n_conditions != len(line) and len(line) > 0:
                bad = True
            try:
                list(map(float, line[1:len(line)]))
            except Exception:
                bad = True
            if bad:
                erroneous += 1
            if erroneous > 9:
                break

    return erroneous == 0 and n_line >= 1


def client_verdict(path):
    script = (
        "const {readDelimited}=require(%s);"
        "const {validateValues}=require(%s);"
        "const fs=require('fs');"
        "const r=readDelimited(new Uint8Array(fs.readFileSync(process.argv[1])));"
        "process.stdout.write(JSON.stringify("
        "r.decodeError?false:validateValues(r.rows).ok));"
    ) % (
        json.dumps(os.path.join(JS_DIR, "format-reader.js")),
        json.dumps(os.path.join(JS_DIR, "format-validator.js")),
    )
    done = subprocess.run(["node", "-e", script, path], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError("node failed on %s: %s" % (path, done.stderr))
    return json.loads(done.stdout)


def all_tab_files():
    """Every .tab in the example datasets, whatever its role.

    Deliberately unfiltered. The agreement test is strongest over the widest
    corpus, and it includes files that are NOT values matrices -- mapping tables,
    association lists, relevant-feature lists -- because agreeing that those are
    invalid is just as much a guarantee as agreeing that a matrix is valid.
    """
    pattern = os.path.join(REPO, "PaintomicsServer", "src", "examplefiles",
                           "datasets", "*", "data", "*.tab")
    return sorted(glob.glob(pattern))


def declared_values_files():
    """Files the example datasets themselves name as omic values matrices.

    This keys on the datasets' own "_values.tab" convention rather than
    inferring a file's shape from its contents, which would make the assertion
    circular. It is the one place a filename is trusted, and only because these
    files are literally what the scenarios pass as inputDataFile.
    """
    return [p for p in all_tab_files() if p.endswith("_values.tab")]


class ValidatorAgreesWithServer(unittest.TestCase):

    def test_example_files_were_found(self):
        self.assertTrue(all_tab_files(), "no .tab files found under examplefiles/datasets")
        self.assertTrue(declared_values_files(), "no *_values.tab files found")

    def test_client_and_server_reach_the_same_verdict(self):
        for path in all_tab_files():
            with self.subTest(path=os.path.relpath(path, REPO)):
                self.assertEqual(
                    client_verdict(path), server_verdict(path),
                    "client and server disagree about %s" % os.path.relpath(path, REPO),
                )

    def test_agreement_is_not_vacuous(self):
        """Both saying "invalid" to everything would pass the test above.

        So require the corpus to contain files of both verdicts: the agreement
        only means something if the validator actually discriminates.
        """
        verdicts = {os.path.basename(p): server_verdict(p) for p in all_tab_files()}
        self.assertIn(True, verdicts.values(), "no example file is a valid values matrix")
        self.assertIn(False, verdicts.values(),
                      "no example file is rejected -- the validator may be accepting everything")

    def test_declared_values_files_are_valid(self):
        for path in declared_values_files():
            with self.subTest(path=os.path.relpath(path, REPO)):
                self.assertTrue(
                    server_verdict(path),
                    "%s is shipped as an omic values file and must validate"
                    % os.path.relpath(path, REPO),
                )
                self.assertTrue(
                    client_verdict(path),
                    "%s validates on the server but not on the client"
                    % os.path.relpath(path, REPO),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
