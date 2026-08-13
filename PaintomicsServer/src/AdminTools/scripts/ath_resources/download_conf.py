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
                    "species-dir"   :   "arabidopsis_thaliana",
                    "division"      :   "plants",
                    "output"        :   "ensembl_mapping.list",
                    "description"   :   "Source: Ensembl cross-reference TSV dumps. BioMart was retired (martservice answers HTTP 405), so the release/assembly and filename are resolved at run time rather than pinned here."
                    }
                ],
                "refseq"   :  [
                    {
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/",
                    "file"          :   "gene2refseq.gz",
                    "output"        :   "refseq_gene2refseq.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per genomic/RNA/protein set of RefSeqs",
                    "specie-code"   :   3702
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Plants/",
                    "file"          :   "Arabidopsis_thaliana.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   3702
                    }
                ],
                 "uniprot"   :   [
                    {
                    "url"           :   "ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/",
                    "file"          :   "ARATH_3702_idmapping_selected.tab.gz",
                    "output"        :   "uniprot_mapping.list",
                    "description"   :    "Source: UniProt idmapping_selected.tab. Downloaded from UniProt FTP. Tab-delimited table which includes the multiple mappings between UniProt Accession and external databases."
                    }
                ],
                "mapman_kegg"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "gene-to-entrez_ath.tsv.gz",
                    "output"        :   "gene-to-entrez_ath.list",
                    "decompress"    :   True,
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Paintomics export. Araport11 gene ID -> NCBI Entrez gene ID."
                    }
                ],
                "mapman_gene"   :   [
                    {
                    "url"           :   GOMAPMAN_PAINTOMICS,
                    "file"          :   "gene-to-mapman_ath.tsv.gz",
                    "output"        :   "gene-to-mapman_ath.list",
                    "decompress"    :   True,
                    "expect"        :   "tsv",
                    "description"   :   "Source: GoMapMan Paintomics export. Araport11 gene ID -> MapMan ontology bins."
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
