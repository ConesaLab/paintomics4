"""Tests for ensure_utf8() encoding conversion in PathwayAcquisitionJob."""
import os
import tempfile
import unittest

import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Imported from PathwayAcquisitionJob deliberately, not from src.common.Util
# where it now lives: that re-export is what Bed2GeneJob, MiRNA2GeneJob and
# PathwayAcquisitionJob itself all import, so this exercises the path the
# application actually uses.
from src.classes.JobInstances.PathwayAcquisitionJob import ensure_utf8


def _write_bytes(path, data):
    with open(path, 'wb') as f:
        f.write(data)


def _read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestEnsureUtf8(unittest.TestCase):
    """Verify ensure_utf8 converts non-UTF-8 files in-place and leaves UTF-8 untouched."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def _tmpfile(self, name):
        return os.path.join(self.tmpdir, name)

    # ------------------------------------------------------------------
    # 1. UTF-8 file should remain unchanged
    # ------------------------------------------------------------------
    def test_utf8_file_unchanged(self):
        path = self._tmpfile("utf8.tsv")
        original = "GeneA\t1.5\t2.3\nGeneB\t0.8\t-1.2\n"
        _write_bytes(path, original.encode('utf-8'))

        ensure_utf8(path)

        self.assertEqual(_read_text(path), original)

    # ------------------------------------------------------------------
    # 2. UTF-8 with BOM — should survive (chardet reports utf-8)
    # ------------------------------------------------------------------
    def test_utf8_bom_file(self):
        path = self._tmpfile("utf8bom.tsv")
        text = "Gene\tVal\nTP53\t3.14\n"
        _write_bytes(path, b'\xef\xbb\xbf' + text.encode('utf-8'))

        ensure_utf8(path)

        content = _read_text(path)
        # BOM may or may not be stripped depending on chardet detection;
        # the key assertion is that the file is valid UTF-8 afterwards
        self.assertIn("TP53", content)

    # ------------------------------------------------------------------
    # 3. Windows-1252 (cp1252) — the original crash scenario
    #    Byte 0x9F is ™ (Ÿ in cp1252, not valid UTF-8)
    # ------------------------------------------------------------------
    def test_windows_1252_converted(self):
        path = self._tmpfile("win1252.tsv")
        # Build a typical values file with a cp1252-only byte
        header = "Gene\tCond1\n"
        row = "BRCA1\t2.5\n"
        # 0x93 = left double quote, 0x94 = right double quote in cp1252
        comment_row = b"# note: \x93quoted\x94 gene\n"
        _write_bytes(path, header.encode('cp1252') + row.encode('cp1252') + comment_row)

        ensure_utf8(path)

        content = _read_text(path)
        self.assertIn("BRCA1", content)
        self.assertIn("quoted", content)
        # The smart quotes should now be valid UTF-8 characters
        self.assertIn("\u201c", content)  # left double quote
        self.assertIn("\u201d", content)  # right double quote

    # ------------------------------------------------------------------
    # 4. Latin-1 (iso-8859-1) — common on older European systems
    # ------------------------------------------------------------------
    def test_latin1_converted(self):
        path = self._tmpfile("latin1.tsv")
        # 0xE9 = é in Latin-1
        _write_bytes(path, b"Gen\xe9A\t1.0\nGen\xe9B\t2.0\n")

        ensure_utf8(path)

        content = _read_text(path)
        self.assertIn("GenéA", content)
        self.assertIn("GenéB", content)

    # ------------------------------------------------------------------
    # 5. Simulated association file (2 columns, tab-delimited)
    # ------------------------------------------------------------------
    def test_association_file_cp1252(self):
        path = self._tmpfile("assoc.tsv")
        lines = b"GeneA\tPathway\x961\nGeneB\tPathway\x962\n"  # 0x96 = en-dash in cp1252
        _write_bytes(path, lines)

        ensure_utf8(path)

        content = _read_text(path)
        self.assertIn("GeneA", content)
        self.assertIn("GeneB", content)

    # ------------------------------------------------------------------
    # 6. Simulated relevant features file (single column, short lines)
    # ------------------------------------------------------------------
    def test_relevant_features_file_cp1252(self):
        path = self._tmpfile("relevant.txt")
        # Encode a realistic relevant-features file via cp1252 with accented
        # gene annotations that chardet can reliably detect.
        text = "TP53\nBRCA1\nEGFR\nKRAS\nPTEN\nRB1\nAPC\nVHL\n"
        text += "# Résumé: gène spécifié\n"
        text += "MYC\nPIK3CA\nBRAF\n"
        _write_bytes(path, text.encode('cp1252'))

        ensure_utf8(path)

        content = _read_text(path)
        self.assertIn("TP53", content)
        self.assertIn("BRCA1", content)
        self.assertIn("MYC", content)
        self.assertIn("Résumé", content)

    # ------------------------------------------------------------------
    # 7. Empty file — should not crash
    # ------------------------------------------------------------------
    def test_empty_file(self):
        path = self._tmpfile("empty.tsv")
        _write_bytes(path, b"")

        ensure_utf8(path)

        self.assertEqual(_read_text(path), "")

    # ------------------------------------------------------------------
    # 8. ASCII-only file (subset of UTF-8) — should remain unchanged
    # ------------------------------------------------------------------
    def test_ascii_file_unchanged(self):
        path = self._tmpfile("ascii.tsv")
        original = "GeneX\t0.1\t0.2\n"
        _write_bytes(path, original.encode('ascii'))

        ensure_utf8(path)

        content = _read_text(path)
        self.assertIn("GeneX", content)


if __name__ == '__main__':
    unittest.main()
