#!/usr/bin/env python3
"""A non-UTF-8 upload must be reported, not raise UnicodeDecodeError.

PaintOmics deliberately accepts files in other encodings -- chardet is a
declared dependency and ensure_utf8() transcodes uploads in place. That only
worked as long as validateFile() was the first thing to read the file.

validateInput() later grew a preamble loop that reads every values file up
front to establish the number of conditions:

    values_delimiter = Job.detect_delimiter(valuesFileName)
    with open(valuesFileName, 'r', encoding='utf-8-sig', newline='') as f:

Both of those opens are hardcoded to UTF-8 and both run *before*
validateFile(), so a UTF-16 or cp1252 upload blew up in the preamble before
anything could transcode it. Confirmed against the deployed server: a UTF-16
values file returned HTTP 400 carrying

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0

instead of a message naming the file and the problem.

The second half of this file guards the transcoding itself. ensure_utf8 tests
UTF-8 directly before consulting chardet, because single-byte codecs such as
cp1252 decode *any* byte sequence -- a misdetected UTF-8 file would be
rewritten into mojibake rather than left alone.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_input_encoding
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import (
    PathwayAcquisitionJob, ensure_utf8)

try:
    from src.classes.JobInstances.PathwayAcquisitionJob import _ENCODING_SNIFF_BYTES
except ImportError:
    # Older builds read the whole file instead of sniffing a prefix. Fall back
    # rather than blowing up on import, so the behavioural tests below still
    # run and report the real defect instead of an ImportError hiding it.
    _ENCODING_SNIFF_BYTES = 256 * 1024

VALUES = "#geneID\tCond1\tCond2\nENSMUSG00000000001\t0.5\t1.5\nENSMUSG00000000028\t-0.5\t2.5\n"
RELEVANT = "Cond1\tCond2\nENSMUSG00000000001\tENSMUSG00000000028\n"


class ValidateInputEncodingTest(unittest.TestCase):
    """The regression: validateInput must not leak a decoding error."""

    def setUp(self):
        # validateFile resolves names against the job input dir and skips
        # anything flagged isExample, so the files must live there and the omic
        # must look like a real upload.
        self._tmpRoot = tempfile.mkdtemp() + "/"
        self.job = PathwayAcquisitionJob(jobID="encoding", userID=None,
                                         CLIENT_TMP_DIR=self._tmpRoot)
        self._inputDir = self.job.getInputDir()
        os.makedirs(self._inputDir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._tmpRoot, ignore_errors=True)

    def _write(self, name, data):
        with open(os.path.join(self._inputDir, name), "wb") as handle:
            handle.write(data)
        return name

    def _addOmic(self, valuesName, relevantName):
        self.job.addGeneBasedInputOmic({
            "omicName": "Gene expression",
            "inputDataFile": valuesName,
            "relevantFeaturesFile": relevantName,
            "associationsFile": None,
            "relevantAssociationsFile": None,
            "configOptions": None,
            "enrichment": "genes",
        })

    def _validate(self):
        """Run validateInput, separating decoding crashes from validation errors."""
        try:
            self.job.validateInput()
            return None
        except UnicodeDecodeError as exc:                      # the defect
            self.fail("validateInput leaked UnicodeDecodeError: %s" % exc)
        except Exception as exc:                               # normal rejection
            return str(exc)

    def test_utf16_values_file_is_transcoded_not_crashed(self):
        values = self._write("values.tab", VALUES.encode("utf-16"))
        relevant = self._write("relevant.tab", RELEVANT.encode("utf-8"))
        self._addOmic(values, relevant)

        # Passing validation outright is the desired outcome; what must never
        # happen is the decode error, which _validate turns into a failure.
        self.assertIsNone(self._validate())

        with open(os.path.join(self._inputDir, values), "r", encoding="utf-8") as handle:
            self.assertIn("ENSMUSG00000000001", handle.read())

    def test_cp1252_values_file_is_transcoded_not_crashed(self):
        # U+2019 encodes to the single byte 0x92 in cp1252, which is not valid
        # UTF-8 -- so the file genuinely needs transcoding.
        text = VALUES.replace("#geneID", "#gene’ID").encode("cp1252")
        self.assertIn(b"\x92", text)
        values = self._write("values.tab", text)
        relevant = self._write("relevant.tab", RELEVANT.encode("utf-8"))
        self._addOmic(values, relevant)

        self.assertIsNone(self._validate())

    def test_utf16_relevant_file_is_transcoded_not_crashed(self):
        values = self._write("values.tab", VALUES.encode("utf-8"))
        relevant = self._write("relevant.tab", RELEVANT.encode("utf-16"))
        self._addOmic(values, relevant)

        self.assertIsNone(self._validate())

    def test_undecodable_file_is_reported_as_a_validation_error(self):
        # Random high bytes with no coherent encoding. Whatever chardet makes of
        # them, the user must get a message, not a traceback.
        values = self._write("values.tab", bytes(range(128, 256)) * 40)
        relevant = self._write("relevant.tab", RELEVANT.encode("utf-8"))
        self._addOmic(values, relevant)

        message = self._validate()
        self.assertIsNotNone(message, "an unreadable file must be rejected")
        self.assertIn("Errors detected", message)


class EnsureUtf8Test(unittest.TestCase):
    """The transcoder itself."""

    def setUp(self):
        self._dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def _write(self, data):
        path = os.path.join(self._dir, "f.tab")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _read(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def test_utf8_file_is_left_byte_identical(self):
        """The mojibake guard.

        These are real UTF-8 accents. Detected as cp1252 and 'converted', they
        would decode to different characters and be silently rewritten.
        """
        original = "gène\tcafé\t1.0\nnaïve\trésumé\t2.0\n".encode("utf-8")
        path = self._write(original)

        self.assertIsNone(ensure_utf8(path))
        self.assertEqual(self._read(path), original,
                         "a valid UTF-8 file must not be rewritten")

    def test_utf16_is_converted_and_reports_success(self):
        path = self._write(VALUES.encode("utf-16"))

        self.assertIsNone(ensure_utf8(path))
        self.assertEqual(self._read(path).decode("utf-8"), VALUES)

    def test_undecodable_returns_a_reason_instead_of_raising(self):
        path = self._write(bytes(range(128, 256)) * 40)

        reason = ensure_utf8(path)
        if reason is not None:
            self.assertIn("UTF-8", reason)
        else:
            # Some chardet builds land on a single-byte codec that accepts the
            # bytes. That is acceptable only if the result is readable UTF-8.
            self._read(path).decode("utf-8")

    def test_empty_file_is_not_an_encoding_error(self):
        self.assertIsNone(ensure_utf8(self._write(b"")))

    def test_multibyte_char_straddling_the_sniff_boundary(self):
        """A large UTF-8 file must not be misdiagnosed at the chunk edge.

        Encoding is decided from a bounded prefix, so a character cut in half at
        that boundary must not be read as evidence of a different encoding.
        """
        filler = b"A" * (_ENCODING_SNIFF_BYTES - 1)
        original = filler + "€uro\tvalue\n".encode("utf-8")
        path = self._write(original)

        self.assertIsNone(ensure_utf8(path))
        self.assertEqual(self._read(path), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
