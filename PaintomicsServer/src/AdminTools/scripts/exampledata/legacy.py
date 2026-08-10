#!/usr/bin/env python3
"""The real STATegra data, registered rather than generated.

This is the mouse Ikaros time course PaintOmics has always shipped: six time
points of real published measurements. Nothing here rewrites a byte of it. The
files move into the same `datasets/` layout as the simulated scenarios and gain
manifest entries, so the loader has one way to find every example instead of one
way plus three hardcoded special cases.

There are three entries, not one, because the old code had three separate
hardcoded examples over this same dataset -- one per entry point:

    PathwayAcquisitionServlet  six omics, already mapped to genes
    Bed2GenesServlet           the DNase regions, before mapping
    MiRNA2GenesServlet         the miRNA table, before mapping

`stategra-multiomics` stays the **default**: clicking "Load example" without
choosing gives the real data, which is the behaviour that exists today.

Why no expected counts
----------------------
The same job yields 888/44 matched pathways on the deploy VM and 877/41 locally
because the two carry different KEGG snapshots. These entries record what the
files *are*, never what analysing them produces.
"""
import os


MULTIOMICS_FOLDER = "08-stategra-multiomics"
REGIONS_FOLDER = "09-stategra-regions"
MIRNA_FOLDER = "10-stategra-mirna"

# The six omics in the order the old hardcoded example built them, with the
# filenames it derived by mangling the omic name ("DNase-seq" -> "dnase").
# Explicit here so that mangling can be deleted from the servlet.
MULTIOMICS = [
    ("Gene expression",      "gene_expression",       "gene",     "genes"),
    ("Metabolomics",         "metabolomics",          "compound", "features"),
    ("Proteomics",           "proteomics",            "gene",     "features"),
    ("miRNA-seq",            "mirna",                 "gene",     "genes"),
    ("DNase-seq",            "dnase",                 "gene",     "genes"),
    ("Transcription factor", "transcription_factor",  "gene",     "genes"),
]

CONDITIONS = ["Ikaros/Control_0h", "Ikaros/Control_2h", "Ikaros/Control_6h",
              "Ikaros/Control_12h", "Ikaros/Control_18h", "Ikaros/Control_24h"]

_ENVIRONMENT_NOTE = ("Matched-pathway counts differ between KEGG snapshots "
                     "(888/44 on the deploy VM vs 877/41 locally for the same "
                     "job), so none are asserted.")


def _dataDir(context, folder):
    return os.path.join(context.outputRoot, folder, "data")


def _fileEntry(context, folder, name):
    """Relative path for `name`, or None when the file is not there.

    Returning None rather than raising keeps the generator usable on a checkout
    where the reorganisation has not been applied: the simulated scenarios still
    build, and the affected legacy entry is simply left out of the manifest.
    """
    path = os.path.join(_dataDir(context, folder), name)
    return context.relative(path) if os.path.isfile(path) else None


def buildStategraMultiomics(context):
    omics = []
    for omicName, stem, omicType, enrichment in MULTIOMICS:
        values = _fileEntry(context, MULTIOMICS_FOLDER, stem + "_values.tab")
        if values is None:
            return None
        entry = {
            "omicName": omicName,
            "omicType": omicType,
            "enrichment": enrichment,
            "dataFile": values,
        }
        relevant = _fileEntry(context, MULTIOMICS_FOLDER, stem + "_relevant.tab")
        if relevant:
            entry["relevantFile"] = relevant
        omics.append(entry)

    return {
        "id": "stategra-multiomics",
        "title": "STATegra — real mouse Ikaros time course (6 omics)",
        "summary": ("The published six-omic, six-timepoint STATegra dataset "
                    "PaintOmics has always shipped. Real measurements, not "
                    "simulated — the reference every simulated scenario is "
                    "shaped against."),
        "tests": ["The full multi-omic pipeline on real data",
                  "Metabolite hub analysis", "Pathway network", "AI interpretation"],
        "pipeline": "pathway-acquisition",
        "organism": "mmu",
        "databases": ["KEGG", "Reactome"],
        "conditions": CONDITIONS,
        "simulated": False,
        "omics": omics,
        "references": [],
        "expected": {"note": _ENVIRONMENT_NOTE},
    }


def buildStategraRegions(context):
    """The DNase regions *before* mapping -- input for Regions2Genes.

    Note the reference GTF: this scenario points at `GTF/sorted_mmu.gtf`, which
    a fresh checkout does not have (`examplefiles/GTF/` holds a zero-byte
    `.dummy`; the real annotation is fetched by a manual deploy step). The
    loader drops a scenario whose files are missing, so on a fresh checkout this
    one is simply not offered -- and the simulated `region-based` scenario,
    which carries its own annotation, is what users get instead.
    """
    values = _fileEntry(context, REGIONS_FOLDER, "dnase_unmapped_values.tab")
    relevant = _fileEntry(context, REGIONS_FOLDER, "dnase_unmapped_relevant.tab")
    if values is None:
        return None

    entry = {
        "id": "stategra-regions",
        "title": "STATegra — DNase regions (real, needs the mouse GTF)",
        "summary": ("The unmapped DNase-seq regions from the STATegra time "
                    "course, for the Regions2Genes step. Requires the full "
                    "mouse annotation, which is fetched by a deploy step and "
                    "is absent from a fresh checkout."),
        "tests": ["RGmatch on real regions", "Region-to-gene assignment at scale"],
        "pipeline": "regions2genes",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": CONDITIONS,
        "simulated": False,
        "omics": [{
            "omicName": "DNase unmapped",
            "omicType": "region",
            "enrichment": "genes",
            "dataFile": values,
        }],
        "references": [{
            "omicName": "DNase unmapped",
            "fileType": "Reference file",
            "dataFile": "GTF/sorted_mmu.gtf",
        }],
        "expected": {"note": _ENVIRONMENT_NOTE},
    }
    if relevant:
        entry["omics"][0]["relevantFile"] = relevant
    return entry


def buildStategraMirna(context):
    """The miRNA table plus the 31 MB miRBase->Ensembl map, for MiRNA2Genes."""
    values = _fileEntry(context, MIRNA_FOLDER, "mirna_unmapped_values.tab")
    relevant = _fileEntry(context, MIRNA_FOLDER, "mirna_unmapped_relevant.tab")
    reference = _fileEntry(context, MIRNA_FOLDER, "mmu_mirBase_to_ensembl.tab")
    geneValues = _fileEntry(context, MULTIOMICS_FOLDER, "gene_expression_values.tab")
    if values is None or reference is None or geneValues is None:
        return None

    omics = [{
        "omicName": "miRNA unmapped",
        "omicType": "gene",
        "enrichment": "genes",
        "role": "regulator",
        "dataFile": values,
    }, {
        "omicName": "Gene expression",
        "omicType": "gene",
        "enrichment": "genes",
        "role": "target",
        "dataFile": geneValues,
    }]
    if relevant:
        omics[0]["relevantFile"] = relevant

    return {
        "id": "stategra-mirna",
        "title": "STATegra — miRNA to genes (real)",
        "summary": ("The unmapped miRNA quantification from the STATegra time "
                    "course with the full miRBase-to-Ensembl target table, for "
                    "the Regulatory Omics step."),
        "tests": ["miRNA-to-gene association on real data",
                  "Correlation filtering across a large prediction table"],
        "pipeline": "mirna2genes",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": CONDITIONS,
        "simulated": False,
        "omics": omics,
        "references": [{
            "omicName": "miRNA unmapped",
            "fileType": "Reference file",
            "dataFile": reference,
        }],
        "expected": {"note": _ENVIRONMENT_NOTE},
    }


CATALOGUE = [
    buildStategraMultiomics,
    buildStategraRegions,
    buildStategraMirna,
]
