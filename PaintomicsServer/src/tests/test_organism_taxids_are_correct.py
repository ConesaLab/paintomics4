"""Every organism's `specie-code` must be ITS OWN NCBI taxonomy id.

`specie-code` is not a label: `processRefSeqData` and `processRefSeqGeneSymbolData`
build the shell filter

    gunzip -c <Species>.gene_info.gz | awk '{if($1=="<specie-code>"){print $0}}'

and then re-check `entrez_tax != specie-code` per row. So a wrong taxid does not raise,
does not warn, and does not produce a partial result -- it matches ZERO rows of the
right file and the organism installs with no Entrez/RefSeq gene-symbol mapping at all.

Nine organisms shipped with a copy-pasted taxid (eight carried mouse's 10090, and
Plasmodium carried human's 9606), so none of them had NCBI identifiers. The values
below were read on 2026-08-12 from the first data row of each organism's own
gene_info.gz on ftp.ncbi.nih.gov, which is the same file the installer downloads.

Run:
    PYTHONPATH=PaintomicsServer python PaintomicsServer/src/tests/test_organism_taxids_are_correct.py
"""

import os
import re
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "AdminTools", "scripts")

# organism directory prefix -> NCBI taxonomy id, verified against the organism's own
# gene_info.gz. Add a row here when a new organism is added; do not copy an existing one.
#
# NCBI keys some organisms' gene_info rows by STRAIN, not species: the species
# taxid matches only a handful of placeholder rows there, so the strain id is
# the correct value even though the NCBI taxonomy names the species one.
# Verified 2026-08-14: sce 4932 matched ~36 mitochondrial/placeholder rows and
# pfa 5833 only 4 -- both organisms shipped with almost no Entrez mapping.
EXPECTED_TAXID = {
    "acs": 28377,   # Anolis carolinensis
    "ath": 3702,    # Arabidopsis thaliana
    "bta": 9913,    # Bos taurus
    "cel": 6239,    # Caenorhabditis elegans
    "cfa": 9615,    # Canis lupus familiaris
    "dme": 7227,    # Drosophila melanogaster
    "dre": 7955,    # Danio rerio
    "gga": 9031,    # Gallus gallus
    "hsa": 9606,    # Homo sapiens
    "mmu": 10090,   # Mus musculus
    "pfa": 36329,   # Plasmodium falciparum 3D7 (strain; species id 5833 matches 4 rows)
    "ptr": 9598,    # Pan troglodytes
    "rno": 10116,   # Rattus norvegicus
    "sce": 559292,  # Saccharomyces cerevisiae S288C (strain; species id 4932 matches ~36 rows)
    "ssc": 9823,    # Sus scrofa
    "xtr": 8364,    # Xenopus tropicalis
}

TAXID_PATTERN = re.compile(r'"specie-code"\s*:\s*(\d+)')


def declaredTaxids(organism):
    confPath = os.path.join(SCRIPTS_DIR, organism + "_resources", "download_conf.py")
    if not os.path.isfile(confPath):
        return None
    with open(confPath, encoding="utf-8") as handle:
        return {int(match) for match in TAXID_PATTERN.findall(handle.read())}


class OrganismTaxidTest(unittest.TestCase):

    def test_each_organism_declares_its_own_taxid(self):
        for organism, expected in sorted(EXPECTED_TAXID.items()):
            # subTest, so the first mismatching organism cannot hide the rest.
            with self.subTest(organism=organism):
                declared = declaredTaxids(organism)
                if declared is None:
                    continue  # organism directory not present in this checkout
                self.assertTrue(
                    declared,
                    organism + "_resources/download_conf.py declares no specie-code")
                self.assertEqual(
                    declared, {expected},
                    organism + " declares specie-code " + str(sorted(declared)) +
                    " but its NCBI taxonomy id is " + str(expected) +
                    ". A wrong taxid silently yields ZERO Entrez/RefSeq mappings for this "
                    "organism -- the awk filter matches no row of its own gene_info file.")

    def test_no_two_organisms_share_a_taxid(self):
        """The original bug was a copy-paste, and this is its signature."""
        seen = {}
        for organism in sorted(EXPECTED_TAXID):
            declared = declaredTaxids(organism)
            if not declared:
                continue
            for taxid in declared:
                self.assertNotIn(
                    taxid, seen,
                    organism + " and " + seen.get(taxid, "?") + " both declare taxid " +
                    str(taxid))
                seen[taxid] = organism

    def test_taxid_is_numeric_not_a_kegg_code(self):
        """`specie-code` is an NCBI taxid; a KEGG code here matches nothing."""
        for organism in sorted(EXPECTED_TAXID):
            confPath = os.path.join(SCRIPTS_DIR, organism + "_resources", "download_conf.py")
            if not os.path.isfile(confPath):
                continue
            with open(confPath, encoding="utf-8") as handle:
                content = handle.read()
            self.assertNotRegex(
                content, r'"specie-code"\s*:\s*["\']',
                organism + " quotes its specie-code; it must be a bare NCBI taxid integer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
