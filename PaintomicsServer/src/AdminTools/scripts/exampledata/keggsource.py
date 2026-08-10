#!/usr/bin/env python3
"""Real identifiers for simulated data, read from an installed KEGG snapshot.

Why simulated data needs real IDs
---------------------------------
Enrichment is the thing worth testing, and enrichment is a statement about
pathway membership. Invented identifiers belong to no pathway, so a job built
on them completes with an empty result -- indistinguishable from a pipeline
that silently dropped everything. Every feature this package emits is therefore
a real identifier drawn from the installed snapshot.

The mapping chain, verified against the local snapshot
-----------------------------------------------------
PaintOmics accepts Ensembl gene IDs and translates them itself, so that is what
the bundled examples use. The translation is two hops:

    ENSMUSG00000000001 --ensembl_mapping.list--> 14679          (NCBI GeneID)
    14679              --KEGG naming for mouse--> mmu:14679
    mmu:14679          --gene2pathway.list-----> path:mmu04015, ...

The middle hop is not a lookup: KEGG's gene identifiers for mouse *are* NCBI
GeneIDs, so `mmu:` + the NCBI id is the KEGG id. Measured on the snapshot at
KEGG_DATA/current (VERSION 2025-11-18):

    ensembl -> ncbi pairs                 28270
    KEGG genes carrying >= 1 pathway      10632
    ensembl genes reaching >= 1 pathway   10406
    pathways with >= 15 ensembl genes       344

Reading is deliberately streaming and one pass per file: gene2pathway.list is
~1 MB but Ensembl2Reactome in the same tree is 916 MB, and a builder that grows
into reading it must not have to be rewritten to stay memory-safe.
"""
import collections
import os
import re

# A compound name that can be spliced into `.*<name>.*` without changing what
# the pattern means. Letters, digits, spaces, hyphens and apostrophes only, and
# it has to start with a letter so a bare formula is not mistaken for a name.
_NAME_SAFE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]*$")


# Pathways below this size give enrichment no power, so a planted signal in one
# of them cannot be recovered and the "expected pathways" file would lie.
MIN_PATHWAY_SIZE = 15

# How much of a pathway's membership is shared with OTHER pathways, averaged over
# its genes: `mean(len(pathwaysContaining(gene)) - 1)`. 0 means every member is
# private to this pathway; the mouse snapshot's worst offenders sit above 12.
#
# This number decides whether a planted signal stays where it was planted. KEGG
# pathways overlap heavily -- a mouse gene is in 3.85 pathways on average -- so
# planting 70% of a hub pathway's genes marks a sizeable slice of every pathway
# that shares genes with it. Measured on the previous generation of these
# fixtures: 562 of 10406 genes relevant (5.4%) but a mean per-pathway relevant
# rate of 18.4%, because the relevant genes sat in 13.5 pathways each against a
# background average of 3.85. Every pathway then looked ~3.4x enriched and the
# hypergeometric test called 207 of 364 significant. Planting only in pathways
# whose members are mostly their own keeps the excess where the ground-truth
# file says it is.
#
# The ladder rather than one cutoff: a stricter cap leaves fewer candidates, and
# a snapshot with a different pathway catalogue must still be able to build. The
# first rung that offers at least twice as many pathways as the scenario needs
# wins, so the choice is deterministic and recorded.
PERIPHERAL_LEAKAGE_LADDER = (2.5, 3.0, 3.5, 4.0, None)

# KEGG's global maps. Every gene is in mmu01100 ("Metabolic pathways"), so
# planting a signal there says nothing about whether enrichment works, and its
# 1653 members would swamp the background. Excluded from target selection only;
# the genes themselves stay in the data.
GLOBAL_PATHWAYS = frozenset({
    "mmu01100",  # Metabolic pathways
    "mmu01110",  # Biosynthesis of secondary metabolites
    "mmu01120",  # Microbial metabolism in diverse environments
    "mmu01200",  # Carbon metabolism
    "mmu01210",  # 2-Oxocarboxylic acid metabolism
    "mmu01212",  # Fatty acid metabolism
    "mmu01230",  # Biosynthesis of amino acids
    "mmu01232",  # Nucleotide metabolism
    "mmu01250",  # Biosynthesis of nucleotide sugars
    "mmu04740",  # Olfactory transduction -- 1182 genes, biologically irrelevant here
    "mmu03040",  # Spliceosome -- 1012 genes
})


class SpeciesNotInstalled(Exception):
    """Raised with the directory looked in and the command that fixes it."""


class KeggSource(object):
    """Identifier universe for one species, loaded once and queried many times.

    Attributes are built eagerly in __init__ because every caller needs all of
    them and the files are small; lazy loading would only add branches.
    """

    def __init__(self, keggDataDir, species="mmu"):
        self.species = species
        self.speciesDir = os.path.join(keggDataDir, "current", species)
        self.commonDir = os.path.join(keggDataDir, "current", "common")

        if not os.path.isdir(self.speciesDir):
            raise SpeciesNotInstalled(
                "species '%s' is not installed under %s\n"
                "Install it first:  python src/AdminTools/DBManager.py "
                "--download --install --specie %s"
                % (species, self.speciesDir, species))

        self._ensemblToNcbi = self._readEnsemblMapping()
        self._ncbiToPathways = self._readGeneToPathway()
        self.pathwayToGenes = self._buildPathwayToGenes()
        self.geneToPathways = self._invert(self.pathwayToGenes)
        self.pathwayNames = self._readPathwayNames()
        self.pathwayToCompounds = self._readPathwayToCompound()
        self.compoundNames = self._readCompoundNames()
        # Compound -> the pathways OF THIS SPECIES it appears in. The compound
        # file is keyed by KEGG's reference maps, which cover every organism, so
        # counting shared membership over all of them would call a compound
        # promiscuous on the strength of pathways the mouse does not have.
        self._compoundToPathways = self._invert(
            {pathway: self.compoundsIn([pathway])
             for pathway in self.pathwayToGenes})

    # -- loaders ------------------------------------------------------------

    def _readEnsemblMapping(self):
        """`ENSMUSG<TAB>NCBI<TAB>ENSMUSP<TAB>ENSMUST`, columns 2-4 often blank.

        Keeps the FIRST NCBI id seen for a gene. The file lists one row per
        transcript, so a multi-transcript gene repeats; every row of a given
        gene carries the same NCBI id, and taking the first avoids holding a
        set per gene for no gain.
        """
        path = os.path.join(self.speciesDir, "mapping", "ensembl_mapping.list")
        mapping = {}
        if not os.path.isfile(path):
            raise SpeciesNotInstalled(
                "no ensembl_mapping.list under %s; the species is installed "
                "but its identifier mappings are not."
                % os.path.dirname(path))

        with open(path) as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                gene, ncbi = parts[0].strip(), parts[1].strip()
                # A blank NCBI column is ordinary -- non-coding genes and
                # Ensembl-only models have no NCBI counterpart. They simply
                # cannot reach a pathway, so they are not useful here.
                if gene and ncbi and gene not in mapping:
                    mapping[gene] = ncbi
        return mapping

    def _readGeneToPathway(self):
        """`mmu:14679<TAB>path:mmu04015` -> {ncbiID: [pathwayID, ...]}."""
        path = os.path.join(self.speciesDir, "gene2pathway.list")
        grouped = collections.defaultdict(list)
        if not os.path.isfile(path):
            raise SpeciesNotInstalled(
                "no gene2pathway.list under %s; is the species fully installed?"
                % self.speciesDir)

        prefix = self.species + ":"
        with open(path) as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                gene, pathway = parts[0].strip(), parts[1].strip()
                if gene.startswith(prefix):
                    gene = gene[len(prefix):]
                if pathway.startswith("path:"):
                    pathway = pathway[len("path:"):]
                if gene and pathway:
                    grouped[gene].append(pathway)
        return dict(grouped)

    def _buildPathwayToGenes(self):
        """{pathwayID: sorted[ENSMUSG...]} -- the index the planting needs.

        Sorted so a fixed seed yields a fixed sample: `random.sample` over a
        set, or over dict insertion order, is reproducible only by accident.
        """
        grouped = collections.defaultdict(set)
        for gene, ncbi in self._ensemblToNcbi.items():
            for pathway in self._ncbiToPathways.get(ncbi, ()):
                grouped[pathway].add(gene)
        return {pathway: sorted(genes) for pathway, genes in grouped.items()}

    @staticmethod
    def _invert(mapping):
        """{key: [member, ...]} -> {member: frozenset(keys)}.

        Used for both gene->pathways and compound->pathways. Frozen sets rather
        than lists because every caller asks only "how many" or "is it in", and
        a frozenset makes accidental mutation of the index impossible.
        """
        inverted = collections.defaultdict(set)
        for key, members in mapping.items():
            for member in members:
                inverted[member].add(key)
        return {member: frozenset(keys) for member, keys in inverted.items()}

    def _readPathwayNames(self):
        """`mmu00010<TAB>Glycolysis ... - Mus musculus (house mouse)`.

        The species suffix is stripped: it is identical on every row and only
        makes the generated README harder to read.
        """
        path = os.path.join(self.speciesDir, "pathways.list")
        names = {}
        if not os.path.isfile(path):
            return names
        with open(path) as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                title = parts[1].strip()
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip()
                names[parts[0].strip()] = title
        return names

    def _readPathwayToCompound(self):
        """{pathwayID: sorted[C#####]}, tolerant of either column orientation.

        The released file is `path:mmu00010<TAB>cpd:C00022` in some KEGG
        releases and the reverse in others, so orientation is decided per row
        by which field looks like a compound rather than assumed for the file.
        """
        path = os.path.join(self.commonDir, "pathway2compound.list")
        grouped = collections.defaultdict(set)
        if not os.path.isfile(path):
            return {}

        with open(path) as handle:
            for line in handle:
                parts = [p.strip().replace("path:", "").replace("cpd:", "")
                         for p in line.rstrip("\n").split("\t")]
                if len(parts) < 2:
                    continue
                first, second = parts[0], parts[1]
                if _looksLikeCompound(second):
                    grouped[first].add(second)
                elif _looksLikeCompound(first):
                    grouped[second].add(first)
        return {pathway: sorted(compounds) for pathway, compounds in grouped.items()}

    def _readCompoundNames(self):
        """`C00002<TAB>ATP; Adenosine 5'-triphosphate` -> {C00002: [names]}.

        The whole synonym list, in file order, because the first entry is the
        one KEGG treats as primary and the rest are what a real metabolomics
        table is likely to be keyed by. `common_build_database.py` splits the
        same field on `"; "` and inserts every synonym into `kegg_compounds`,
        so a name taken from here is a name the running server can resolve.
        """
        path = os.path.join(self.commonDir, "compounds_all.list")
        names = {}
        if not os.path.isfile(path):
            return names
        with open(path) as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                synonyms = [name.strip() for name in parts[1].split(";")
                            if name.strip()]
                if synonyms:
                    names[parts[0].strip()] = synonyms
        return names

    # -- queries ------------------------------------------------------------

    def pathwayLeakage(self, pathway):
        """Mean number of OTHER pathways this pathway's genes also belong to.

        The measure that decides whether a planted signal stays put; see
        PERIPHERAL_LEAKAGE_LADDER. 0.0 for a pathway whose genes are all its
        own, and unbounded upwards for a hub.
        """
        genes = self.pathwayToGenes.get(pathway, ())
        if not genes:
            return 0.0
        return sum(len(self.geneToPathways[gene]) - 1
                   for gene in genes) / float(len(genes))

    def compoundLeakage(self, compound):
        """How many pathways OF THIS SPECIES the compound appears in."""
        return len(self._compoundToPathways.get(compound, ()))

    def eligiblePathways(self, minSize=MIN_PATHWAY_SIZE, maxLeakage=None,
                         minCompounds=0):
        """Pathways a planted signal could actually be recovered from.

        `maxLeakage` keeps out the hubs whose members are mostly other
        pathways' members too; `minCompounds` keeps out the pathways that carry
        no metabolites, which a scenario planting a compound signal cannot use.
        Both default to off, so the unfiltered call means what it always did.
        """
        return sorted(
            pathway for pathway, genes in self.pathwayToGenes.items()
            if len(genes) >= minSize
            and pathway not in GLOBAL_PATHWAYS
            and (maxLeakage is None or self.pathwayLeakage(pathway) <= maxLeakage)
            and (not minCompounds or len(self.compoundsIn([pathway])) >= minCompounds))

    def peripheralPathways(self, count, minCompounds=0,
                           ladder=PERIPHERAL_LEAKAGE_LADDER):
        """The least-shared pathways, loose enough to still offer a choice.

        Returns `(pathways, maxLeakage)`: the first rung of the ladder that
        offers at least `2 * count` candidates, so a scenario asking for `count`
        targets has something to sample rather than a forced hand. The cap that
        was used is returned so the scenario can record it -- a fixture whose
        properties depend on a threshold should say which threshold.
        """
        pool, chosenCap = [], ladder[-1]
        for cap in ladder:
            pool = self.eligiblePathways(maxLeakage=cap, minCompounds=minCompounds)
            chosenCap = cap
            if len(pool) >= 2 * count:
                break
        return pool, chosenCap

    def allGenes(self):
        """Every Ensembl gene reaching at least one pathway, sorted."""
        return sorted({gene
                       for genes in self.pathwayToGenes.values()
                       for gene in genes})

    def genesIn(self, pathways):
        """Union of the members of `pathways`, sorted."""
        union = set()
        for pathway in pathways:
            union.update(self.pathwayToGenes.get(pathway, ()))
        return sorted(union)

    def allCompounds(self):
        """Every compound in a pathway THIS SPECIES has, sorted.

        Not every compound in the file: `pathway2compound.list` is keyed by
        KEGG's reference maps and covers every organism, so it names ~6600
        compounds of which ~4600 are reachable from a mouse pathway. Shipping
        the other 2000 would put metabolites in the example that no mouse
        pathway can ever match -- they would show up as unmapped features and
        add nothing but noise to the compound panel.
        """
        return sorted({compound
                       for pathway in self.pathwayToGenes
                       for compound in self.compoundsIn([pathway])})

    def compoundsIn(self, pathways):
        """Compounds of `pathways`, translating species ids to reference maps.

        `pathway2compound.list` is keyed `map00010`, while every pathway id in
        this module is species-prefixed (`mmu00010`). Looking the species id up
        directly returns nothing for every pathway, silently -- which is what
        made the multi-omic example's compound layer carry no planted signal at
        all: `compoundsIn(targets)` came back empty and the caller fell through
        to a random sample of the whole compound universe. Both spellings are
        tried, because a future release keying the file by species id must not
        break this the other way round.
        """
        union = set()
        for pathway in pathways:
            union.update(self.pathwayToCompounds.get(pathway, ()))
            union.update(self.pathwayToCompounds.get(
                self._referenceMapID(pathway), ()))
        return sorted(union)

    def _referenceMapID(self, pathway):
        """`mmu00010` -> `map00010`; anything else is returned unchanged."""
        if pathway.startswith(self.species):
            return "map" + pathway[len(self.species):]
        return pathway

    def describe(self, pathway):
        return self.pathwayNames.get(pathway, pathway)

    def namedCompounds(self, compounds):
        """[(compoundID, name)] for the compounds a *name*-keyed file may use.

        The server resolves a compound name with a MongoDB regex --
        `findCompoundIDByFeatureName` builds `.*<name>.*` and runs it against
        `kegg_compounds.name` -- so a name is only usable here if it survives
        being spliced into a regular expression:

        * anything outside letters, digits, space, hyphen and apostrophe is
          dropped. `NAD+` would ask for one-or-more `D`, `Fe(II)` opens a group,
          and `[Protein]-lysine` opens a character class that never closes,
          which raises inside the driver and is caught as "no match" -- an
          unmapped feature with no explanation.
        * names shorter than five characters are dropped: as a substring
          pattern they match half the catalogue, and the matched-metabolites
          step then shows a wall of candidates for a name that is not ambiguous
          in reality.
        * one compound per name. Two compounds sharing a primary name would
          collide as row identifiers in a values file, and the second row would
          overwrite the first.

        Returns the pairs in `compounds` order so the caller keeps control of
        which compounds it prefers.
        """
        used, pairs = set(), []
        for compound in compounds:
            for name in self.compoundNames.get(compound, ()):
                if len(name) < 5 or not _NAME_SAFE_RE.match(name):
                    continue
                key = name.lower()
                if key in used:
                    continue
                used.add(key)
                pairs.append((compound, name))
                break
        return pairs


def _looksLikeCompound(token):
    """KEGG compound accession: 'C' followed by digits, e.g. C00022."""
    return len(token) > 1 and token[0] == "C" and token[1:].isdigit()
