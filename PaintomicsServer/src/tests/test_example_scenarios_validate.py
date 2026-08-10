#!/usr/bin/env python3
"""Every bundled example must survive the validator a real upload goes through.

Why this test is the point of the whole catalogue
-------------------------------------------------
`validateFile` returns immediately for an omic flagged `isExample: True`:

    if inputOmic.get("isExample", False):
        return nConditions, error

So the bundled data is the *only* input in the system that is never checked. A
malformed example does not fail at submission -- it fails somewhere downstream,
as an empty result or a traceback out of a queue worker, with nothing pointing
back at the file. That was survivable while one hand-curated example shipped. It
is not survivable now that the files are generated, because a generator bug
produces ten broken scenarios at once.

This test therefore re-validates each scenario with the flag OFF. The files are
symlinked into a scratch job's input directory, which is the layout the
validator expects (it resolves every name against `getInputDir()`), so the code
under test is reached by exactly the path an upload reaches it by.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_scenarios_validate
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.common import ExampleDatasets

EXAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles")) + os.sep

# Which job class validates which pipeline's files. They do NOT agree on the
# rules, which is why dispatching matters: PathwayAcquisitionJob requires a
# relevant-features file to have 1, 2 or `nConditions` columns, while
# Bed2GeneJob requires exactly 3 (chrom/start/end). Validating a region scenario
# with the wrong class rejects correct data.
JOB_CLASS_FOR_PIPELINE = {
    "pathway-acquisition": PathwayAcquisitionJob,
    "regions2genes": Bed2GeneJob,
    "mirna2genes": PathwayAcquisitionJob,
}


def scenarios(pipeline=None):
    return ExampleDatasets.listScenarios(EXAMPLE_DIR, pipeline=pipeline)


class ScenarioValidationTest(unittest.TestCase):
    """One scratch job per scenario; symlinks keep it O(1) regardless of size.

    `mmu_mirBase_to_ensembl.tab` is 31 MB and `dnase_unmapped_values.tab` is
    2.4 MB. Copying them per scenario would make this test slow enough to skip,
    and a skipped test protects nothing.
    """

    def setUp(self):
        self._tmpRoot = tempfile.mkdtemp(prefix="example_validate_") + os.sep

    def tearDown(self):
        shutil.rmtree(self._tmpRoot, ignore_errors=True)

    def _stage(self, scenario):
        """A job whose input dir holds this scenario's files under flat names.

        Returns (job, omics) where each omic dict names its files relatively and
        is NOT flagged as an example -- which is what makes the validator run.
        """
        jobClass = JOB_CLASS_FOR_PIPELINE[scenario["pipeline"]]
        # One staging root PER SCENARIO. getInputDir() is derived from the user,
        # not the jobID, so every scenario would otherwise share a single
        # <root>/nologin/inputData/ -- and link() below skips a name that already
        # exists. Nine scenarios each own a file called gene_expression_values.tab,
        # so whichever scenario staged first silently supplied that file to all
        # the others. It went unnoticed only because the scenarios used to be
        # listed alphabetically, which put a six-condition dataset first and the
        # count it implies happened to fit its neighbours; listing them in the
        # intended 01..10 order puts the single-condition dataset first and every
        # multi-condition scenario after it was then validated against a
        # two-column file.
        scenarioRoot = os.path.join(self._tmpRoot, scenario["id"]) + os.sep
        os.makedirs(scenarioRoot, exist_ok=True)
        job = jobClass(jobID="validate_" + scenario["id"],
                       userID=None, CLIENT_TMP_DIR=scenarioRoot)
        inputDir = job.getInputDir()
        os.makedirs(inputDir, exist_ok=True)

        def link(relativePath):
            source = ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)
            name = os.path.basename(source)
            target = os.path.join(inputDir, name)
            if not os.path.exists(target):
                os.symlink(source, target)
            return name

        omics = []
        for omic in scenario.get("omics", []):
            entry = {"omicName": omic["omicName"],
                     "inputDataFile": link(omic["dataFile"]),
                     "isExample": False}
            if omic.get("relevantFile"):
                entry["relevantFeaturesFile"] = link(omic["relevantFile"])
            if omic.get("associationsFile"):
                entry["associationsFile"] = link(omic["associationsFile"])
            omics.append((entry, omic))
        return job, omics

    def _nConditions(self, job, omics):
        """Column count of the first values file, as validateInput derives it.

        Reproduced rather than called because validateInput bails out on the
        first error with an exception, and this test wants to report *which*
        omic failed rather than that something did.
        """
        from src.classes.Job import Job
        from csv import reader as csv_reader

        for entry, _ in omics:
            path = os.path.join(job.getInputDir(), entry["inputDataFile"])
            delimiter = Job.detect_delimiter(path)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                for line in csv_reader(handle, delimiter=delimiter):
                    if len(line) > 1:
                        try:
                            float(line[1])
                            return len(line)
                        except ValueError:
                            continue
        return -1

    def test_every_gene_and_compound_omic_validates(self):
        checked = 0
        for scenario in scenarios():
            if scenario.get("pipeline") == "more":
                continue          # different job class; covered separately below
            job, omics = self._stage(scenario)
            nConditions = self._nConditions(job, omics)

            self.assertNotEqual(
                nConditions, -1,
                "%s: no values file had a numeric second column, so the "
                "condition count could not be established" % scenario["id"])

            for entry, source in omics:
                _, error = job.validateFile(entry, nConditions, "")
                self.assertEqual(
                    error, "",
                    "scenario '%s', omic '%s' (%s) was rejected by the "
                    "validator:\n%s"
                    % (scenario["id"], entry["omicName"],
                       os.path.basename(source["dataFile"]), error))
                checked += 1

        self.assertGreater(checked, 0, "no scenarios were checked at all")

    def test_relevant_file_width_matches_the_values_file(self):
        """The rule that makes per-condition relevance work or silently not.

        For a gene- or compound-based omic a relevant-features file must have
        one column, two (the legacy TARGET/REGULATOR pair list), or exactly as
        many as the values file has conditions. Get it wrong and the file is
        rejected -- or, for a 2-column file, read as a pair list instead, which
        fails silently.

        Region-based omics are excluded: their relevant file is always exactly
        three columns (chrom, start, end) regardless of condition count, and
        Bed2GeneJob enforces that separately.
        """
        for scenario in scenarios():
            if scenario.get("pipeline") in ("more", "regions2genes"):
                continue
            job, omics = self._stage(scenario)
            nConditions = self._nConditions(job, omics)

            for entry, source in omics:
                relative = entry.get("relevantFeaturesFile")
                if not relative:
                    continue
                path = os.path.join(job.getInputDir(), relative)
                with open(path, encoding="utf-8-sig") as handle:
                    width = len(handle.readline().rstrip("\n").split("\t"))
                self.assertIn(
                    width, (1, 2, nConditions - 1),
                    "scenario '%s', omic '%s': relevant file has %d columns; "
                    "the values file declares %d conditions, so 1 or %d were "
                    "required" % (scenario["id"], entry["omicName"], width,
                                  nConditions - 1, nConditions - 1))

    def test_no_values_file_carries_a_missing_value_token(self):
        """Every value column must float, so `NA` is not a legal example.

        validateFile runs `list(map(float, line[1:]))` over each row and records
        "Line contains invalid values or symbols" for anything that will not
        parse -- `NA`, `NaN` and an empty cell alike. An example carrying gaps
        would be teaching a format the application refuses, and it would only be
        caught at upload time by a user, since example omics skip validation.
        """
        for scenario in scenarios():
            for omic in scenario.get("omics", []):
                path = ExampleDatasets.absolutePath(EXAMPLE_DIR, omic["dataFile"])
                skipColumns = 3 if omic.get("omicType") == "region" else 1
                with open(path, encoding="utf-8-sig") as handle:
                    handle.readline()                       # header
                    for number, line in enumerate(handle, start=2):
                        if not line.strip():
                            continue
                        for cell in line.rstrip("\n").split("\t")[skipColumns:]:
                            try:
                                float(cell)
                            except ValueError:
                                self.fail(
                                    "%s line %d has the non-numeric value %r; "
                                    "the validator rejects the whole file for it"
                                    % (omic["dataFile"], number, cell))
                        if number > 500:      # a sample is enough to catch a systematic bug
                            break

    def test_per_condition_scenario_really_is_per_condition(self):
        """Guards the scenario that exists specifically to reach that branch.

        If a generator change quietly collapsed this file to one column, every
        other assertion here would still pass and the multi-condition parser
        would go back to being unreachable from example mode -- which is the
        exact gap this catalogue was built to close.
        """
        scenario = ExampleDatasets.getScenario(
            EXAMPLE_DIR, "gene-multi-condition-relevance")
        omic = scenario["omics"][0]
        path = ExampleDatasets.absolutePath(EXAMPLE_DIR, omic["relevantFile"])

        with open(path, encoding="utf-8-sig") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            firstRow = handle.readline().rstrip("\n").split("\t")

        self.assertEqual(len(header), len(scenario["conditions"]))
        self.assertGreater(len(header), 1,
                           "the per-condition scenario has a single-column "
                           "relevant file, so it tests nothing the others do not")
        self.assertEqual(len(firstRow), len(header),
                         "rows are not padded to the header width; the "
                         "validator measures the file by its first line")

        # The header must not be mistaken for data, or the first condition's
        # name would be parsed as a relevant feature.
        from src.classes.Job import Job
        self.assertFalse(Job._row_looks_like_data(header),
                         "condition names %r look like feature IDs to the "
                         "header heuristic" % (header,))


class MoreScenarioTest(unittest.TestCase):
    """MORE's inputs answer to runMORE.R's reader, not to validateFile."""

    def setUp(self):
        self.scenario = ExampleDatasets.getScenario(EXAMPLE_DIR, "regulatory-more")

    def _matrix(self, relativePath):
        path = ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)
        with open(path, encoding="utf-8") as handle:
            rows = [line.rstrip("\n").split("\t") for line in handle if line.strip()]
        return rows

    def test_sample_columns_agree_across_every_matrix(self):
        """MORE pairs samples by position as well as by name.

        A regulator matrix whose columns are in a different order than the
        target matrix produces a model fitted on mismatched samples: no error,
        just wrong coefficients.
        """
        expected = self._matrix(self.scenario["target"]["dataFile"])[0][1:]
        self.assertEqual(expected, self.scenario["samples"])

        for omic in self.scenario["omics"]:
            header = self._matrix(omic["dataFile"])[0][1:]
            self.assertEqual(
                header, expected,
                "regulator matrix for '%s' has different sample columns than "
                "the target matrix" % omic["omicName"])

    def test_design_rows_match_the_sample_columns(self):
        rows = self._matrix(self.scenario["design"]["dataFile"])
        self.assertEqual([row[0] for row in rows[1:]], self.scenario["samples"])

        # Indicator columns, one 1 per row: read_matrix rejects a non-numeric
        # cell outright, so a factor column of group names is not an option.
        for row in rows[1:]:
            flags = [int(cell) for cell in row[1:]]
            self.assertEqual(sum(flags), 1,
                             "sample %s belongs to %d groups" % (row[0], sum(flags)))

    def test_matrices_have_unique_and_numeric_rows(self):
        """A duplicate ID makes R's tab parse fail and the job proceed empty.

        read.table(row.names=1) raises "duplicate 'row.names' are not allowed";
        runMORE.R then retries with a comma separator, gets a zero-column frame,
        and carries on with no data at all rather than reporting anything.
        """
        paths = [self.scenario["target"]["dataFile"]]
        paths += [omic["dataFile"] for omic in self.scenario["omics"]]

        for relativePath in paths:
            rows = self._matrix(relativePath)
            ids = [row[0] for row in rows[1:]]
            self.assertEqual(len(ids), len(set(ids)),
                             "%s has duplicate feature IDs" % relativePath)
            for row in rows[1:]:
                for cell in row[1:]:
                    float(cell)      # raises ValueError, naming the file, if not

    def test_association_targets_and_regulators_exist(self):
        """An association naming a feature in neither matrix is a silent no-op.

        runMORE.R reports the overlap and carries on, so the run completes
        having modelled nothing.
        """
        targets = {row[0] for row in
                   self._matrix(self.scenario["target"]["dataFile"])[1:]}

        for omic in self.scenario["omics"]:
            regulators = {row[0] for row in self._matrix(omic["dataFile"])[1:]}
            rows = self._matrix(omic["associationsFile"])
            self.assertEqual(rows[0], ["Target", "Regulator"],
                             "%s needs a header: runMORE.R reads it with "
                             "header=TRUE and would eat the first pair"
                             % omic["associationsFile"])
            for target, regulator in rows[1:]:
                self.assertIn(target, targets,
                              "association target %s is not in the target matrix"
                              % target)
                self.assertIn(regulator, regulators,
                              "association regulator %s is not in the %s matrix"
                              % (regulator, omic["omicName"]))


class RegionScenarioTest(unittest.TestCase):
    """The region scenario has to agree with its own annotation."""

    def setUp(self):
        self.scenario = ExampleDatasets.getScenario(EXAMPLE_DIR, "region-based")

    def _lines(self, relativePath):
        path = ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)
        with open(path, encoding="utf-8") as handle:
            return [line.rstrip("\n") for line in handle
                    if line.strip() and not line.startswith("#")]

    def test_relevant_regions_have_exactly_three_columns(self):
        omic = self.scenario["omics"][0]
        for line in self._lines(omic["relevantFile"]):
            self.assertEqual(len(line.split("\t")), 3,
                             "the parser rejects any other width: %r" % line)

    def test_every_relevant_region_appears_in_the_values_file(self):
        """Relevance is keyed `chrom_start_end`; a mismatch matches nothing.

        And the failure is silent -- zero relevant regions, no error.
        """
        omic = self.scenario["omics"][0]
        present = set()
        for line in self._lines(omic["dataFile"]):
            fields = line.split("\t")
            present.add("_".join(fields[:3]).lower())

        relevant = self._lines(omic["relevantFile"])
        self.assertGreater(len(relevant), 0)
        for line in relevant:
            key = "_".join(line.split("\t")).lower()
            self.assertIn(key, present,
                          "relevant region %s is not in the values file" % key)

    def test_gtf_has_exon_rows_with_gene_and_transcript_ids(self):
        """RGmatch reads `exon` rows and pulls both IDs out of column 9."""
        import re
        reference = self.scenario["references"][0]
        exons = [line for line in self._lines(reference["dataFile"])
                 if line.split("\t")[2] == "exon"]
        self.assertGreater(len(exons), 0, "the GTF has no exon rows to read")

        for line in exons[:50]:
            fields = line.split("\t")
            self.assertEqual(len(fields), 9, "GTF rows must have 9 columns")
            self.assertIsNotNone(re.search(r'gene_id "?(.*?)"?;', fields[8]))
            self.assertIsNotNone(re.search(r'transcript_id "?(.*?)"?;', fields[8]))
            int(fields[3]), int(fields[4])
            self.assertIn(fields[6], ("+", "-"))

    def test_signal_regions_sit_upstream_of_their_gene(self):
        """Upstream means a LOWER coordinate on +, a HIGHER one on -.

        Subtracting an offset regardless of strand puts a third of the regions
        inside the gene body instead of its promoter. RGmatch still assigns them
        to the gene, under a different area rule, so the scenario would quietly
        stop testing promoter assignment.
        """
        reference = self.scenario["references"][0]
        genes = {}
        for line in self._lines(reference["dataFile"]):
            fields = line.split("\t")
            if fields[2] != "gene":
                continue
            geneID = fields[8].split('"')[1]
            genes[geneID] = (fields[0], int(fields[3]), int(fields[4]), fields[6])

        omic = self.scenario["omics"][0]
        regions = set()
        for line in self._lines(omic["dataFile"]):
            fields = line.split("\t")
            regions.add((fields[0], int(fields[1]), int(fields[2])))

        checkedPlus = checkedMinus = 0
        for chrom, start, end, strand in genes.values():
            if strand == "+":
                match = [r for r in regions if r[0] == chrom and r[2] < start]
                checkedPlus += bool(match)
            else:
                match = [r for r in regions if r[0] == chrom and r[1] > end]
                checkedMinus += bool(match)

        self.assertGreater(checkedPlus, 0, "no plus-strand gene has an upstream region")
        self.assertGreater(checkedMinus, 0,
                           "no minus-strand gene has a region at a HIGHER "
                           "coordinate than its end -- the strand-aware "
                           "promoter placement has regressed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
