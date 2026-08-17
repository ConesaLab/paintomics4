#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Regression tests for the three converter speedups that must not change a byte
of any output file:

  * the parsed-GTF sidecar cache in DHS_exon_association.run()
  * extractAttribute(), which replaced two re.search calls per GTF row
  * the once-per-row float conversion in miRNA2Target

Run with:
    cd <repo root> && PYTHONPATH=PaintomicsServer \
        python3 PaintomicsServer/src/tests/test_gtf_cache_and_attribute_parsing.py

The cache is the part with teeth. It is keyed by (format, absolute GTF path,
mtime, size, gene tag, transcript tag, match table) and nothing else, so these
tests pin two opposite failure modes: a key that forgets one of its inputs
(serving the wrong annotation) and a cache file that cannot be read (taking the
run down with it instead of parsing).
"""

import os
import pickle
import random
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.common.bioscripts import DHS_exon_association
from src.common.bioscripts import miRNA2Target
from src.common.bioscripts.DHS_exon_association import (
    GTF_CACHE_FORMAT, extractAttribute, gtfCacheKey, gtfCachePath,
    loadGtfCache, parseGTF, storeGtfCache, run)


# A miniature annotation: two genes on two chromosomes, one of them on the
# minus strand so the exon renumbering pass has something to reverse.
GTF_ROWS = [
    ('1\thavana\tgene\t100\t900\t.\t+\t.\tgene_id "G1"; gene_name "alpha";'),
    ('1\thavana\ttranscript\t100\t900\t.\t+\t.\tgene_id "G1"; transcript_id "T1";'),
    ('1\thavana\texon\t100\t200\t.\t+\t.\tgene_id "G1"; transcript_id "T1";'),
    ('1\thavana\texon\t800\t900\t.\t+\t.\tgene_id "G1"; transcript_id "T1";'),
    ('2\thavana\tgene\t500\t1500\t.\t-\t.\tgene_id "G2"; gene_name "beta";'),
    ('2\thavana\ttranscript\t500\t1500\t.\t-\t.\tgene_id "G2"; transcript_id "T2";'),
    ('2\thavana\texon\t500\t600\t.\t-\t.\tgene_id "G2"; transcript_id "T2";'),
    ('2\thavana\texon\t1400\t1500\t.\t-\t.\tgene_id "G2"; transcript_id "T2";'),
]

REGION_ROWS = [
    "#CHR\tstart\tend\tCond1",
    "1\t150\t250\t1.5",
    "2\t550\t650\t-2.25",
]

RUN_OPTIONS = {
    "level": "gene", "distance": 10000, "tss": 200.0, "promoter": 1300.0,
    "perc_area": 90, "perc_region": 50, "ignore_missing": False,
    "gene_id_tag": "gene_id", "tran_id_tag": "transcript_id",
    "presortedGTF": False,
}


def readFile(path):
    with open(path) as handle:
        return handle.read()


def annotationFingerprint(genes, allTranscripts):
    """A comparable, order-preserving summary of a parsed annotation.

    Order is part of the contract: the region scan sorts each chromosome's gene
    list with a stable sort, so two genes with the same start are reported in
    the order the GTF listed them.
    """
    summary = []
    for chromosome in sorted(genes):
        for gene in genes[chromosome]:
            transcripts = []
            for transcript in gene.getTranscripts():
                transcripts.append((
                    transcript.getTranscriptID(),
                    transcript.getStart(), transcript.getEnd(),
                    [(exon.getStart(), exon.getEnd(), exon.getExon())
                     for exon in transcript.getExons()]))
            summary.append((chromosome, gene.getGeneID(), gene.getStrand(),
                            gene.getStart(), gene.getEnd(), transcripts))
    return (summary, sorted(allTranscripts))


class GtfCacheKeyTest(unittest.TestCase):
    """Every input the parse depends on has to be in the key, and nothing the
    parse does not depend on should be."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="gtfcachekey")
        self.gtf = os.path.join(self.directory, "mini.gtf")
        with open(self.gtf, "w") as handle:
            handle.write("\n".join(GTF_ROWS) + "\n")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def keyFor(self, **overrides):
        arguments = {"gtf": self.gtf, "gene_id_tag": "gene_id",
                     "tran_id_tag": "transcript_id", "matchTable": None}
        arguments.update(overrides)
        return gtfCacheKey(arguments["gtf"], arguments["gene_id_tag"],
                           arguments["tran_id_tag"], arguments["matchTable"])

    def testKeyIsStableForTheSameInputs(self):
        self.assertEqual(self.keyFor(), self.keyFor())

    def testKeyCarriesTheFormatVersion(self):
        self.assertEqual(GTF_CACHE_FORMAT, self.keyFor()[0])

    def testKeyChangesWithTheGeneTag(self):
        self.assertNotEqual(self.keyFor(), self.keyFor(gene_id_tag="gene_name"))

    def testKeyChangesWithTheTranscriptTag(self):
        self.assertNotEqual(self.keyFor(),
                            self.keyFor(tran_id_tag="havana_transcript"))

    def testKeyChangesWithTheMatchTable(self):
        matchTable = os.path.join(self.directory, "match.tab")
        with open(matchTable, "w") as handle:
            handle.write("1\tchr1\n2\tchr2\n")
        withTable = self.keyFor(matchTable=matchTable)
        self.assertNotEqual(self.keyFor(), withTable)

        # ...and with its CONTENTS, not just its presence.
        with open(matchTable, "w") as handle:
            handle.write("1\tchrI\n2\tchrII\n")
        os.utime(matchTable, (1_000_000, 1_000_000))
        self.assertNotEqual(withTable, self.keyFor(matchTable=matchTable))

    def testKeyChangesWhenTheGtfIsRewritten(self):
        before = self.keyFor()
        with open(self.gtf, "a") as handle:
            handle.write(GTF_ROWS[0] + "\n")
        self.assertNotEqual(before, self.keyFor())

    def testKeyChangesOnMtimeAloneEvenAtTheSameSize(self):
        """An edit that keeps the byte count is the case a size-only key would
        miss -- a corrected coordinate is exactly that shape."""
        before = self.keyFor()
        contents = readFile(self.gtf).replace("\t100\t900\t", "\t101\t900\t")
        with open(self.gtf, "w") as handle:
            handle.write(contents)
        os.utime(self.gtf, (2_000_000, 2_000_000))
        self.assertEqual(os.path.getsize(self.gtf),
                         before[3])  # same size, so mtime is what must differ
        self.assertNotEqual(before, self.keyFor())

    def testKeyIsNoneForAMissingGtf(self):
        self.assertIsNone(self.keyFor(gtf=os.path.join(self.directory, "nope")))

    def testKeyIsIndifferentToScanSettings(self):
        """distance/tss/level and friends are consumed long after the
        annotation is built. Putting them in the key would only cost hits."""
        key = self.keyFor()
        self.assertNotIn(10000, key)
        self.assertNotIn("gene", key[4:])


class GtfCacheRoundTripTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="gtfcache")
        self.cacheDir = os.path.join(self.directory, "cache")
        self.gtf = os.path.join(self.directory, "mini.gtf")
        with open(self.gtf, "w") as handle:
            handle.write("\n".join(GTF_ROWS) + "\n")
        self.key = gtfCacheKey(self.gtf, "gene_id", "transcript_id", None)
        self.path = gtfCachePath(self.key, self.cacheDir)
        self.parsed = parseGTF(self.gtf, "gene_id", "transcript_id", None)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def testRoundTripRebuildsTheSameAnnotation(self):
        self.assertTrue(storeGtfCache(self.path, self.key, self.parsed))
        restored = loadGtfCache(self.path, self.key)
        self.assertIsNotNone(restored)
        self.assertEqual(annotationFingerprint(*self.parsed),
                         annotationFingerprint(*restored))

    def testRoundTripKeepsSharedObjectIdentity(self):
        """The gene objects reachable from `genes` and the transcript objects
        in `allTranscripts` are the SAME objects. Pickling the pair in one call
        is what preserves that; pickling them separately would double the
        memory and silently split the graph."""
        self.assertTrue(storeGtfCache(self.path, self.key, self.parsed))
        genes, allTranscripts = loadGtfCache(self.path, self.key)
        for chromosome in genes:
            for gene in genes[chromosome]:
                for transcript in gene.getTranscripts():
                    self.assertIs(allTranscripts[transcript.getTranscriptID()],
                                  transcript)

    def testCacheIsRejectedForADifferentKey(self):
        self.assertTrue(storeGtfCache(self.path, self.key, self.parsed))
        otherKey = gtfCacheKey(self.gtf, "gene_name", "transcript_id", None)
        self.assertIsNone(loadGtfCache(self.path, otherKey))

    def testCorruptCacheFallsBackInsteadOfRaising(self):
        with open(self.path, "wb") as handle:
            handle.write(b"this is not a pickle at all")
        self.assertIsNone(loadGtfCache(self.path, self.key))

    def testTruncatedCacheFallsBackInsteadOfRaising(self):
        self.assertTrue(storeGtfCache(self.path, self.key, self.parsed))
        with open(self.path, "rb") as handle:
            whole = handle.read()
        with open(self.path, "wb") as handle:
            handle.write(whole[:len(whole) // 2])
        self.assertIsNone(loadGtfCache(self.path, self.key))

    def testAnEmptyAnnotationIsTreatedAsAMiss(self):
        """({}, {}) is the right shape and the right key, and serving it means
        either zero associations or the "incomplete GTF" abort -- a silent
        wrong answer where a re-parse costs one parse."""
        with open(self.path, "wb") as handle:
            pickle.dump((self.key, ({}, {})), handle)
        self.assertIsNone(loadGtfCache(self.path, self.key))

    def testAWellFormedPickleOfTheWrongShapeIsRejected(self):
        with open(self.path, "wb") as handle:
            pickle.dump((self.key, "not a pair of dicts"), handle)
        self.assertIsNone(loadGtfCache(self.path, self.key))

    def testMissingCacheFileIsSimplyAMiss(self):
        self.assertIsNone(loadGtfCache(self.path, self.key))

    def testStoreDoesNotRaiseOnAnUnwritableDirectory(self):
        unwritable = os.path.join(self.directory, "readonly")
        os.makedirs(unwritable)
        os.chmod(unwritable, 0o500)
        try:
            self.assertFalse(storeGtfCache(
                os.path.join(unwritable, "x.rgcache"), self.key, self.parsed))
        finally:
            os.chmod(unwritable, 0o700)

    def testStoreLeavesNoTemporaryFileBehind(self):
        self.assertTrue(storeGtfCache(self.path, self.key, self.parsed))
        leftovers = [name for name in os.listdir(self.cacheDir)
                     if name.endswith(".tmp")]
        self.assertEqual([], leftovers)


class GtfCacheEndToEndTest(unittest.TestCase):
    """run() twice over the same GTF must write the same output file, and the
    second run must not have parsed anything."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="gtfcacherun")
        self.cacheDir = os.path.join(self.directory, "cache")
        self.gtf = os.path.join(self.directory, "mini.gtf")
        with open(self.gtf, "w") as handle:
            handle.write("\n".join(GTF_ROWS) + "\n")
        self.regions = os.path.join(self.directory, "regions.bed")
        with open(self.regions, "w") as handle:
            handle.write("\n".join(REGION_ROWS) + "\n")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def runAssociation(self, name, **optionOverrides):
        output = os.path.join(self.directory, name)
        options = dict(RUN_OPTIONS)
        options["cache_dir"] = self.cacheDir
        options.update(optionOverrides)
        run(self.gtf, self.regions, output, None, options)
        return readFile(output)

    def testSecondRunReadsTheCacheAndProducesIdenticalBytes(self):
        first = self.runAssociation("first.txt")

        calls = []
        original = DHS_exon_association.parseGTF
        DHS_exon_association.parseGTF = lambda *a, **k: (
            calls.append(a) or original(*a, **k))
        try:
            second = self.runAssociation("second.txt")
        finally:
            DHS_exon_association.parseGTF = original

        self.assertEqual(first, second)
        self.assertEqual([], calls, "the second run re-parsed the GTF")

    def testTouchingTheGtfInvalidatesTheCache(self):
        self.runAssociation("first.txt")
        with open(self.gtf, "a") as handle:
            handle.write(
                '3\thavana\tgene\t10\t99\t.\t+\t.\tgene_id "G3";\n'
                '3\thavana\ttranscript\t10\t99\t.\t+\t.\tgene_id "G3"; transcript_id "T3";\n'
                '3\thavana\texon\t10\t99\t.\t+\t.\tgene_id "G3"; transcript_id "T3";\n')

        calls = []
        original = DHS_exon_association.parseGTF
        DHS_exon_association.parseGTF = lambda *a, **k: (
            calls.append(a) or original(*a, **k))
        try:
            self.runAssociation("second.txt")
        finally:
            DHS_exon_association.parseGTF = original

        self.assertEqual(1, len(calls), "an edited GTF was served from cache")

    def testCorruptCacheStillProducesTheRightOutput(self):
        expected = self.runAssociation("first.txt")
        for name in os.listdir(self.cacheDir):
            with open(os.path.join(self.cacheDir, name), "wb") as handle:
                handle.write(b"\x80\x05 garbage")
        self.assertEqual(expected, self.runAssociation("second.txt"))

    def testAnUnwritableCacheDirectoryDoesNotStopTheRun(self):
        blocked = os.path.join(self.directory, "blocked")
        os.makedirs(blocked)
        os.chmod(blocked, 0o500)
        try:
            # A second writable directory rather than cache_dir=None: the None
            # fallback writes into <gettempdir()>/paintomics-gtfcache, which
            # nothing here owns and nothing cleans, so every run of this suite
            # would leave a sidecar behind under a fresh digest.
            expected = self.runAssociation(
                "plain.txt", cache_dir=os.path.join(self.directory, "other"))
            self.assertEqual(
                expected,
                self.runAssociation("blocked.txt",
                                    cache_dir=os.path.join(blocked, "cache")))
        finally:
            os.chmod(blocked, 0o700)

    def testATornParseIsNotPersisted(self):
        """If the GTF changes while it is being parsed, the annotation in
        memory is a mixture of two files. Using it for this one job is what has
        always happened; writing it to disk under the pre-change key would hand
        the mixture to every later job."""
        original = DHS_exon_association.parseGTF

        def parseThenRewriteTheGtf(*arguments, **keywords):
            result = original(*arguments, **keywords)
            with open(self.gtf, "a") as handle:
                handle.write(
                    '3\thavana\tgene\t10\t99\t.\t+\t.\tgene_id "G3";\n')
            return result

        DHS_exon_association.parseGTF = parseThenRewriteTheGtf
        try:
            self.runAssociation("first.txt")
        finally:
            DHS_exon_association.parseGTF = original

        self.assertEqual(
            [], [name for name in os.listdir(self.cacheDir)
                 if name.endswith(".rgcache")],
            "a parse of a file that changed underneath it was cached")


class ExtractAttributeTest(unittest.TestCase):
    """extractAttribute() has one job: return what re.search(r'<tag>
    \"?(.*?)\"?;') used to return, for every string, including the ugly ones."""

    TRICKY = [
        'gene_id "G1"; transcript_id "T1";',
        'gene_id G1; transcript_id T1;',                      # unquoted
        'gene_id "with space"; transcript_id "t 1";',
        'gene_id ""; transcript_id "";',                      # empty, quoted
        'gene_id ; transcript_id ;',                          # empty, unquoted
        'gene_id "A;B"; transcript_id "T1";',                 # ';' inside quotes
        'gene_id "A\'B"; transcript_id "T1";',
        'gene_id "a"b"; transcript_id "T1";',                 # quote inside
        'transcript_id "T1"; gene_id "G1";',                  # order swapped
        'havana_gene "H"; gene_id "G1"; transcript_id "T1";',
        'gene_id "G1"; gene_version "3"; transcript_id "T1"; exon_number "2";',
        'gene_id "G1";transcript_id "T1";',                   # no space after ';'
        'gene_id  "G1"; transcript_id  "T1";',                # two spaces
        'gene_id "G1"; transcript_id "T1"',                   # no final ';'
        'gene_id "tab\tinside"; transcript_id "T1";',
        'gene_id "-"; transcript_id "-";',
        'gene_id "ENSMUSG00000102693"; gene_version "1"; transcript_id '
        '"ENSMUST00000193812"; exon_number "1"; tag "basic";',
    ]

    def referenceValue(self, attributes, tag):
        """What the code did before: re.search(...).group(1), AttributeError
        and all."""
        pattern = re.compile(r"{0} \"?(.*?)\"?;".format(tag))
        return re.search(pattern, attributes).group(1)

    def testMatchesTheOldRegexOnEveryTrickyString(self):
        for attributes in self.TRICKY:
            for tag in ("gene_id", "transcript_id"):
                try:
                    expected = self.referenceValue(attributes, tag)
                except AttributeError:
                    expected = AttributeError
                try:
                    actual = extractAttribute(attributes, tag)
                except AttributeError:
                    actual = AttributeError
                self.assertEqual(
                    expected, actual,
                    "tag %r in %r" % (tag, attributes))

    # The alphabet that actually decides the answer: quotes, semicolons,
    # spaces, the tag itself -- and '\n', which is the one character the two
    # implementations can disagree about (re's '.' stops at it, str.find does
    # not). It is in the alphabet on purpose: a fuzz test that omits the
    # character it cannot survive is not evidence.
    FUZZ_ALPHABET = ['"', ';', ' ', 'x', 'gene_id ', 'gene_id', '_', 'A', '\n']

    def compare(self, attributes, tag="gene_id"):
        """(old, new), with AttributeError standing in for a failed match."""
        try:
            expected = self.referenceValue(attributes, tag)
        except AttributeError:
            expected = AttributeError
        try:
            actual = extractAttribute(attributes, tag)
        except AttributeError:
            actual = AttributeError
        return expected, actual

    def fuzzStrings(self, count, seed):
        generator = random.Random(seed)
        for _ in range(count):
            yield "".join(generator.choice(self.FUZZ_ALPHABET)
                          for _ in range(generator.randint(1, 14)))

    def testMatchesTheOldRegexOnRandomAttributeSoup(self):
        """Every divergence the fuzz can produce contains a newline.

        Newline-free strings must agree exactly; the newline-bearing ones are
        allowed to differ, and the count is asserted to be non-zero so that
        this test keeps documenting a real divergence rather than quietly
        becoming vacuous.
        """
        divergences = 0
        for attributes in self.fuzzStrings(6000, 20260817):
            expected, actual = self.compare(attributes)
            if expected == actual:
                continue
            divergences += 1
            self.assertIn(
                "\n", attributes,
                "divergence without a newline: %r" % (attributes,))
        self.assertGreater(divergences, 0,
                           "the fuzz alphabet no longer reaches the known "
                           "newline divergence -- check it still contains '\\n'")

    def testTheNewlineDivergenceCannotSurviveAGtfRow(self):
        """...and it is unreachable from the parser.

        Both readers split the file on '\\n' before a row's attributes column
        exists, so the only newline a row can carry is a trailing one with
        nothing after it -- while a divergence needs a ';' AFTER the newline.
        Fuzzing the two shapes the parser actually produces (a trailing '\\n'
        from the file-object path, and none from the gz split) finds none.
        """
        for attributes in self.fuzzStrings(3000, 20260818):
            row = attributes.replace("\n", " ")   # a row cannot contain one
            for shaped in (row, row + "\n"):      # gz split / file iteration
                expected, actual = self.compare(shaped)
                self.assertEqual(expected, actual, repr(shaped))

    def testTheKnownNewlineDivergenceIsTheOneInTheDocstring(self):
        # The simple shape: re's '.' will not cross the newline, so the regex
        # finds no match at all; str.find(';') crosses it and returns a value.
        expected, actual = self.compare('gene_id a\nb;')
        self.assertIs(AttributeError, expected)
        self.assertEqual("a\nb", actual)

        # And the shape where both find something, but not the same thing: the
        # regex gives up at the first occurrence and matches the tag again
        # inside 'havana_gene_id '.
        expected, actual = self.compare('gene_id .\nhavana_gene_id x;')
        self.assertEqual("x", expected)
        self.assertEqual(".\nhavana_gene_id x", actual)

    def testAMissingTagRaisesTheSameExceptionClassAsBefore(self):
        attributes = 'transcript_id "T1"; exon_number "1";'
        self.assertRaises(AttributeError,
                          self.referenceValue, attributes, "gene_id")
        self.assertRaises(AttributeError,
                          extractAttribute, attributes, "gene_id")

    def testATagWithNoSemicolonAfterItIsNotAMatch(self):
        self.assertRaises(AttributeError,
                          extractAttribute, 'x "1"; gene_id "G1"', "gene_id")

    def testTheMessageNamesTheTagAndTheRow(self):
        try:
            extractAttribute('transcript_id "T1";', "gene_id")
        except AttributeError as failure:
            self.assertIn("gene_id", str(failure))
            self.assertIn("transcript_id", str(failure))
        else:
            self.fail("no AttributeError raised")

    def testParsedAnnotationIsUnchangedByTheNewExtraction(self):
        """The end-to-end version of the above: parse a GTF with both readers
        and compare the object graphs."""
        directory = tempfile.mkdtemp(prefix="gtfparse")
        try:
            gtf = os.path.join(directory, "mini.gtf")
            with open(gtf, "w") as handle:
                handle.write("\n".join(GTF_ROWS) + "\n")

            fresh = parseGTF(gtf, "gene_id", "transcript_id", None)

            geneRe = re.compile(r"gene_id \"?(.*?)\"?;")
            tranRe = re.compile(r"transcript_id \"?(.*?)\"?;")
            original = DHS_exon_association.extractAttribute
            DHS_exon_association.extractAttribute = (
                lambda attributes, tag: re.search(
                    geneRe if tag == "gene_id" else tranRe,
                    attributes).group(1))
            try:
                viaRegex = parseGTF(gtf, "gene_id", "transcript_id", None)
            finally:
                DHS_exon_association.extractAttribute = original

            self.assertEqual(annotationFingerprint(*viaRegex),
                             annotationFingerprint(*fresh))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class MiRNAFloatHoistTest(unittest.TestCase):
    """Converting a value row once at read time instead of once per pair must
    not move a single digit of any score."""

    ROWS = [
        ["1.0", "2.0", "3.0", "4.0"],
        ["4.0", "3.0", "2.0", "1.0"],
        ["1.0", "1.0", "1.0", "1.0"],          # constant: correlation is nan
        ["1.0", "1.0", "2.0", "2.0"],          # ties
        ["-0.5", "0", "1e-3", "2.5e2"],        # exponents and a bare zero
        ["0.1", "0.2", "0.30000000000000004", "0.4"],
    ]

    def testScoresAreIdenticalWithPreConvertedRows(self):
        for method in ("kendall", "spearman", "pearson"):
            for left in self.ROWS:
                for right in self.ROWS:
                    old = miRNA2Target.getScore(left, right, method)
                    new = miRNA2Target.getScore(miRNA2Target.toFloats(left),
                                                miRNA2Target.toFloats(right),
                                                method)
                    # str() is what reaches the output file, and it is the
                    # comparison that matters: 'nan' has to render as 'nan'
                    # from both paths too.
                    self.assertEqual(str(old), str(new),
                                     "%s %s %s" % (method, left, right))

    def testToFloatsParsesLikeTheOldInlineComprehension(self):
        for row in self.ROWS:
            self.assertEqual([float(cell) for cell in row],
                             miRNA2Target.toFloats(row))

    def testToFloatsKeepsANonNumericRowIntact(self):
        """The gene expression file is read without skipping its header, so a
        row of condition names is a real, expected input."""
        header = ["T00h", "T02h", "T06h"]
        self.assertEqual(header, miRNA2Target.toFloats(header))

    def testANonNumericRowStillFailsWhereItUsedTo(self):
        kept = miRNA2Target.toFloats(["T00h", "T02h", "T06h", "T12h"])
        self.assertRaises(ValueError, miRNA2Target.getScore,
                          [1.0, 2.0, 3.0, 4.0], kept, "kendall")

    def testAsFloatsIsIdempotent(self):
        converted = miRNA2Target.asFloats(["1.5", "2.5"])
        self.assertEqual([1.5, 2.5], converted)
        self.assertIs(converted, miRNA2Target.asFloats(converted))

    def testAsFloatsHandlesAnEmptyRow(self):
        self.assertEqual([], miRNA2Target.asFloats([]))


class MiRNAKernelOutputTest(unittest.TestCase):
    """The whole kernel, on a fixture small enough to write out by hand."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="mirnakernel")

        self.values = os.path.join(self.directory, "mirna_values.tab")
        with open(self.values, "w") as handle:
            handle.write("C1\tC2\tC3\tC4\n")
            handle.write("mmu-miR-1\t1.0\t2.0\t3.0\t4.0\n")
            handle.write("mmu-miR-2\t4.0\t3.0\t2.0\t1.0\n")
            handle.write("mmu-miR-3\t1.0\t1.0\t1.0\t1.0\n")

        self.reference = os.path.join(self.directory, "targets.tab")
        with open(self.reference, "w") as handle:
            handle.write("mmu-miR-1\tGENE_A\nmmu-miR-1\tGENE_B\n"
                         "mmu-miR-2\tGENE_A\nmmu-miR-2\tGENE_MISSING\n"
                         "mmu-miR-3\tGENE_B\n")

        self.expression = os.path.join(self.directory, "genes.tab")
        with open(self.expression, "w") as handle:
            handle.write("#geneID\tC1\tC2\tC3\tC4\n")
            handle.write("GENE_A\t4.0\t3.0\t2.0\t1.0\n")
            handle.write("GENE_B\t1.0\t1.0\t2.0\t2.0\n")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def testEveryPairIsScoredAndTheHeaderRowIsNotATarget(self):
        for method in ("kendall", "spearman", "pearson"):
            output = os.path.join(self.directory, "out_%s.txt" % method)
            miRNA2Target.run(self.reference, None, self.values,
                             self.expression, output, method)
            lines = readFile(output).splitlines()
            self.assertEqual(
                "# miRNA_id\ttarget_id\tscore\tscore method\tC1\tC2\tC3\tC4",
                lines[0])
            # GENE_MISSING has no expression row, so its pair is skipped --
            # four of the five reference rows survive.
            self.assertEqual(4, len(lines) - 1)
            pairs = [(line.split("\t")[0], line.split("\t")[1])
                     for line in lines[1:]]
            self.assertEqual([("mmu-miR-1", "GENE_A"), ("mmu-miR-1", "GENE_B"),
                              ("mmu-miR-2", "GENE_A"), ("mmu-miR-3", "GENE_B")],
                             pairs)

    def testPerfectAnticorrelationScoresMinusOne(self):
        output = os.path.join(self.directory, "out.txt")
        miRNA2Target.run(self.reference, None, self.values,
                         self.expression, output, "pearson")
        row = [line for line in readFile(output).splitlines()
               if line.startswith("mmu-miR-1\tGENE_A")][0]
        self.assertEqual("-1.0", row.split("\t")[2])

    def testAConstantRowStillWritesNan(self):
        output = os.path.join(self.directory, "out.txt")
        miRNA2Target.run(self.reference, None, self.values,
                         self.expression, output, "pearson")
        row = [line for line in readFile(output).splitlines()
               if line.startswith("mmu-miR-3\t")][0]
        self.assertEqual("nan", row.split("\t")[2])

    def testTheValueColumnsAreTheRawTextFromTheInput(self):
        """The row echoes the miRNA's own cells verbatim; they must not come
        back as the repr of a float ('1.0' is fine, but a '1e-3' input would
        turn into '0.001')."""
        with open(self.values, "a") as handle:
            handle.write("mmu-miR-4\t1e-3\t2E+2\t.5\t3.10\n")
        with open(self.reference, "a") as handle:
            handle.write("mmu-miR-4\tGENE_A\n")

        output = os.path.join(self.directory, "out.txt")
        miRNA2Target.run(self.reference, None, self.values,
                         self.expression, output, "kendall")
        row = [line for line in readFile(output).splitlines()
               if line.startswith("mmu-miR-4\t")][0]
        self.assertEqual(["1e-3", "2E+2", ".5", "3.10"], row.split("\t")[4:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
