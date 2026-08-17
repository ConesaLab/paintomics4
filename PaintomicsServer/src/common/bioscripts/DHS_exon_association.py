#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author: Pedro Furió Tarí
"""RGmatch: associate genomic regions (BED) with genes from an annotation (GTF).

Importable (`run()`, which is what the web app calls) and runnable from the
command line (see `usage()`).

One thing to know before running it anywhere: **run() writes a sidecar cache of
the parsed annotation to disk.** Parsing a real genome dominates the job, so the
result is pickled next to nothing in particular -- into the directory named by
the "cache_dir" option. Callers that pass no "cache_dir" (this module's own
main(), and the example-data generator in
src/AdminTools/scripts/exampledata/stategrafull.py) fall back to
`<tempfile.gettempdir()>/paintomics-gtfcache`, where a mouse-sized annotation
leaves a ~29MB file per (GTF, mtime, size, tag) combination. The web app points
"cache_dir" at `<CLIENT_TMP>/gtfcache` instead. Nothing prunes either directory.
"""

import getopt
import sys
import os
import os.path
import gzip
import hashlib
import pickle
import re
import tempfile

# Global variables
rules          = ["TSS","1st_EXON","PROMOTER","TTS","INTRON","GENE_BODY","UPSTREAM","DOWNSTREAM"]
perc_area      = 90
perc_region    = 50
tss            = 200.0
tts            = 0.0
promotor       = 1300.0
distance       = 10000
level          = "exon"
gene_id_tag    = "gene_id"
tran_id_tag    = "transcript_id"
gene_id_re     = re.compile(r"gene_id \"?(.*?)\"?;")
tran_id_re     = re.compile(r"transcript_id \"?(.*?)\"?;")
ignore_missing = False
match_table    = None
check_strand   = False

# The option names run() understands. They are deliberately NOT the getopt flag
# names -- "report" and "gene" on the command line are "level" and
# "gene_id_tag" here -- and an options dict is read with .get(key, default), so
# a caller that spells a key the getopt way used to be ignored without a word.
# That is exactly how the web app spent its life running at the built-in
# defaults instead of the settings the user typed into the form. Any key not in
# this set is a programming error, so run() rejects it loudly.
RUN_OPTION_KEYS = frozenset([
    "presortedGTF", "rules", "perc_area", "perc_region", "tss", "tts",
    "promoter", "distance", "level", "gene_id_tag", "tran_id_tag",
    "ignore_missing", "check_strand", "cache_dir",
])

# Values accepted for the "level" option / -r flag.
REPORT_LEVELS = ("exon", "transcript", "gene")

# Bumped whenever the parsed annotation changes shape -- the pickled record
# classes, what the payload holds, or what the parser does with a GTF line.
# It is part of the cache key, so an old sidecar written by an older build is
# never read back into a newer one.
GTF_CACHE_FORMAT = 1
GTF_CACHE_SUFFIX = ".rgcache"

class Candidate:
    def __init__(self, start, end, strand, exon_number, area, transcript, gene, distance, pctg_region, pctg_area, tssdist, ttsdist):
        self.start       = start
        self.end         = end
        self.strand      = strand
        self.exon_number = exon_number
        self.area        = area
        self.transcript  = transcript
        self.gene        = gene
        self.distance    = distance
        self.parea       = pctg_area
        self.pregion     = pctg_region
        self.tssdist     = tssdist
        self.ttsdist     = ttsdist

    def getStart(self):
        return self.start

    def getEnd (self):
        return self.end

    def getStrand(self):
        return self.strand

    def getExonNr(self):
        return self.exon_number

    def getArea(self):
        return self.area

    def getTranscript(self):
        return self.transcript

    def getGene(self):
        return self.gene

    def getDistance(self):
        return self.distance

    def getPRegion(self):
        return self.pregion

    def getPArea(self):
        return self.parea
        
    def getTSSdistance(self):
        return self.tssdist

    def getTTSdistance(self):
        return self.ttsdist


# Objects to store the annotations from the GTF file.
#
# The three record classes below are instantiated once per GTF row -- 843k
# exons, 143k transcripts and 55k genes for the bundled mouse annotation -- so
# they carry `__slots__`: no per-instance __dict__ is ~100 bytes saved on every
# one of the million objects, and nothing anywhere sets an attribute on them
# that is not declared here (they are used only inside this module).
#
# `__slots__` alone would make pickling SLOWER and bigger, because the default
# reduction for a slotted object ships a {slot: value} dict. The explicit
# __getstate__/__setstate__ pair ships a plain tuple instead, which is what
# makes the annotation cache (see run()) worth having: measured on the bundled
# mouse GTF, 18.7MB and 0.43s to load the exon records versus 28.0MB / 0.68s
# with the default slotted reduction. Every state tuple below is non-empty, so
# pickle always calls __setstate__ back (a falsy state is skipped).
class Myexons:
    __slots__ = ("start", "end", "exon")

    def __init__(self, start, end, exon):
        self.start = start
        self.end = end
        self.exon = exon

    def __getstate__(self):
        return (self.start, self.end, self.exon)

    def __setstate__(self, state):
        self.start, self.end, self.exon = state

    def getStart(self):
        return self.start

    def getEnd(self):
        return self.end

    def getExon(self):
        return self.exon

    def setExon(self, exon_number):
        self.exon = exon_number


class Mytranscripts:
    __slots__ = ("myexons", "trans_id", "start", "end")

    def __init__(self, trans_id):
        self.myexons = []
        self.trans_id = trans_id
        self.start = sys.maxsize
        self.end = 0

    def __getstate__(self):
        return (self.myexons, self.trans_id, self.start, self.end)

    def __setstate__(self, state):
        self.myexons, self.trans_id, self.start, self.end = state

    def addExon(self, myexon):
        self.myexons.append(myexon)

    def getTranscriptID(self):
        return self.trans_id

    def getExons(self):
        return self.myexons

    def size(self):
        return len (self.myexons)

    # Just to rename exon numbers on the negative strand because some GTFs have it wrong tagged
    def checkExonNumbers(self, strand):

        # Sort them by position        
        self.myexons = sorted(self.myexons, key=lambda tup:tup.getStart())

        # For positive strands assign an increasing order
        if strand == "+":
            n_exons = 1
        
            for exon in self.myexons:
                exon.setExon(str(n_exons))
                n_exons = n_exons + 1
        # For negative strands use an inverse order
        else:
            n_exons = len(self.myexons)
            
            for exon in self.myexons:
                exon.setExon(str(n_exons))
                n_exons = n_exons - 1

    def calculateSize(self):
        # When we don't have the transcript tag, we calculate the sizes
        for exon in self.myexons:
            if exon.getStart() < self.start:
                self.start = exon.getStart()
            if exon.getEnd() > self.end:
                self.end = exon.getEnd()
                          
    def setLength(self, start, end):
        # If we read the transcript tag, we set the sizes
        self.start = start
        self.end   = end

    def getStart(self):
        return self.start

    def getEnd (self):
        return self.end


class Mygenes:
    __slots__ = ("mytranscripts", "start", "end", "gene_id", "strand")

    def __init__(self, gene_id, strand):
        self.mytranscripts = []
        self.start = sys.maxsize
        self.end = 0
        self.gene_id = gene_id
        self.strand = strand

    def __getstate__(self):
        return (self.mytranscripts, self.start, self.end, self.gene_id,
                self.strand)

    def __setstate__(self, state):
        (self.mytranscripts, self.start, self.end, self.gene_id,
         self.strand) = state

    def getGeneID(self):
        return self.gene_id

    def addTranscript(self, mytranscript):
        self.mytranscripts.append(mytranscript)

    def getTranscripts(self):
        return self.mytranscripts

    def size(self):
        return len(self.mytranscripts)

    def calculateSize(self):
        # When we don't have the transcript tag, we calculate the sizes
        for transcript in self.mytranscripts:
            if transcript.getStart() < self.start:
                self.start = transcript.getStart()
            if transcript.getEnd() > self.end:
                self.end = transcript.getEnd()
                          
    def setLength(self, start, end):
        # If we read the transcript tag, we set the sizes
        self.start = start
        self.end   = end

    def getStart(self):
        return self.start

    def getEnd (self):
        return self.end

    def getStrand(self):
        return self.strand


##*****************************************************************************
## GTF attribute extraction
##*****************************************************************************

def extractAttribute(attributes, tag):
    """The value of `tag` in a GTF attributes column.

    This reproduces, character for character, what
        re.search(r'<tag> \"?(.*?)\"?;', attributes).group(1)
    used to return for every attribute string a GTF row can carry -- it is only
    about twice as fast, and the parser calls it twice for every one of the ~1M
    rows of a mouse annotation.

    There is exactly ONE class of string where the two disagree, and it names
    itself: `re`'s '.' does not match a newline, while `str.find(';', ...)`
    crosses one. So an attributes column holding a newline with a ';' somewhere
    after it diverges -- 'gene_id a\\nb;' is AttributeError from the regex and
    'a\\nb' here.

    That shape cannot reach this function: both readers split the file on '\\n'
    before a row's attributes column exists, so the only newline a row can
    carry is a trailing one with nothing after it, while a divergence needs a
    ';' *after* the newline. Fuzzing with '\\n' in the alphabet (see
    test_gtf_cache_and_attribute_parsing.py) finds divergences only in strings
    containing a newline, and none at all once the strings are shaped like the
    rows the two readers actually produce.

    The regex it replaces has three behaviours that are easy to lose:

    * The quotes are OPTIONAL on both sides, so `gene_id ABC;` yields `ABC`
      exactly as `gene_id "ABC";` yields `ABC`.
    * The group is non-greedy and the closing quote is greedy, so the value
      ends at the FIRST ';' at or after the value start, minus one preceding
      '"' if there is one. `gene_id "A;B";` therefore yields `A`, not `A;B`.
    * The match is leftmost: an occurrence of the tag with no ';' after it
      anywhere is not a match, and the search continues at the next
      occurrence.

    A tag that is not present at all made `re.search(...)` return None and the
    caller crash on `.group(1)` with AttributeError. That is deliberately kept
    -- a GTF row without a gene_id is malformed and must not be accepted in
    silence -- but the message now names the tag and shows the row instead of
    saying "'NoneType' object has no attribute 'group'". The exception CLASS is
    unchanged so that any caller distinguishing exception types still sees what
    it saw before.
    """
    needle = tag + " "
    needleLength = len(needle)
    position = attributes.find(needle)
    while position != -1:
        cursor = position + needleLength
        # Optional opening quote: '"?' is greedy, so it takes the quote when
        # one is there and the value starts after it.
        if attributes[cursor:cursor + 1] == '"':
            cursor += 1
        semicolon = attributes.find(";", cursor)
        if semicolon != -1:
            # Optional closing quote, also greedy: it can only sit in the one
            # position immediately before the ';'.
            end = semicolon
            if end > cursor and attributes[end - 1] == '"':
                end -= 1
            return attributes[cursor:end]
        # No ';' after this occurrence means the regex would have failed here
        # and moved on to the next one.
        position = attributes.find(needle, position + 1)

    raise AttributeError(
        "The GTF row carries no %r attribute (or none followed by ';'), so the "
        "annotation cannot be read: %r" % (tag, attributes[:200]))


##*****************************************************************************
## Parsed-annotation cache
##*****************************************************************************

def gtfCacheKey(gtf, gene_id_tag, tran_id_tag, matchTable):
    """Everything the parse depends on, or None if it cannot be determined.

    The GTF is identified by absolute path + mtime + size rather than by a
    digest of its contents: hashing 566MB on every job would cost more than the
    parse it is meant to save. The remaining entries are the ONLY other inputs
    to the load loop -- the two attribute tags (they are compiled into the
    extraction) and the chromosome match table (it renames every chromosome
    key). Everything else run() accepts (rules, distance, tss, tts, promoter,
    the area percentages, level, ignore_missing, check_strand, presortedGTF)
    is consumed by the region scan, long after the annotation is built, and so
    is deliberately absent: including it would only cause needless misses.

    The limitation of mtime+size, stated plainly: an annotation replaced by a
    DIFFERENT file of the SAME byte count whose mtime is then restored -- which
    is what `cp -p`, `tar -x` and `rsync --times` do -- is not detected, and the
    stale sidecar is served. Demonstrated, so it is a trade-off and not an
    oversight: hashing 566MB on every job would cost more than the parse the
    cache exists to skip. Anyone replacing an installed GTF in place should
    bump `GTF_CACHE_FORMAT` or clear the cache directory. The narrower race --
    the GTF changing WHILE it is being parsed -- is handled: run() re-stats
    after parseGTF and refuses to persist a torn parse.
    """
    try:
        gtfPath = os.path.abspath(gtf)
        gtfStat = os.stat(gtfPath)
        matchEntry = None
        if matchTable is not None:
            matchPath = os.path.abspath(matchTable)
            matchStat = os.stat(matchPath)
            matchEntry = (matchPath, matchStat.st_mtime_ns, matchStat.st_size)
        return (GTF_CACHE_FORMAT, gtfPath, gtfStat.st_mtime_ns,
                gtfStat.st_size, gene_id_tag, tran_id_tag, matchEntry)
    except Exception:
        # An unstattable GTF is the parse's problem to report, not the cache's.
        return None


def gtfCachePath(key, cacheDir):
    """Where the sidecar for `key` lives, creating the directory if needed.

    One rule, deliberately: a directory that exists for this and nothing else.
    Writing the sidecar "next to the GTF" was the other candidate and is
    rejected -- the bundled annotations live inside the checked-out repository
    (datasets/07-region-based/data/synthetic_mmu.gtf is a tracked file) and an
    uploaded one lives in the user's own input directory, so both would gain a
    surprise multi-megabyte neighbour.

    `cacheDir` is what the caller passes as the "cache_dir" option -- the web
    app points it at <CLIENT_TMP>/gtfcache. The command-line entry point passes
    nothing, and falls back to the system temporary directory.
    """
    if not cacheDir:
        cacheDir = os.path.join(tempfile.gettempdir(), "paintomics-gtfcache")
    os.makedirs(cacheDir, exist_ok=True)

    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:32]
    # A readable prefix so a human can tell the sidecars apart; the digest is
    # what actually distinguishes them.
    label = "".join(character if character.isalnum() or character in "._-"
                    else "_" for character in os.path.basename(key[1]))[:48]
    return os.path.join(cacheDir, "%s.%s%s" % (label, digest, GTF_CACHE_SUFFIX))


def loadGtfCache(path, key):
    """The cached (genes, allTranscripts) for `key`, or None.

    Never raises: a truncated, unpicklable, half-written or simply foreign file
    means "no cache", and the caller parses the GTF as it always did. The key
    is stored inside the file and compared again here, so a digest collision or
    a stale file reused under the same name cannot feed the wrong annotation
    into a run.
    """
    try:
        with open(path, "rb") as handle:
            stored = pickle.load(handle)
    except Exception:
        return None

    try:
        if (not isinstance(stored, tuple) or len(stored) != 2
                or stored[0] != key):
            return None
        payload = stored[1]
        if (not isinstance(payload, tuple) or len(payload) != 2
                or not isinstance(payload[0], dict)
                or not isinstance(payload[1], dict)):
            return None
        if not payload[0]:
            # An annotation with no chromosomes is not a cache hit worth having:
            # served, it means either zero associations or the "incomplete GTF"
            # abort, which is a silent wrong answer. A GTF that really parses to
            # nothing costs one wasted parse per job and reports itself honestly.
            return None
        return payload
    except Exception:
        return None


def storeGtfCache(path, key, payload):
    """Write the sidecar atomically. Never raises: a job must not fail because
    its cache could not be written (read-only directory, full disk, a parallel
    job writing the same key)."""
    temporaryPath = None
    try:
        handle, temporaryPath = tempfile.mkstemp(
            dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(handle, "wb") as sink:
            pickle.dump((key, payload), sink, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporaryPath, path)
        return True
    except Exception:
        if temporaryPath is not None:
            try:
                os.unlink(temporaryPath)
            except OSError:
                pass
        return False


def parseGTF(gtf, gene_id_tag, tran_id_tag, match_table):
    """Build the annotation the region scan works against.

    Returns (genes, allTranscripts):
      genes           chromosome -> [Mygenes], in first-seen order
      allTranscripts  transcript id -> Mytranscripts

    The gene objects are shared between the two structures and carry their
    transcripts, which carry their exons, so pickling the pair in ONE call
    preserves every shared reference. `allGenes` is deliberately not returned:
    nothing downstream of the exon-renumbering pass below ever reads it.

    Extracted verbatim out of run() so the result can be cached; the only
    change to the loop itself is extractAttribute() in place of two re.search
    calls per row, which returns exactly the same strings (see its docstring).

    `match_table` here is the already-loaded {gtf chromosome: bed chromosome}
    dict, not the path.
    """
    inputGTF = None
    if gtf[-2:] == "gz":
        aux = gzip.open(gtf, 'rb').read().decode(errors='replace')
        inputGTF = aux.split("\n")
    else:
        inputGTF = open(gtf, 'r')
    genes = {}
    allTranscripts = {}
    allGenes  = {}
    # Flags will tell me if "transcript" and "gene" flags can be found inside the GTF file. If they are not found,
    # the start and end positions will have to be measured based on the exons.
    geneFlag  = False
    transFlag = False

    for line in inputGTF:
        # Avoid comments
        if line and line[0] != "#":
            linea_split = line.split("\t")
            chrom = linea_split[0]
            start = int(linea_split[3])
            end   = int(linea_split[4])
            strand = linea_split[6]

            popurri = linea_split[8]

            # Rename chrom if match_table exists
            if match_table is not None:
                chrom = match_table[chrom]

            if linea_split[2] == "exon":

                gene_id       = extractAttribute(popurri, gene_id_tag)
                transcript_id = extractAttribute(popurri, tran_id_tag)

                # The exon number will be calculated later
                exon_number = None

                myexon = Myexons(start, end, exon_number)

                flag_transcript = False
                if transcript_id not in allTranscripts:
                    allTranscripts[transcript_id] = Mytranscripts(transcript_id)
                    flag_transcript = True
                allTranscripts[transcript_id].addExon(myexon)

                if chrom not in genes:
                    genes[chrom] = []

                if gene_id not in allGenes:
                    allGenes[gene_id] = Mygenes(gene_id, strand)
                    genes[chrom].append(allGenes[gene_id])
                if flag_transcript is True:
                    # Transcript not added in gene
                    allGenes[gene_id].addTranscript(allTranscripts[transcript_id])


            elif linea_split[2] == "transcript":

                transFlag = True

                gene_id = extractAttribute(popurri, gene_id_tag)
                transcript_id = extractAttribute(popurri, tran_id_tag)

                flag_transcript = False
                if transcript_id not in allTranscripts:
                    allTranscripts[transcript_id] = Mytranscripts(transcript_id)
                    flag_transcript = True
                allTranscripts[transcript_id].setLength(start, end)

                if chrom not in genes:
                    genes[chrom] = []

                if gene_id not in allGenes:
                    allGenes[gene_id] = Mygenes(gene_id, strand)
                    genes[chrom].append(allGenes[gene_id])
                if flag_transcript is True:
                    # Transcript not added in gene
                    allGenes[gene_id].addTranscript(allTranscripts[transcript_id])


            elif linea_split[2] == "gene":

                geneFlag = True

                gene_id = extractAttribute(popurri, gene_id_tag)


                if chrom not in genes:
                    genes[chrom] = []

                if gene_id not in allGenes:
                    allGenes[gene_id] = Mygenes(gene_id, strand)
                    genes[chrom].append(allGenes[gene_id])
                allGenes[gene_id].setLength(start, end)

    if gtf[-2:] == "gz":
        inputGTF = None
    else:
        inputGTF.close()

    # Check exon number in transcripts
    for gene_id in allGenes:
        for transcript in allGenes[gene_id].getTranscripts():
            transcript.checkExonNumbers(allGenes[gene_id].getStrand())

            if transFlag is False:
                allTranscripts[transcript.getTranscriptID()].calculateSize()

    if geneFlag is False:
        for gene in allGenes:
            allGenes[gene].calculateSize()

    return genes, allTranscripts


def reportCacheEvent(message):
    """Opt-in tracing for the annotation cache.

    Off by default and on purpose: the association kernel runs in a forked
    child, and unconditional writes to the inherited stderr of a forked process
    are exactly the shape of problem that wedged the compound mapper.
    """
    if os.environ.get("PAINTOMICS_GTF_CACHE_DEBUG"):
        sys.stderr.write("GTF CACHE: " + message + "\n")


def main():
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hg:b:o:q:r:t:p:R:v:w:G:T:s:m:ic", ["help", "gtf=", "bed=", "output=", "distance=", "report=", "tss=", "promoter=", "rules=", "perc_area=", "perc_region=", "gene=","transcript=", "tts=", "match_table=", "ignore_missing", "check_strand"])
    except getopt.GetoptError as err:
        print(err) # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    gtf = None
    dhs = None
    outputfile = None

    global perc_area
    global perc_region
    global tss
    global tts
    global promotor
    global distance
    global level
    global gene_id_tag
    global tran_id_tag
    global gene_id_re
    global tran_id_re
    global ignore_missing
    global match_table
    global check_strand

    for o, a in opts:
        if o in ("-h","--help"):
            usage()
            sys.exit()
        elif o in ("-g", "--gtf"):
            if os.path.isfile(a):
                gtf = a
            else:
                sys.stderr.write("\nERROR: GTF file not recognized.\n")
                usage()
                sys.exit()
        elif o in ("-b", "--bed"):
            if os.path.isfile(a):
                dhs = a
            else:
                sys.stderr.write("\nERROR: Region file not recognized.\n")
                usage()
                sys.exit()
        elif o in ("-o", "--output"):
            outputfile = a
        elif o in ("-G", "--gene"):
            gene_id_tag = a
            gene_id_re  = re.compile(r"{0} \"?(.*?)\"?;".format(a))
        elif o in ("-T", "--transcript"):
            tran_id_tag = a
            tran_id_re  = re.compile(r"{0} \"?(.*?)\"?;".format(a))
        elif o in ("-r", "--report"):
            if a.lower() in REPORT_LEVELS:
                level = a.lower()
            else:
                sys.stderr.write("\nERROR: Report can only be one of the following: exon, transcript or gene.\n")
                usage()
                sys.exit()
        elif o in ("-q", "--distance"):
            # -q is documented in kb; everything downstream compares against
            # genomic coordinates in bp. run() is handed a distance already in
            # bp (its callers convert), so this is the only place that scales.
            aux = int(a)
            distance = aux*1000 if aux >= 0 else distance
        elif o in ("-t", "--tss"):
            tss = int(a)
            if tss < 0:
                sys.stderr.write("\nERROR: The TSS distance cannot be lower than 0 bps.\n")
        elif o in ("-s", "--tts"):
            tts = int(a)
            if tts < 0:
                sys.stderr.write("\nERROR: The TTS distance cannot be lower than 0 bps.\n")
        elif o in ("-p", "--promoter"):
            promotor = int(a)
            if promotor < 0:
                sys.stderr.write("\nERROR: The promoter distance cannot be lower than 0 bps.\n")
        elif o in ("-R", "--rules"):
            if readRules(a) is False:
                sys.stderr.write("\nERROR: Rules not properly passed.\n")
                usage()
                sys.exit()
        elif o in ("-v","--perc_area"):
            value = float(a)
            if 0 <= value <= 100:
                perc_area = value
            else:
                sys.stderr.write("\nERROR: The percentage of area defined was wrong. It should range between 0 and 100.\n")
                usage()
                sys.exit()           
        elif o in ("-w","--perc_region"):
            value = float(a)    
            if 0 <= value <= 100:
                perc_region = value
            else:
                sys.stderr.write("\nERROR: The percentage of region defined was wrong. It should range between 0 and 100.\n") 
                usage()
                sys.exit()
        elif o in ("-m", "--match_table"):
            if os.path.isfile(a):
                match_table = a
            else:
                sys.stderr.write("\nERROR: Match table file not recognized.\n")
                usage()
                sys.exit()
        elif o in ("-i", "--ignore_missing"):
            ignore_missing = True
        elif o in ("-c", "--check_strand"):
            check_strand = True
        else:
            assert False, "Unhandled option"

    if gtf is not None and dhs is not None and outputfile is not None:
        # No options dict: getopt has already written every setting straight
        # into the module globals above (including the kb->bp scaling of
        # -q/--distance), so passing them again here would convert twice.
        run(gtf, dhs, outputfile, match_table)
    else:
        usage()


def usage():
    print("\nUsage: python rgmatch.py [options] <mandatory>")
    print("Options:")
    print("\t-r, --report:\n\t\t Report at the 'exon', 'transcript' or 'gene' level. Default: 'exon'")
    print("\t-q, --distance:\n\t\t Maximum distance in kb to report associations. Default: 10 (10kb)")
    print("\t-t, --tss:\n\t\t TSS region distance. Default: 200 bps")
    print("\t-s, --tts:\n\t\t TTS region distance. Default: 0 bps")
    print("\t-p, --promoter:\n\t\t Promoter region distance. Default: 1300 bps")
    print("\t-v, --perc_area:\n\t\t Percentage of the area of the gene overlapped to be considered to discriminate at transcript and gene level. Default: 90 (90%)")
    print("\t-w, --perc_region:\n\t\t Percentage of the region overlapped by the gene to be considered to discriminate at transcript and gene level. Default: 50 (50%)")
    print("\t-R, --rules:\n\t\t Priorities in case of ties. Default: TSS,1st_EXON,PROMOTER,TTS,INTRON,GENE_BODY,UPSTREAM,DOWNSTREAM")
    print("\t-G, --gene:\n\t\t GTF tag used to get gene ids/names. Default: gene_id")
    print("\t-T, --transcript:\n\t\t GTF tag used to get transcript ids/names. Default: transcript_id")
    print("\t-h, --help:\n\t\t show this help message and exit")
    print("\t-i, --ignore_missing:\n\t\t Silently ignore BED missing regions not present in GTF file")
    print("\t-m, --match_table:\n\t\t Match table (2 tab separated columns: GTF -> BED) to transform GTF chromosome/scaffolds IDS to the ones used in the BED file")
    print("\t-c, --check_strand:\n\t\t Consider strand specificity when determining the association")
    print("Mandatory:")
    print("\t-g, --gtf:\n\t\t GTF annotation file")
    print("\t-b, --bed:\n\t\t Region bed file")
    print("\t-o, --output:\n\t\t Output file")
    print("\n25/04/2017. Pedro Furio-Tari. Carlos Martinez.\n")


def readRules(myrules):

    global rules
    rules = []

    myrules_spl = myrules.split(",")

    for tag in myrules_spl:
        if tag in ["TSS","1st_EXON","PROMOTER","TTS","INTRON","GENE_BODY","UPSTREAM","DOWNSTREAM"] and tag not in rules:
            rules.append(tag)

    # Check that we have stored all the possible tags in the proper order
    if len(rules) == 8:
        return True
    else:
        return False


def checkTSS(start, end, exon):

    exon_start = exon.getStart()
    distance = exon.getDistance()
    dhs_start = start
    dhs_end = end

    pm = (start + end)/2

    # If exon is in the negative strand, we will change the sign in order to make this code invariant to the strand
    if exon.getStrand() == "-":
        aux = dhs_end
        dhs_end = 2 * exon.getEnd() - dhs_start
        dhs_start = 2 * exon.getEnd() - aux
        exon_start = exon.getEnd()

    dhs_length = dhs_end - dhs_start + 1

    salida = []

    if distance <= tss:

        # UPSTREAM       PROMOTER        TSS          1st exon
        # ..........|................|..............|----------->

        if exon_start - dhs_start <= tss:
            # UPSTREAM       PROMOTER        TSS          1st exon
            # ..........|................|..............|----------->
            #                      DHS
            #                               |-------------


            pctg_dhs_200 = ((min (exon_start-1, dhs_end) - dhs_start + 1)/float(dhs_length))*100
            pctg_tss_200 = ((min (exon_start-1, dhs_end) - dhs_start + 1)/float(tss))*100
            tag = "TSS"
            # Report TSS
            salida.append([tag, pctg_dhs_200, pctg_tss_200])
    
        else:
            # UPSTREAM       PROMOTER        TSS          1st exon
            # ..........|................|..............|----------->
            #                      DHS
            #                        --------------

            pctg_dhs_200 = ((min (exon_start-1, dhs_end) - (exon_start - tss) + 1)/float(dhs_length))*100
            pctg_tss_200 = ((min (exon_start-1, dhs_end) - (exon_start - tss) + 1)/float(tss))*100
            tag = "TSS"
            # Report TSS
            salida.append([tag, pctg_dhs_200, pctg_tss_200])

            if exon_start - dhs_start <= (tss + promotor):
                # UPSTREAM       PROMOTER        TSS           1st exon
                # ..........|................|..............|----------->
                #                      DHS
                #                     |--------------|

                pctg_dhs_1500 = ((exon_start - tss - dhs_start ) / float(dhs_length))*100
                pctg_tss_1500 = ((exon_start - tss - dhs_start ) / float(promotor))*100
                tag = "PROMOTER"
                # Report PROMOTER
                salida.append([tag, pctg_dhs_1500, pctg_tss_1500])

            else:
                # UPSTREAM       PROMOTER        TSS          1st exon
                # ..........|................|..............|----------->
                #                      DHS
                #       |---------------------------|
                pctg_dhs_1500 = (promotor / float(dhs_length))*100
                pctg_tss_1500 = 100
                tag = "PROMOTER"
                # Report PROMOTER
                salida.append([tag, pctg_dhs_1500, pctg_tss_1500])

                pctg_dhs_upst = ((exon_start - tss - promotor - dhs_start) / float(dhs_length))*100
                pctg_tss_upst = -1
                tag = "UPSTREAM"
                # Report UPSTREAM
                salida.append([tag, pctg_dhs_upst, pctg_tss_upst])

    elif  distance <= (tss + promotor):
        if exon_start - dhs_start <= (tss + promotor):
            # UPSTREAM       PROMOTER        TSS          1st exon
            # ..........|................|..............|----------->
            #                   DHS
            #                |--------|
            pctg_dhs_1500 = 100
            pctg_tss_1500 = (dhs_length/float(promotor))*100
            tag = "PROMOTER"
            # Report PROMOTER
            salida.append([tag, pctg_dhs_1500, pctg_tss_1500])
            
        else:
            # UPSTREAM       PROMOTER        TSS          1st exon
            # ..........|................|..............|----------->
            #                   DHS
            #       |-------------|
            pctg_dhs_1500 = ((dhs_end - (exon_start - tss - promotor) + 1)/float(dhs_length))*100
            pctg_tss_1500 = ((dhs_end - (exon_start - tss - promotor) + 1)/float(promotor))*100
            tag = "PROMOTER"
            # Report PROMOTER
            salida.append([tag, pctg_dhs_1500, pctg_tss_1500])

            pctg_dhs_upst = ((exon_start - tss - promotor - dhs_start) / float(dhs_length))*100
            pctg_tss_upst = -1
            tag = "UPSTREAM"
            # Report UPSTREAM
            salida.append([tag, pctg_dhs_upst, pctg_tss_upst])
            
    else:
        pctg_dhs_upst = 100
        pctg_tss_upst = -1
        tag = "UPSTREAM"
        # Report UPSTREAM
        salida.append([tag, pctg_dhs_upst, pctg_tss_upst])
        
    return salida


def checkTTS(start, end, exon):

    exon_start = exon.getStart()
    distance = exon.getDistance()
    dhs_start = start
    dhs_end = end

    pm = (start + end)/2

    # If exon is in the positive strand, we will change the sign in order to make this code invariant to the strand
    if exon.getStrand() == "+":
        aux = dhs_end
        dhs_end = 2 * exon.getEnd() - dhs_start
        dhs_start = 2 * exon.getEnd() - aux
        exon_start = exon.getEnd()

    dhs_length = dhs_end - dhs_start + 1

    salida = []

    if distance <= tts:

        # DOWNSTREAM       TTS        last exon
        # ..........|...............|----------->

        if exon_start - dhs_start <= tts:
            # DOWNSTREAM        TSS          last exon
            # ..........|................|----------->
            #                      DHS
            #                  |-------------


            pctg_dhs_200 = ((min (exon_start-1, dhs_end) - dhs_start + 1)/float(dhs_length))*100
            pctg_tts_200 = ((min (exon_start-1, dhs_end) - dhs_start + 1)/float(tts))*100
            tag = "TTS"
            # Report TTS
            salida.append([tag, pctg_dhs_200, pctg_tts_200])
    
        else:
            # DOWNSTREAM         TSS          last exon
            # ............|..............|----------->
            #               DHS
            #       --------------

            pctg_dhs_200 = ((min (exon_start-1, dhs_end) - (exon_start - tts) + 1)/float(dhs_length))*100
            pctg_tts_200 = ((min (exon_start-1, dhs_end) - (exon_start - tts) + 1)/float(tts))*100
            tag = "TTS"
            # Report TTS
            salida.append([tag, pctg_dhs_200, pctg_tts_200])

            pctg_dhs_down = ((exon_start - tts - dhs_start) / float(dhs_length))*100
            pctg_tts_down = -1
            tag = "DOWNSTREAM"
            # Report DOWNSTREAM
            salida.append([tag, pctg_dhs_down, pctg_tts_down])

    else:
        pctg_dhs_down = 100
        pctg_tts_down = -1
        tag = "DOWNSTREAM"
        salida.append([tag, pctg_dhs_down, pctg_tts_down])
        
    return salida


# myfinaloutput: Vector of "Candidate"'s
# groupedBy: { transcript1: [pos1, pos3], transcript2: [pos2]};
# Returns the vector of "Candidate"'s to be reported after applying the rules
def applyRules(myfinaloutput, groupedBy):

    toreport = []

    for my_id in groupedBy:
        if len(groupedBy[my_id]) == 1:
            toreport.append(myfinaloutput[groupedBy[my_id][0]])
        else:
            positions = groupedBy[my_id]
            tmpResultsRegion = []

            # Check %Region
            for pos in positions:
                myexon = myfinaloutput[pos]
                if myexon.getPRegion() >= perc_region:
                    tmpResultsRegion.append(myexon)

            if len(tmpResultsRegion) == 1:
                toreport.append(tmpResultsRegion[0])
            elif len(tmpResultsRegion) == 0:
                # Fill with all the results
                for pos in positions:
                    tmpResultsRegion.append(myfinaloutput[pos])

            if len(tmpResultsRegion) > 1:
                tmpResults = []

                # Check %Area
                for myexon in tmpResultsRegion:
                    #myexon = tmpResultsRegion[pos]
                    if myexon.getPArea() >= perc_area:
                        tmpResults.append(myexon)

                if len(tmpResults) == 1:
                    toreport.append(tmpResults[0])
                elif len(tmpResults) == 0:
                    # Fill the vector again with all the candidates
                    for myexon in tmpResultsRegion:
                        tmpResults.append(myexon)

                if len(tmpResults) > 1:

                    maximum_pctg = 0
                    region_candidates = []
                    # Check if there's an exon with maximum %Region
                    for myexon in tmpResults:

                        if myexon.getPRegion() > maximum_pctg:
                            maximum_pctg = myexon.getPRegion()
                            region_candidates = [myexon]
                        elif myexon.getPRegion() == maximum_pctg:
                            region_candidates.append(myexon)

                    if len(region_candidates) == 1:
                        toreport.append(region_candidates[0])
                    else:
                        # Apply the rules amongst the best candidates
                        flagRule = False
                        for area_rule in rules:
                            for myexon in region_candidates:
                                if myexon.getArea() == area_rule:
                                    toreport.append(myexon)
                                    flagRule = True
                            if flagRule is True:
                                break

                        if flagRule is False:
                            # `rules` is caller-supplied, so it may not rank
                            # every area the code emits. Reporting nothing here
                            # dropped the region from the output silently;
                            # keeping the first candidate loses the tie-break
                            # but never loses the association.
                            toreport.append(region_candidates[0])
    return toreport


# myfinaloutput: Vector of "Candidate"'s
# groupedBy: { gene1: [pos1, pos3], gene2: [pos2]}
# Returns the vector of "Candidate"'s to be reported after applying the rules
def selectTranscript(myfinaloutput, groupedBy):

    toreport = []
    for my_id in groupedBy:

        if len(groupedBy[my_id]) == 1:
            toreport.append(myfinaloutput[groupedBy[my_id][0]])
        else:
            myAreas = {}
            positions = groupedBy[my_id]

            for pos in positions:
                myexon = myfinaloutput[pos]
                if myexon.getArea() in myAreas:
                    myAreas[myexon.getArea()].append(pos)
                else:
                    myAreas[myexon.getArea()] = [pos]

            # Apply the set of rules
            area_winner = None
            for area_rule in rules:
                if area_rule in myAreas.keys():
                    area_winner = area_rule
                    break

            if area_winner is None:
                # No candidate area appears in the rules table. The built-in
                # table lists all eight areas the code can emit, but `rules` is
                # caller-supplied (-R / options["rules"]), so a short table
                # leaves every area unranked and `myAreas[None]` raised KeyError
                # -- an unhandled crash in place of a result. Fall back to the
                # first area we grouped, which keeps the report deterministic.
                area_winner = next(iter(myAreas))

            if len(myAreas[area_winner]) == 1:
                toreport.append( myfinaloutput[myAreas[area_winner][0]] )
            else:
                # Report all the candidates that have a tie
                transcripts = ""
                exons       = ""
                pArea       = 0
                pRegion     = 0

                for pos in myAreas[area_winner]:
                    mycandidate = myfinaloutput[pos]
                    transcripts = transcripts + mycandidate.getTranscript() + ","
                    exons       = exons       + mycandidate.getExonNr()     + ","
                    pArea   = max(pArea, mycandidate.getPArea())
                    pRegion = max(pRegion, mycandidate.getPRegion())

                # ttsdist completes the 12 arguments Candidate takes. It was
                # missing, so the moment two transcripts of the same gene tied
                # this raised TypeError instead of merging them -- unreachable
                # while the web app was stuck at the "exon" default, reachable
                # the instant it reports at gene level.
                mycandidate_ref = myfinaloutput[myAreas[area_winner][0]]
                mycandidate = Candidate(mycandidate_ref.getStart(), mycandidate_ref.getEnd(), mycandidate_ref.getStrand(), exons[:-1],
                    mycandidate_ref.getArea(), transcripts[:-1], mycandidate_ref.getGene(), mycandidate_ref.getDistance(),
                    pRegion, pArea, mycandidate_ref.getTSSdistance(), mycandidate_ref.getTTSdistance())
                toreport.append(mycandidate)

    return toreport


def reportOutput(myfinaloutput, dhs_id, start, end, outobj, metainfo):

    pm = (start + end)/2
    
    if level == "exon":
        # Report everything
        for myexon in myfinaloutput:
            outobj.write(dhs_id + "\t" + str(pm) + "\t" + myexon.getGene() + "\t" + myexon.getTranscript() + "\t" +
                    myexon.getExonNr() + "\t" + myexon.getArea() + "\t" + str(myexon.getDistance()) + "\t" + str(myexon.getTSSdistance()) + "\t" + str(myexon.getTTSdistance()) + "\t" + str("{0:.2f}".format(myexon.getPRegion())) +
                    "\t" + str("{0:.2f}".format(myexon.getPArea())) + (("\t" + "\t".join(metainfo)[:-1]) if len(metainfo) > 0 else "") + "\n")
    else:
        # Dictionary with positions where we can find a transcript in myfinaloutput
        # Example: { transcript1: [pos1, pos3], transcript2: [pos2]}
        mytranscripts = {}
        for pos in range(len(myfinaloutput)):
            transcript_id = myfinaloutput[pos].getTranscript()
            if transcript_id not in mytranscripts:
                mytranscripts[transcript_id] = [pos]
            else:
                mytranscripts[transcript_id].append(pos)

        toreport = applyRules(myfinaloutput, mytranscripts)


        if level == "transcript":
            # Report the vector toreport
            for myexon in toreport:
                outobj.write(dhs_id + "\t" + str(pm) + "\t" + myexon.getGene() + "\t" + myexon.getTranscript() + "\t" +
                    myexon.getExonNr() + "\t" + myexon.getArea() + "\t" + str(myexon.getDistance()) + "\t" + str(myexon.getTSSdistance()) + "\t" + str(myexon.getTTSdistance()) + "\t" + str("{0:.2f}".format(myexon.getPRegion())) +
                    "\t" + str("{0:.2f}".format(myexon.getPArea())) + (("\t" + "\t".join(metainfo)[:-1]) if len(metainfo) > 0 else "") + "\n")
        else:
            # Dictionary with positions where we can find a gene in myfinaloutput
            # Example: { gene1: [pos1, pos3], gene2: [pos2]}
            mygenes = {}
            for pos in range(len(toreport)):
                gene_id = toreport[pos].getGene()
                if gene_id not in mygenes:
                    mygenes[gene_id] = [pos]
                else:
                    mygenes[gene_id].append(pos)

            toreport = selectTranscript(toreport, mygenes)
            # Report the vector toreport
            for myexon in toreport:
                outobj.write(dhs_id + "\t" + str(pm) + "\t" + myexon.getGene() + "\t" + myexon.getTranscript() + "\t" +
                    myexon.getExonNr() + "\t" + myexon.getArea() + "\t" + str(myexon.getDistance()) + "\t" + str(myexon.getTSSdistance()) + "\t" + str(myexon.getTTSdistance()) + "\t" + str("{0:.2f}".format(myexon.getPRegion())) +
                    "\t" + str("{0:.2f}".format(myexon.getPArea())) + (("\t" + "\t".join(metainfo)[:-1]) if len(metainfo) > 0 else "") + "\n")


def run(gtf, dhs, outputfile, match_table, options=None, managed_queue=None):
    """Run the region-to-gene association.

    `options` is a dict keyed by RUN_OPTION_KEYS, with `distance` already in
    **bp** (the kb wording belongs to the -q flag and to the web form; every
    caller of run() converts before calling). `managed_queue` is the
    multiprocessing queue the web app uses to ferry an exception back out of
    the worker process; the command-line path passes neither.
    """
    #############################################
    ## CODE ADDED BY RAFA (modified by Carlos) ##
    # Global variables
    try:
        global rules
        global perc_area
        global perc_region
        global tss
        global tts
        global promotor
        global distance
        global level
        global gene_id_tag
        global tran_id_tag
        global gene_id_re
        global tran_id_re
        global ignore_missing
        global check_strand

        options = options or {}

        # Every setting below is read with .get(key, default), so a misspelled
        # key is indistinguishable from an absent one and the run quietly uses
        # the built-in default. Refuse instead: a caller sending an option we
        # do not honour is a bug, and the user deserves to hear about it now
        # rather than to receive a plausible-looking wrong answer.
        unknownOptions = sorted(set(options.keys()) - RUN_OPTION_KEYS)
        if unknownOptions:
            raise Exception(
                "Unknown option(s) passed to the region-to-gene association: "
                + ", ".join(unknownOptions)
                + ". Accepted options are: "
                + ", ".join(sorted(RUN_OPTION_KEYS)) + ".")

        # presortedGTF is accepted for compatibility with the callers that send
        # it, but nothing here depends on the GTF being sorted: the annotation
        # is loaded into dictionaries before any region is matched.
        rules          = options.get("rules", rules)
        perc_area      = options.get("perc_area", perc_area)
        perc_region    = options.get("perc_region", perc_region)
        tss            = options.get("tss", tss)
        tts            = options.get("tts", tts)
        promotor       = options.get("promoter", promotor)
        distance       = options.get("distance", distance)
        level          = options.get("level", level)
        gene_id_tag    = options.get("gene_id_tag", gene_id_tag)
        tran_id_tag    = options.get("tran_id_tag", tran_id_tag)
        ignore_missing = options.get("ignore_missing", ignore_missing)
        check_strand   = options.get("check_strand", check_strand)

        if level not in REPORT_LEVELS:
            # reportOutput() has no else-branch for an unrecognised level: it
            # would silently fall through to the gene-level report. Say so.
            raise Exception(
                "Unknown report level %r for the region-to-gene association. "
                "Expected one of: %s." % (level, ", ".join(REPORT_LEVELS)))

        # The gene/transcript tags are only ever consumed through the attribute
        # extraction, which the getopt path re-derived but this one did not --
        # so a GTF annotated with, say, gene_name was parsed looking for
        # gene_id and every lookup raised AttributeError on a missing tag. The
        # tags are re-read from the options on every call, so a second run() in
        # the same interpreter cannot inherit the previous call's tag.
        #
        # The two patterns are still compiled, unused as they now are: the tag
        # arrives from a web form, and compiling it is what has always rejected
        # a tag that is not a valid pattern (an unbalanced parenthesis, say).
        # Keeping the compile keeps that rejection. What it deliberately does
        # NOT keep is the tag being interpreted AS a pattern -- extractAttribute
        # matches it literally, so a tag containing '.' or '*' now means those
        # characters instead of silently matching anything. For every tag the
        # web app and the examples use (gene_id, transcript_id, gene_name) the
        # two readings are the same string.
        gene_id_re = re.compile(r"{0} \"?(.*?)\"?;".format(gene_id_tag))
        tran_id_re = re.compile(r"{0} \"?(.*?)\"?;".format(tran_id_tag))
        ## END CODE ADDED BY RAFA ##
        ############################

        # 1. First, we save all the genes with their positions.
        #
        # Parsing the annotation is the single most expensive thing this
        # function does on a real genome (~3.6s of an 8.4s mouse job, and it is
        # repeated in full for every job because the kernel runs in a fresh
        # forked child), and it depends on nothing but the GTF itself and the
        # two attribute tags. So it is cached: gtfCacheKey() names every
        # parse-time input, and a hit skips both the load loop and the exon
        # renumbering pass below. Only the annotation is ever cached -- never
        # the regions/BED side, which is per-job data.
        # Captured before `match_table` is rebound from a path to the loaded
        # dict a few lines down; the key needs the path, and so does the
        # re-stat after the parse.
        matchTablePath = match_table
        cacheKey = gtfCacheKey(gtf, gene_id_tag, tran_id_tag, matchTablePath)
        cachePath = None
        cached = None
        if cacheKey is not None:
            try:
                cachePath = gtfCachePath(cacheKey, options.get("cache_dir"))
                cached = loadGtfCache(cachePath, cacheKey)
            except Exception:
                # A cache that cannot even be located must not stop the run.
                cachePath = None
                cached = None

        # Prepare a match table to transform the GTF chromosome/scaffolds IDs to the
        # ones used in the BED regions file. Loaded on the cached path too, so
        # that an unreadable match table still fails the same way it always did.
        if match_table is not None:
            with open(match_table, 'r') as table_file:
                match_table = dict(match_line.strip().split('\t') for match_line in table_file)

        if cached is not None:
            reportCacheEvent("hit %s" % cachePath)
            genes, allTranscripts = cached
        else:
            reportCacheEvent("miss %s" % cachePath)
            genes, allTranscripts = parseGTF(gtf, gene_id_tag, tran_id_tag,
                                             match_table)
            # Re-stat before persisting. The key was taken before the read; if
            # the GTF moved underneath the parse, what is in memory is a torn
            # mixture of two files. Using it for THIS job is the behaviour that
            # has always been there, but writing it to disk would hand the same
            # torn annotation to every later job under the pre-change key.
            if (cachePath is not None
                    and gtfCacheKey(gtf, gene_id_tag, tran_id_tag,
                                    matchTablePath) == cacheKey):
                stored = storeGtfCache(cachePath, cacheKey,
                                       (genes, allTranscripts))
                reportCacheEvent(("stored " if stored else "not stored ")
                                 + str(cachePath))
            else:
                reportCacheEvent("not stored (annotation changed during the "
                                 "parse) " + str(cachePath))

        inputDHS = None
        if dhs[-2:] == "gz":
            aux = gzip.open(dhs, 'rb').read().decode()
            inputDHS = aux.split("\n")
        else:
            inputDHS = open(dhs, 'r')
        myregions = {}
        myheader = []

        # Column names carried by the regions file itself. In PaintOmics a
        # regions file is not a plain BED: columns 4..n hold one quantification
        # per experimental condition and the header names them (T00h..T24h,
        # Ikaros/Control_0h..). Those names exist nowhere else in the pipeline,
        # so if they are dropped here the condition labels are gone for good --
        # Bed2GeneJob copies this file's header into B2G_output_*.tab, and the
        # pathway job hands that straight to the browser as the chart legend.
        inputValueHeader = []
        # Widest metainfo seen, rather than whatever the last parsed row
        # happened to leave behind in `metainfo`: a short final row used to
        # silently shorten the header of the whole file.
        maxMetaColumns = 0
        firstRowSeen = False

        for dhs_line in inputDHS:

            if dhs_line:
                line = dhs_line.split("\t")
                if len(line) >= 3:
                    # Only rows wide enough to be a region (or its header) count
                    # as "first": a BED `track ...` / `browser ...` preamble is
                    # one column wide and must not shadow the real header.
                    isFirstRow = not firstRowSeen
                    firstRowSeen = True
                    try:
                        chrom = line[0]
                        start = int(line[1])
                        end = int(line[2])
                        strand = None

                        # Select up to 9 additional bed columns
                        metainfo = line[3:12]
                        maxMetaColumns = max(maxMetaColumns, len(metainfo))

                        # In BED files strand is the optional column 6 (third position of metainfo)
                        if len(metainfo) > 2:
                            strand = metainfo[2].strip()

                        if chrom not in myregions:
                            myregions[chrom] = []

                        myregions[chrom].append([start,end, metainfo, strand])
                    except:
                        # If cannot convert start and end to int, it must be a header.
                        # Keep the value-column names from the FIRST such row only,
                        # so a stray comment further down the file (datasets/09 ships
                        # one at line 886) cannot rename the conditions.
                        if isFirstRow:
                            inputValueHeader = [cell.strip().lstrip('#').strip()
                                                for cell in line[3:12]]
                        continue

        if dhs[-2:] == "gz":
            inputDHS = None
        else:
            inputDHS.close()

        # Ensure that extra columns have a header
        bed_extra_columns = ["name", "score", "strand", "thickStart", "thickEnd",
                             "itemRgb", "blockCount", "blockSizes", "blockStarts"]

        # Prefer the file's own names; fall back to the BED optional-column
        # vocabulary only for a genuinely headerless file. The fallback is
        # required to stay exactly as wide as the data rows, so a header that
        # does not cover every value column -- or that leaves a cell blank -- is
        # discarded whole rather than patched, which would mix real condition
        # names with BED keywords in one legend.
        myheader = bed_extra_columns[:maxMetaColumns]
        if maxMetaColumns > 0 and len(inputValueHeader) >= maxMetaColumns:
            candidate = inputValueHeader[:maxMetaColumns]
            if all(candidate):
                myheader = candidate

        salida = open(outputfile,'w')
        salida.write("#Region\tMidpoint\tGene\tTranscript\tExon/Intron\tArea\tDistance\tTSSDistance\tTTSDistance\tPercRegion\tPercArea" + (("\t" + "\t".join(myheader)) if len(myheader) > 0 else "") + "\n")

        last_index = None
        old_chrom = ""
        gene_vector = None

        # Check if all chromosomes present in the regions file are also in the reference file
        if not set(myregions.keys()).issubset(set(genes.keys())):
            sys.stderr.write("\nWARNING: there are chromosomes/scaffolds in your BED file that are not present in your GTF file.\n")

            if ignore_missing:
                sys.stderr.write("\nWARNING: option enabled to ignore missing regions, discarding chromosomes/scaffolds not available in GTF file.\n")
                myregions = {key : myregions[key] for key in set(myregions.keys()) & set(genes.keys())}
            else:
                sys.stderr.write("\nERROR: aborting execution due to incomplete GTF file, provide a different one or enable the '--ignore_missing' flag.\n")
                raise Exception("Aborting execution due to incomplete GTF file, provide a different one or enable the '--ignore_missing' flag")

        for chrom in myregions:

            last_index = 0
            gene_vector = sorted(genes[chrom], key = lambda tup:tup.getStart())
            all_regions = sorted(myregions[chrom], key= lambda tup:tup[0])

            for one_region in all_regions:
                start = int(one_region[0])
                end = int(one_region[1])
                metainfo = one_region[2]
                pm = (end+start)/2
                dhs_id = chrom + "_" + str(start) + "_" + str(end)
                region_length  = end - start + 1
                strand = one_region[3]

                # Start analysis
                down = sys.maxsize # Distance to TTS
                exon_down = None
                last_index_down = last_index

                upst = sys.maxsize # Distance to TSS
                exon_up = None
                last_index_up = last_index

                last_index_body = last_index

                block_last_index = -1

                # When flagGeneBody is False, we will report downstream or upstream exons
                # Otherwise, we will only report the overlapped exons
                flagGeneBody = False

                # Array containing the relations that are going to be reported
                # [Candidate's]
                myfinaloutput = []

                # This dictionaries will contain as a key [geneID_transcriptID] and as values will be a vector
                # containing [[Candidate, area_length, overlapped_area],[Candidate, area_length, overlapped_area]...]
                # This is because there will be regions that will overlap different introns or exons, so we need to have all
                # this information, and once we know all the overlaps, we will recalculate the percentages of overlap.
                myIntrons = {}
                myGeneBodys = {}

                for i in range(last_index, len(gene_vector)):

                    mygene = gene_vector[i]

                    # If enabled, force the strand checking and skip if they are not equal
                    if check_strand and strand != None and mygene.getStrand() != strand:
                        continue

                    distanceToStartGene = abs(mygene.getStart() - pm)

                    if mygene.getStart() > end and (flagGeneBody is True or down < distanceToStartGene or upst < distanceToStartGene):

                        # We update the point from we will keep on looking at exons for new regions
                        if block_last_index == -1: # We can keep updating
                            last_index = last_index_down if last_index_down < last_index_up else last_index_up
                            last_index = last_index_body if last_index_body < last_index else last_index
                        else:
                            last_index = block_last_index


                        break

                    else: # Check associations
                        for mytranscript in mygene.getTranscripts():

                            myexons = mytranscript.getExons()

                            # Calculate TSSdist using the first exon "start" position.
                            # With positive strands ([0] = first exon), the
                            # position will be getStart().
                            # In negative strands ([-1]), the position will be getEnd()
                            if (myexons[0].getExon() == '1'):
                                TSSdistance = myexons[0].getStart() - pm
                                TTSdistance = myexons[-1].getEnd() - pm
                            else:
                                TSSdistance = pm - myexons[-1].getEnd()
                                TTSdistance = pm - myexons[0].getStart()

                            for j in range(len(myexons)):

                                exon = myexons[j]
                                isFirstExon = True if j == 0 else False
                                isLastExon  = True if j == (len(myexons) - 1) else False
                                exon_length    = exon.getEnd() - exon.getStart() + 1

                                # 1. Exon before the region
                                #
                                #     <--------->
                                #                    |--------------|
                                #

                                if exon.getEnd() < start:

                                    # Check whether the current gene also covers the region
                                    if block_last_index == -1 and mygene.getEnd() > start:
                                        block_last_index = i

                                    dist_tmp = pm - exon.getEnd()
                                    # Check if it's the last exon
                                    if isLastExon is True:
                                        if mygene.getStrand() == "+" and dist_tmp < down:
                                            down = dist_tmp
                                            exon_down = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), "DOWNSTREAM", mytranscript.getTranscriptID(), mygene.getGeneID(),down, 100, -1, TSSdistance, TTSdistance)
                                            last_index_down = i
                                        elif mygene.getStrand() == "-" and dist_tmp < upst:
                                            upst = dist_tmp
                                            exon_up = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), "UPSTREAM", mytranscript.getTranscriptID(), mygene.getGeneID(),upst, 100, -1, TSSdistance, TTSdistance)
                                            last_index_up = i

                                    else:
                                        # Check if the next exon is closer to the region
                                        next_exon = myexons[j+1]

                                        if next_exon.getStart() > start:
                                            flagGeneBody = True
                                            intron_length = next_exon.getStart() - exon.getEnd() - 1
                                            # The next exon is after the region
                                            if next_exon.getStart() > end:
                                                pctg_region   = 100
                                                pctg_area     = (float(region_length)/intron_length)*100
                                                intron_number = (j + 1) if mygene.getStrand() == "+" else (len(myexons) - 1 - j)

                                                myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                                intron_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), str(intron_number), "INTRON", mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                                if myid not in myIntrons:
                                                    myIntrons[myid] = [[intron_candidate, intron_length, region_length]]
                                                else:
                                                    myIntrons[myid].append([intron_candidate, intron_length, region_length])

                                                break
                                            # The next exon overlaps with the region
                                            else:
                                                region_overlap = next_exon.getStart() - start
                                                pctg_region    = (float(region_overlap)/region_length)*100
                                                pctg_area      = (float(region_overlap)/intron_length)*100
                                                intron_number = (j + 1) if mygene.getStrand() == "+" else (len(myexons) - 1 - j)

                                                myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                                intron_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), str(intron_number), "INTRON", mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                                if myid not in myIntrons:
                                                    myIntrons[myid] = [[intron_candidate, intron_length, region_overlap]]
                                                else:
                                                    myIntrons[myid].append([intron_candidate, intron_length, region_overlap])

                                # 2. Exon overlapping partially the region
                                #
                                #     <--------->
                                #          |--------------|
                                #
                                elif start <= exon.getEnd() <= end and exon.getStart() <  start:

                                    if last_index_body == last_index:
                                        last_index_body = i

                                    flagGeneBody = True
                                    body_overlap = exon.getEnd() - start + 1
                                    pctg_region  = (float(body_overlap)/region_length)*100
                                    pctg_area    = (float(body_overlap)/exon_length) * 100

                                    if isFirstExon and mygene.getStrand() == "+" or isLastExon and mygene.getStrand() == "-":
                                        tag = "1st_EXON"
                                        myfinaloutput.append(Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance))
                                    else:
                                        tag = "GENE_BODY"
                                        myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                        gb_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                        if myid not in myGeneBodys:
                                            myGeneBodys[myid] = [[gb_candidate, exon_length, body_overlap]]
                                        else:
                                            myGeneBodys[myid].append([gb_candidate, exon_length, body_overlap])

                                    if exon.getEnd() < end:
                                        if isLastExon is True:
                                            region_overlap = end - exon.getEnd()
                                            pctg_region    = (float(region_overlap)/region_length)*100
                                            if mygene.getStrand() == "+":
                                                tag = "DOWNSTREAM"
                                                exon_down = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                if tts > 0:
                                                    mychecks = checkTTS(start, end, exon_down)
                                                    for assoc in mychecks:
                                                        myfinaloutput.append(Candidate(exon_down.getStart(), exon_down.getEnd(), exon_down.getStrand(), exon_down.getExonNr(), assoc[0], exon_down.getTranscript(), exon_down.getGene(), exon_down.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))
                                                else:
                                                    myfinaloutput.append(exon_down)
                                            else:
                                                tag = "UPSTREAM"
                                                exon_up = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                mychecks = checkTSS(start, end, exon_up)
                                                for assoc in mychecks:
                                                    myfinaloutput.append(Candidate(exon_up.getStart(), exon_up.getEnd(), exon_up.getStrand(), exon_up.getExonNr(), assoc[0], exon_up.getTranscript(), exon_up.getGene(), exon_up.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))

                                        else:

                                            next_exon = myexons[j+1]

                                            intron_length  = next_exon.getStart() - exon.getEnd() - 1
                                            intron_number = (j + 1) if mygene.getStrand() == "+" else (len(myexons) - 1 - j)

                                            if next_exon.getStart() > end:
                                                region_overlap = end - exon.getEnd()
                                                pctg_region    = (float(region_overlap)/region_length)*100
                                                pctg_area      = (float(region_overlap)/intron_length)*100

                                                myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                                intron_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), str(intron_number), "INTRON", mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                                if myid not in myIntrons:
                                                    myIntrons[myid] = [[intron_candidate, intron_length, region_overlap]]
                                                else:
                                                    myIntrons[myid].append([intron_candidate, intron_length, region_overlap])

                                                break
                                            else:
                                                region_overlap = next_exon.getStart() - exon.getEnd() - 1
                                                pctg_region    = (float(region_overlap)/region_length)*100
                                                pctg_area      = (float(region_overlap)/intron_length)*100

                                                myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                                intron_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), str(intron_number), "INTRON", mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                                if myid not in myIntrons:
                                                    myIntrons[myid] = [[intron_candidate, intron_length, region_overlap]]
                                                else:
                                                    myIntrons[myid].append([intron_candidate, intron_length, region_overlap])

                                # 3. Exon completely inside the region
                                #
                                #     <--------->
                                #   |--------------|
                                #
                                elif start <= exon.getStart() and end >= exon.getEnd():
                                    flagGeneBody = True

                                    if start < exon.getStart():
                                        if isFirstExon is True:
                                            region_overlap = exon.getStart() - start
                                            pctg_region = (float(region_overlap)/region_length)*100

                                            if mygene.getStrand() == "-":
                                                tag = "DOWNSTREAM"
                                                exon_down = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                if tts > 0:
                                                    mychecks = checkTTS(start, end, exon_down)
                                                    for assoc in mychecks:
                                                        myfinaloutput.append(Candidate(exon_down.getStart(), exon_down.getEnd(), exon_down.getStrand(), exon_down.getExonNr(), assoc[0], exon_down.getTranscript(), exon_down.getGene(), exon_down.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))
                                                else:
                                                    myfinaloutput.append(exon_down)

                                            else:
                                                tag = "UPSTREAM"
                                                exon_up = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                mychecks = checkTSS(start, end, exon_up)
                                                for assoc in mychecks:
                                                    myfinaloutput.append(Candidate(exon_up.getStart(), exon_up.getEnd(), exon_up.getStrand(), exon_up.getExonNr(), assoc[0], exon_up.getTranscript(), exon_up.getGene(), exon_up.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))

                                    region_overlap = exon.getEnd() - exon.getStart() + 1
                                    pctg_region = (float(region_overlap)/region_length)*100
                                    pctg_area   = 100

                                    if isFirstExon and mygene.getStrand() == "+" or isLastExon and mygene.getStrand() == "-":
                                        tag = "1st_EXON"
                                        myfinaloutput.append(Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance))
                                    else:
                                        tag = "GENE_BODY"
                                        myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                        gb_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                        if myid not in myGeneBodys:
                                            myGeneBodys[myid] = [[gb_candidate, exon_length, exon_length]]
                                        else:
                                            myGeneBodys[myid].append([gb_candidate, exon_length, exon_length])

                                    if end > exon.getEnd():
                                        if isLastExon is True:
                                            region_overlap = end - exon.getEnd()
                                            pctg_region    = (float(region_overlap)/region_length)*100

                                            if mygene.getStrand() == "+":
                                                tag = "DOWNSTREAM"
                                                exon_down = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                if tts > 0:
                                                    mychecks = checkTTS(start, end, exon_down)
                                                    for assoc in mychecks:
                                                        myfinaloutput.append(Candidate(exon_down.getStart(), exon_down.getEnd(), exon_down.getStrand(), exon_down.getExonNr(), assoc[0], exon_down.getTranscript(), exon_down.getGene(), exon_down.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))
                                                else:
                                                    myfinaloutput.append(exon_down)
                                            else:
                                                tag = "UPSTREAM"
                                                exon_up = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                mychecks = checkTSS(start, end, exon_up)
                                                for assoc in mychecks:
                                                    myfinaloutput.append(Candidate(exon_up.getStart(), exon_up.getEnd(), exon_up.getStrand(), exon_up.getExonNr(), assoc[0], exon_up.getTranscript(), exon_up.getGene(), exon_up.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))

                                        else:

                                            next_exon = myexons[j+1]

                                            intron_length  = next_exon.getStart() - exon.getEnd() - 1
                                            intron_number = (j + 1) if mygene.getStrand() == "+" else (len(myexons) - 1 - j)
                                            if next_exon.getStart() > end:
                                                region_overlap = end - exon.getEnd()
                                                pctg_region    = (float(region_overlap)/region_length)*100
                                                pctg_area      = (float(region_overlap)/intron_length)*100

                                                myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                                intron_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), str(intron_number), "INTRON", mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                                if myid not in myIntrons:
                                                    myIntrons[myid] = [[intron_candidate, intron_length, region_overlap]]
                                                else:
                                                    myIntrons[myid].append([intron_candidate, intron_length, region_overlap])

                                                break
                                            else:
                                                region_overlap = next_exon.getStart() - exon.getEnd() - 1
                                                pctg_region    = (float(region_overlap)/region_length)*100
                                                pctg_area      = (float(region_overlap)/intron_length)*100

                                                myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                                intron_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), str(intron_number), "INTRON", mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                                if myid not in myIntrons:
                                                    myIntrons[myid] = [[intron_candidate, intron_length, region_overlap]]
                                                else:
                                                    myIntrons[myid].append([intron_candidate, intron_length, region_overlap])

                                # 4. Exon overlapping the region but shifted to the right
                                #
                                #             <--------->
                                #   |--------------|
                                #
                                elif start <= exon.getStart() <= end and end < exon.getEnd():
                                    flagGeneBody = True
                                    if start < exon.getStart():
                                        if isFirstExon is True:
                                            region_overlap = exon.getStart() - start
                                            pctg_region = (float(region_overlap)/region_length)*100

                                            if mygene.getStrand() == "-":
                                                tag = "DOWNSTREAM"
                                                exon_down = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                if tts > 0:
                                                    mychecks = checkTTS(start, end, exon_down)
                                                    for assoc in mychecks:
                                                        myfinaloutput.append(Candidate(exon_down.getStart(), exon_down.getEnd(), exon_down.getStrand(), exon_down.getExonNr(), assoc[0], exon_down.getTranscript(), exon_down.getGene(), exon_down.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))
                                                else:
                                                    myfinaloutput.append(exon_down)

                                            else:
                                                tag = "UPSTREAM"
                                                exon_up = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, -1, TSSdistance, TTSdistance)
                                                mychecks = checkTSS(start, end, exon_up)
                                                for assoc in mychecks:
                                                    myfinaloutput.append(Candidate(exon_up.getStart(), exon_up.getEnd(), exon_up.getStrand(), exon_up.getExonNr(), assoc[0], exon_up.getTranscript(), exon_up.getGene(), exon_up.getDistance(), assoc[1], assoc[2], TSSdistance, TTSdistance))

                                    region_overlap = end - exon.getStart() + 1
                                    pctg_region    = (float(region_overlap)/region_length)*100
                                    pctg_area      = (float(region_overlap)/exon_length)*100

                                    if isFirstExon and mygene.getStrand() == "+" or isLastExon and mygene.getStrand() == "-":
                                        tag = "1st_EXON"
                                        myfinaloutput.append(Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(), 0, pctg_region, pctg_area, TSSdistance, TTSdistance))
                                    else:
                                        tag = "GENE_BODY"
                                        myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                        gb_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(), 0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                        if myid not in myGeneBodys:
                                            myGeneBodys[myid] = [[gb_candidate, exon_length, region_overlap]]
                                        else:
                                            myGeneBodys[myid].append([gb_candidate, exon_length, region_overlap])

                                # 5. Region completely within the exon
                                #
                                #             <----------------->
                                #                 |---------|
                                #
                                elif exon.getStart() <= start <= exon.getEnd() and end < exon.getEnd():

                                    if last_index_body == last_index:
                                        last_index_body = i

                                    flagGeneBody = True
                                    region_overlap = region_length
                                    pctg_region    = 100
                                    pctg_area      = (float(region_overlap)/exon_length) * 100

                                    if isFirstExon and mygene.getStrand() == "+" or isLastExon and mygene.getStrand() == "-":
                                        tag = "1st_EXON"
                                        myfinaloutput.append(Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance))
                                    else:
                                        tag = "GENE_BODY"
                                        myid = mygene.getGeneID() + "_" + mytranscript.getTranscriptID()
                                        gb_candidate = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), tag, mytranscript.getTranscriptID(), mygene.getGeneID(),0, pctg_region, pctg_area, TSSdistance, TTSdistance)
                                        if myid not in myGeneBodys:
                                            myGeneBodys[myid] = [[gb_candidate, exon_length, region_overlap]]
                                        else:
                                            myGeneBodys[myid].append([gb_candidate, exon_length, region_overlap])

                                # 6. Exon totally after the region
                                #
                                #                       <----------------->
                                #   |---------|
                                #
                                elif exon.getStart() > end:
                                    if isFirstExon is True:

                                        dist_tmp = exon.getStart() - pm

                                        if mygene.getStrand() == "-" and dist_tmp < down:
                                            down = dist_tmp
                                            exon_down = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), "DOWNSTREAM", mytranscript.getTranscriptID(), mygene.getGeneID(), down, 100, -1, TSSdistance, TTSdistance)
                                        elif mygene.getStrand() == "+" and dist_tmp < upst:
                                            upst = dist_tmp
                                            exon_up = Candidate(exon.getStart(), exon.getEnd(), mygene.getStrand(), exon.getExon(), "UPSTREAM", mytranscript.getTranscriptID(), mygene.getGeneID(), upst, 100, -1, TSSdistance, TTSdistance)

                                        if down <= dist_tmp and upst <= dist_tmp:
                                            break

                if (down < upst or down == upst) and exon_down is not None and exon_down.getDistance() <= distance:
                    # Report Downstream
                    if tts > 0:
                        mychecks = checkTTS(start, end, exon_down)
                        for assoc in mychecks:
                            myfinaloutput.append(Candidate(exon_down.getStart(), exon_down.getEnd(), exon_down.getStrand(), exon_down.getExonNr(), assoc[0], exon_down.getTranscript(), exon_down.getGene(), exon_down.getDistance(), assoc[1], assoc[2], exon_down.getTSSdistance(), exon_down.getTTSdistance()))
                    else:
                        myfinaloutput.append(exon_down)

                if (upst < down or upst == down) and exon_up is not None and exon_up.getDistance() <= distance:
                    mychecks = checkTSS(start, end, exon_up)
                    for assoc in mychecks:
                        myfinaloutput.append(Candidate(exon_up.getStart(), exon_up.getEnd(), exon_up.getStrand(), exon_up.getExonNr(), assoc[0], exon_up.getTranscript(), exon_up.getGene(), exon_up.getDistance(), assoc[1], assoc[2], exon_up.getTSSdistance(), exon_up.getTTSdistance()))

                if flagGeneBody is True:
                    # Sum up cases overlapping different exons of the gene body
                    for myid in myGeneBodys:
                        if len(myGeneBodys[myid]) == 1:
                            myfinaloutput.append(myGeneBodys[myid][0][0])
                        else:
                            total_area = 0
                            total_overlap = 0
                            exon_nr = ""
                            for candidate in myGeneBodys[myid]:
                                total_area += candidate[1]
                                total_overlap += candidate[2]
                                myexon = candidate[0]
                                exon_nr = exon_nr + myexon.getExonNr() + ","
                            myexon = myGeneBodys[myid][0][0]
                            pctg_region = (float(total_overlap)/region_length)*100
                            pctg_area   = (float(total_overlap)/total_area)*100
                            myfinaloutput.append(Candidate(myexon.getStart(), myexon.getEnd(), myexon.getStrand(), exon_nr[:-1], myexon.getArea(), myexon.getTranscript(), myexon.getGene(), myexon.getDistance(), pctg_region, pctg_area, myexon.getTSSdistance(), myexon.getTTSdistance()))

                    # Sum up cases overlapping different introns of the gene body
                    for myid in myIntrons:
                        if len(myIntrons[myid]) == 1:
                            myfinaloutput.append(myIntrons[myid][0][0])
                        else:
                            total_area = 0
                            total_overlap = 0
                            intron_nr = ""
                            for candidate in myIntrons[myid]:
                                total_area += candidate[1]
                                total_overlap += candidate[2]
                                myexon = candidate[0]
                                intron_nr = intron_nr + myexon.getExonNr() + ","
                            myexon = myIntrons[myid][0][0]
                            pctg_region = (float(total_overlap)/region_length)*100
                            pctg_area   = (float(total_overlap)/total_area)*100
                            myfinaloutput.append(Candidate(myexon.getStart(), myexon.getEnd(), myexon.getStrand(), intron_nr[:-1], myexon.getArea(), myexon.getTranscript(), myexon.getGene(), myexon.getDistance(), pctg_region, pctg_area, myexon.getTSSdistance(), myexon.getTTSdistance()))

                reportOutput(myfinaloutput, dhs_id, start, end, salida, metainfo)

        salida.close()

        # CODE ADDED BY RAFA
        keys = list( allTranscripts.keys() )
        for i in keys:
            del allTranscripts[i]

        #keys = allTranscripts.keys()
        #for i in keys:
        #    del allTranscripts[i]

        import gc
        gc.collect()
        gc.enable()

        # Need to put something at the queue (the caller blocks on a get()).
        # None means "finished without raising" -- it says nothing about how
        # many associations were written, so the caller has to check the file.
        if managed_queue is not None:
            managed_queue.put(None)
    except Exception as e:
        if managed_queue is None:
            # Command-line path: no worker process to ferry the error out of.
            raise
        managed_queue.put(e)
        raise e


if __name__ == "__main__":
    main()

