#!/usr/bin/env python3
"""The data-management tools must normalise an upload's encoding before reading.

Why this exists
---------------
`cab1dd57` gave Bed2GeneJob and MiRNA2GeneJob the `ensure_utf8` call that
PathwayAcquisitionJob already had, because both read their uploads with a bare

    open(relevantFileName, 'r')

which decodes using the locale. A spreadsheet exported as cp1252/latin-1 --
what Excel writes by default outside a UTF-8 locale -- therefore raised

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd1 in position 4

out of a validation routine, reaching the user as an internal error rather than
a message about their file. One accented gene name is enough.

That fix shipped with no test. It was verified by hand at the time and then had
nothing holding it in place: replacing the guard with `encodingError = None`
left all 87 tests passing. This file closes that hole, and it exists because a
mutation run over this session's fixes caught six of seven and missed exactly
this one.

What is pinned is the behaviour rather than the call: a latin-1 file must be
readable after validateFile has seen it, and a UTF-8 or ASCII file must come
back byte-identical, since rewriting files that were already fine would be its
own bug.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_dm_upload_encoding
"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob
from src.classes.JobInstances.MiRNA2GeneJob import MiRNA2GeneJob

LATIN1_BODY = "MMU-MIR-1983\nGeneÑ\ncafé\n".encode("latin-1")
UTF8_BODY = "MMU-MIR-1983\nGeneÑ\ncafé\n".encode("utf-8")
ASCII_BODY = b"MMU-MIR-1983\nGeneA\n"
VALUES_BODY = b"#name\tC1\ngene\t1\n"


class DataManagementUploadEncodingTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _job(self, jobClass):
        job = jobClass("ENCTEST", None, self.directory)
        job.setDirectories(self.directory)
        job.inputDir = self.directory + os.sep
        return job

    def _validate(self, jobClass, relevantBody):
        relevant = os.path.join(self.directory, "relevant.tab")
        values = os.path.join(self.directory, "values.tab")
        with open(relevant, "wb") as handle:
            handle.write(relevantBody)
        with open(values, "wb") as handle:
            handle.write(VALUES_BODY)

        self._job(jobClass).validateFile(
            {"omicName": "miRNA", "inputDataFile": "values.tab",
             "relevantFeaturesFile": "relevant.tab"}, 0, "")
        return relevant

    def _classes(self):
        return (("Bed2GeneJob", Bed2GeneJob), ("MiRNA2GeneJob", MiRNA2GeneJob))

    def test_a_latin1_upload_becomes_readable(self):
        """The whole point: it could not be read as UTF-8 before, and can after."""
        for label, jobClass in self._classes():
            with self.subTest(job=label):
                with self.assertRaises(UnicodeDecodeError,
                                       msg="the fixture is not actually latin-1"):
                    LATIN1_BODY.decode("utf-8")

                path = self._validate(jobClass, LATIN1_BODY)

                with open(path, "rb") as handle:
                    content = handle.read()
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError:
                    self.fail("%s left the upload undecodable, so the next bare "
                              "open() of it raises UnicodeDecodeError at the "
                              "user" % label)

    def test_validating_a_latin1_upload_does_not_raise(self):
        """The user-visible symptom was an internal error out of validation."""
        for label, jobClass in self._classes():
            with self.subTest(job=label):
                try:
                    self._validate(jobClass, LATIN1_BODY)
                except UnicodeDecodeError as exc:
                    self.fail("%s raised UnicodeDecodeError from validateFile, "
                              "which reaches the browser as 'Oops..Internal "
                              "error!': %s" % (label, exc))

    def test_a_utf8_upload_is_left_alone(self):
        """Rewriting a file that was already fine would be its own bug."""
        for label, jobClass in self._classes():
            with self.subTest(job=label):
                before = hashlib.sha256(UTF8_BODY).hexdigest()

                path = self._validate(jobClass, UTF8_BODY)

                with open(path, "rb") as handle:
                    after = hashlib.sha256(handle.read()).hexdigest()
                self.assertEqual(after, before,
                                 "%s rewrote a UTF-8 upload" % label)

    def test_an_ascii_upload_is_left_alone(self):
        for label, jobClass in self._classes():
            with self.subTest(job=label):
                before = hashlib.sha256(ASCII_BODY).hexdigest()

                path = self._validate(jobClass, ASCII_BODY)

                with open(path, "rb") as handle:
                    after = hashlib.sha256(handle.read()).hexdigest()
                self.assertEqual(after, before,
                                 "%s rewrote an ASCII upload" % label)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
