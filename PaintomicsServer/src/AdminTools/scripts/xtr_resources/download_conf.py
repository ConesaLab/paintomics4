# Xenopus tropicalis. This file was missing entirely: xtr_resources shipped a
# download_others.py that loads <specie>_resources/download_conf.py by
# convention, so every xtr download died at that import (FileNotFoundError,
# observed on the 2026-08-14 full reinstall) and the species had never been
# installable. Modeled on dre_resources (the other non-mammalian vertebrate
# with the same build shape).
#
# Deliberately no "uniprot" section: UniProt's by_organism directory publishes
# idmapping_selected.tab.gz for ~20 reference proteomes only and has no Xenopus
# file (checked 2026-08-14), and xtr's build_database.py never had a UniProt
# processing step to consume one. download_others.py reads only "ensembl" and
# "refseq".
EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "https://ftp.ensembl.org/pub/",
                    "species-dir"   :   "xenopus_tropicalis",
                    "division"      :   "vertebrates",
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
                    "specie-code"   :   8364
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Non-mammalian_vertebrates/",
                    "file"          :   "Xenopus_tropicalis.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   8364
                    }
                ]
        }
