EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "https://www.ensembl.org/biomart/martservice",
                    "file"          :   "ath_resources/ensembl_mapping.xml",
                    "output"        :   "ensembl_mapping.list",
                    "description"   :   "Source: Ensembl Mammals databases. Downloaded from Biomart."
                    }
                ],
                "refseq"   :  [
                    {
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/",
                    "file"          :   "gene2refseq.gz",
                    "output"        :   "refseq_gene2refseq.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per genomic/RNA/protein set of RefSeqs",
                    "specie-code"   :   10090
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Plants/",
                    "file"          :   "Arabidopsis_thaliana.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   10090
                    }
                ],
                 "uniprot"   :   [
                    {
                    "url"           :   "ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/",
                    "file"          :   "ARATH_3702_idmapping.dat.gz",
                    "output"        :   "uniprot_mapping.list",
                    "description"   :    "Source: UniProt idmapping_selected.tab. Downloaded from UniProt FTP. Tab-delimited table which includes the multiple mappings between UniProt Accession and external databases."
                    }
                ],
                "mapman_kegg"   :   [
                    {
                    "url"           :   "/home/tian/mapman/ath/",
                    "file"          :   "gene-to-entrez_ath.tsv",
                    "output"        :   "gene-to-entrez_ath.list",
                    "description"   :    "Source: <include description>"
                    }
                ],
                "mapman_gene"   :   [
                    {
                    "url"           :   "/home/tian/mapman/ath/",
                    "file"          :   "gene-to-mapman_ath.tsv",
                    "output"        :   "gene-to-mapman_ath.list",
                    "description"   :   "Source: <include description>"
                    }
                ],
                "mapman_pathways"   :   [
                    {
                    "url"           :   "/home/tian/mapman/common/",
                    "file"          :   "mapman_pathways.tar.gz",
                    "output"        :   "mapman_pathways.tar.gz",
                    "description"   :   "Source: <include description>"
                    }
                ],
                "mapman_classification"   :   [
                    {
                    "url"           :   "/home/tian/mapman/common/",
                    "file"          :   "mapman_classification.txt",
                    "output"        :   "mapman_classification.txt",
                    "description"   :   "Source: <include description>"
                    }
                ],
                "metabolites"	:	[                    
                    {
                    "url"           :   "/home/tian/mapman/common/",
                    "file"          :   "mapman_metabolites.txt",
                    "output"        :   "mapman_metabolites.txt",
                    "description"   :   "Source: <include description>"
                    }
                    ]
}
