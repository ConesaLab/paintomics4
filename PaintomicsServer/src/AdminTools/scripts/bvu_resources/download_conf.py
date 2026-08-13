#**************************************************************************
# GoMapMan publishes the MapMan inputs Paintomics needs, in the exact layout
# this installer expects - it maintains a "paintomics" export target
# alongside its MapMan/GSEA/BioMine ones. These prefixes replace the private
# /home/tian/mapman/ directory the MapMan organisms used to be built from.
#
# Browse the tree with: https://gomapman.nib.si/api/GetFolderInfo/
# %7C is the '|' path separator the export API uses.
#
# Note: sugar beet has no gene-to-entrez export in GoMapMan, so there is no
# "mapman_kegg" entry here and MapMan genes are not cross-linked to KEGG for
# this organism. download_others.py treats that key as optional.
#**************************************************************************
GOMAPMAN_PAINTOMICS = "https://gomapman.nib.si/api/GetFile/protein_2018-05-25%7Cpaintomics%7C"
GOMAPMAN_METABOLITE = "https://gomapman.nib.si/api/GetFile/metabolite_2018-02-06%7Cmapman%7C"

EXTERNAL_RESOURCES = {
                "mapman_gene"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "gene-to-mapman_bvu.tsv.gz",
                    "output"        :   "gene-to-mapman_bvu.list",
                    "decompress"    :   True,
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Paintomics export. RefBeet1.1 gene ID -> MapMan ontology bins."
                    }
                ],
                "mapman_extra_pathways"   :   [
                    {
                    # GoMapMan ships 20 diagrams, nearly all Secondary Metabolism
                    # and Hormones. This manifest adds the 50 general 3.6-era maps
                    # from the MapManStore archive - Metabolism overview, glycolysis,
                    # TCA, photosynthesis, transcription, Metabolites and the rest.
                    # Delete this entry to install the base 20 only.
                    "manifest"      :   "scripts/common_resources/mapman_extra_diagrams.json",
                    "description"   :   "Source: MapManStore pathway archive (plabipd.de). 3.6-era diagrams only; X4 diagrams use a renumbered ontology and are deliberately excluded."
                    }
                ],
                "mapman_pathways"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "mapman_pathways.tar.gz",
                    "output"        :   "mapman_pathways.tar.gz",
                    "expect"        :   "targz",
                    "description"   :   "Source: GoMapMan Paintomics export. 20 MapMan diagrams as xml/ layouts + png/ backgrounds."
                    }
                ],
                "mapman_classification"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "mapman_classification.txt",
                    "output"        :   "mapman_classification.txt",
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Paintomics export. Primary/secondary category per diagram."
                    }
                ],
                "metabolites"	:	[
                    {
                    "url"           :   GOMAPMAN_METABOLITE,
                    "file"          :   "plant_plant metabolites_2018-02-06_mapping.txt",
                    "output"        :   "mapman_metabolites.txt",
                    # The metabolite export carries a BINCODE/NAME/... header row.
                    # Left in place it becomes a compound literally named "NAME".
                    "skip_header"   :   True,
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Metabolite export (MapMan mapping format). Bin -> metabolite names."
                    }
                    ]
}
