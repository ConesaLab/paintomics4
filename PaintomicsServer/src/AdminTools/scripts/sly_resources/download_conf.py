#**************************************************************************
# GoMapMan publishes the MapMan inputs Paintomics needs, in the exact layout
# this installer expects - it maintains a "paintomics" export target
# alongside its MapMan/GSEA/BioMine ones. These prefixes replace the private
# /home/tian/mapman/ directory the MapMan organisms used to be built from.
#
# Browse the tree with: https://gomapman.nib.si/api/GetFolderInfo/
# %7C is the '|' path separator the export API uses.
#**************************************************************************
GOMAPMAN_PAINTOMICS = "https://gomapman.nib.si/api/GetFile/protein_2018-05-25%7Cpaintomics%7C"
GOMAPMAN_METABOLITE = "https://gomapman.nib.si/api/GetFile/metabolite_2018-02-06%7Cmapman%7C"

EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "https://ftp.ebi.ac.uk/ensemblgenomes/pub/current/",
                    "species-dir"   :   "solanum_lycopersicum_gca000188115v5cm",
                    "division"      :   "plants",
                    "output"        :   "ensembl_mapping.list",
                    "description"   :   "Source: Ensembl cross-reference TSV dumps. BioMart was retired (martservice answers HTTP 405), so the release/assembly and filename are resolved at run time rather than pinned here."
                    },
                    {
                    "url"           :   "https://ftp.ebi.ac.uk/ensemblgenomes/pub/current/",
                    "species-dir"   :   "solanum_lycopersicum_gca000188115v5cm",
                    "division"      :   "plants",
                    "xref-type"     :   "uniprot",
                    "xref-db"       :   ["Uniprot/SWISSPROT", "Uniprot/SPTREMBL"],
                    "output"        :   "uniprot_mapping.list",
                    "description"   :   "Source: Ensembl UniProt cross-reference TSV dumps. BioMart was retired (martservice answers HTTP 405), so the release/assembly and filename are resolved at run time rather than pinned here."
                    }
                ],
                "mapman_kegg"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "gene-to-entrez_sly.tsv.gz",
                    "output"        :   "gene-to-entrez_sly.list",
                    "decompress"    :   True,
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Paintomics export. ITAG gene ID -> NCBI Entrez gene ID."
                    }
                ],
                "mapman_gene"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "gene-to-mapman_sly.tsv.gz",
                    "output"        :   "gene-to-mapman_sly.list",
                    "decompress"    :   True,
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Paintomics export. ITAG gene ID -> MapMan ontology bins."
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
