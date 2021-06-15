EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "http://www.ensembl.org/biomart/martservice/",
                    "file"          :   "hsa_resources/ensembl_mapping.xml",
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
                    "specie-code"   :   9606
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Mammalia/",
                    "file"          :   "Homo_sapiens.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   9606
                    }
                ],
                 "uniprot"   :   [
                    {
                    "url"           :   "ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/",
                    "file"          :   "HUMAN_9606_idmapping_selected.tab.gz",
                    "output"        :   "uniprot_mapping.list",
                    "description"   :    "Source: UniProt idmapping_selected.tab. Downloaded from UniProt FTP. Tab-delimited table which includes the multiple mappings between UniProt Accession and external databases."
                    }
                ],
                "reactome": [
                    {
                        "url": "https://reactome.org/ContentService/data/pathways/top/9606",
                        "file": "",
                        "output": "reactome_top.json",
                        "description": "Source: Reactome top pathways in JSON. It contains the main pathways to be used to retrieve the others.."
                    }
                ],
        }