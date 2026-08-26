"""Regression tests for the crash classes reported by users via email
(Nov 2025 - Aug 2026) and fixed together on 2026-08-13.

Each test names the production symptom it pins down:
  * IndexError in step1 while parsing a ragged relevant-features file
    (R's write.table row-names shape: header N columns, rows N+1).
  * IndexError reading line[1] of a 1-column row under a `#Cond<TAB>` header.
  * UnicodeDecodeError on a large upload whose only bad byte sits past the
    256 KiB encoding sniff window.
  * Binary uploads (.xlsx/.gz) being transcoded in place into mojibake.
  * IsADirectoryError from an empty-filename file part ('untouched file
    input' shape browsers submit).
  * FileNotFoundError on <species>/hubData for species installed without it.

Run:  PYTHONPATH=PaintomicsServer python3 PaintomicsServer/src/tests/test_crash_report_fixes.py
"""
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from src.common.Util import ensure_utf8
from src.classes.Job import Job


def _parseRelevant(content):
    """Run the real parser over an on-disk relevant-features file."""
    job = object.__new__(Job)
    job.conditionNames = []
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "relevant.tab")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return job.parseSignificativeFeaturesFile(path)


class RaggedRelevantFileTest(unittest.TestCase):
    def test_row_wider_than_header_is_clamped_not_crashed(self):
        # R's write.table default: header has N names, rows N+1 fields.
        features = _parseRelevant("Ctrl\tTreat\n1\tP12345\tP67890\n")
        self.assertIn("p12345", features)
        # The extra trailing cell is dropped, not written past the end.
        for flags in features.values():
            self.assertEqual(len(flags), 2)

    def test_much_wider_row_is_also_safe(self):
        features = _parseRelevant("Ctrl\tTreat\nP1\tP2\tP3\tP4\tP5\n")
        self.assertTrue(all(len(flags) == 2 for flags in features.values()))

    def test_one_column_row_under_comment_header_is_safe(self):
        # `#Ctrl<TAB>` keeps legacy detection eligible; the single-column row
        # used to be indexed at [1].
        features = _parseRelevant("#Ctrl\t\nP12345\n")
        self.assertIn("p12345", features)

    def test_well_formed_multicondition_file_is_unchanged(self):
        features = _parseRelevant("Ctrl\tTreat\nP1\tP2\nP3\t\n")
        self.assertEqual(features["p1"], [True, False])
        self.assertEqual(features["p2"], [False, True])
        self.assertEqual(features["p3"], [True, False])


class SniffWindowTest(unittest.TestCase):
    def test_bad_byte_past_the_sniff_window_is_still_transcoded(self):
        # 300 KiB of clean ASCII, then one latin-1 byte: the old prefix-only
        # verdict said "UTF-8, fine" and the csv reader crashed later.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "values.tab")
            with open(path, "wb") as handle:
                handle.write(b"gene\tlog2FC\n")
                for i in range(30000):
                    handle.write(("g%06d\t1.5\n" % i).encode("ascii"))
                handle.write("Señal1\t2.0\n".encode("latin-1"))
            self.assertIsNone(ensure_utf8(path))
            # The whole file must now be readable the way the parsers read it.
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                data = handle.read()
            self.assertIn("Señal1", data)


class BinaryUploadTest(unittest.TestCase):
    def _reason(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "upload.bin")
            with open(path, "wb") as handle:
                handle.write(payload)
            reason = ensure_utf8(path)
            with open(path, "rb") as handle:
                after = handle.read()
            return reason, payload == after

    def test_xlsx_is_named_and_left_untouched(self):
        reason, unchanged = self._reason(b"PK\x03\x04" + os.urandom(256))
        self.assertIsNotNone(reason)
        self.assertIn("Excel", reason)
        self.assertTrue(unchanged, "a binary upload must never be rewritten")

    def test_gzip_is_named_and_left_untouched(self):
        import gzip
        payload = gzip.compress(b"chr1\t100\t200\n")
        reason, unchanged = self._reason(payload)
        self.assertIsNotNone(reason)
        self.assertIn("gzip", reason)
        self.assertTrue(unchanged, "a .gz upload must never be rewritten")

    def test_utf16_is_still_transcoded(self):
        # UTF-16 is full of NULs and must keep working (existing behaviour).
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "values.tab")
            with open(path, "wb") as handle:
                handle.write("gene\tvalue\nAlb\t1.5\n".encode("utf-16"))
            self.assertIsNone(ensure_utf8(path))


class EmptyFilenamePartTest(unittest.TestCase):
    def test_saveFile_refuses_an_empty_filename(self):
        from src.servlets.DataManagementServlet import saveFile
        with self.assertRaises(UserWarning):
            saveFile("1", "", {}, None, "/tmp/nonexistent-dir/")

    def test_saveFiles_skips_an_untouched_relevant_input(self):
        # A part with filename="" is what browsers submit for an untouched
        # <input type=file>; it used to reach saveFile and open() the
        # directory itself.
        from werkzeug.datastructures import FileStorage, MultiDict
        from src.common.JobInformationManager import JobInformationManager

        registered = {}

        class _JobStub:
            def getJobID(self):
                return "TESTJOB"
            def addGeneBasedInputOmic(self, omic):
                registered.update(omic)
            def addCompoundBasedInputOmic(self, omic):
                registered.update(omic)

        with tempfile.TemporaryDirectory() as tmp:
            files = MultiDict()
            files.add("omic0_file", FileStorage(
                stream=io.BytesIO(b"gene\tv\nAlb\t1.0\n"), filename="values.tab",
                name="omic0_file"))
            files.add("omic0_relevant_file", FileStorage(
                stream=io.BytesIO(b""), filename="", name="omic0_relevant_file"))
            fields = MultiDict({
                "omic0_omic_name": "Gene expression",
                "omic0_file_type": "Gene expression",
                "omic0_match_type": "gene",
                "omic0_origin": "client",
                "omic0_relevant_origin": "client",
            })
            JobInformationManager().saveFiles(
                files, fields, None, _JobStub(), tmp + "/")

        self.assertEqual(registered.get("relevantFeaturesFile"), None)
        self.assertTrue(str(registered.get("inputDataFile", "")).endswith("values.tab"))


class MissingHubDataTest(unittest.TestCase):
    def test_hubAnalysis_returns_False_when_hubData_is_absent(self):
        from src.classes.Feature import OmicValue
        from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

        # The real OmicValue, not a stub with the two fields spelled as bare
        # attributes: hubAnalysis asks isRelevant(), because `relevant` is a
        # LIST and a list of all-False is truthy. A hand-rolled double drifted
        # away from that the moment the caller stopped reading the attribute.
        omicValue = OmicValue("g1")
        omicValue.setOmicName("Gene expression")
        omicValue.setRelevant([True])

        class _Gene:
            omicsValues = [omicValue]

        job = object.__new__(PathwayAcquisitionJob)
        job.organism = "no-such-species-xyz"
        job.inputGenesData = {"g1": _Gene()}
        job.inputCompoundsData = {}
        result = job.hubAnalysis("/nonexistent-root/")
        self.assertIs(result, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
