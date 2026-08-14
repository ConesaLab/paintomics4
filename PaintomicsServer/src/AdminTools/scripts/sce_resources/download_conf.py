EXTERNAL_RESOURCES = {
                    "ensembl"   :   [
                    {
                    "url"           :   "https://ftp.ensembl.org/pub/",
                    "species-dir"   :   "saccharomyces_cerevisiae",
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
                    # NCBI keys S. cerevisiae rows by strain: 559292 (S288C), the same
                    # organism id already in the UniProt filename below. The species
                    # taxid 4932 matches only ~36 mitochondrial/placeholder rows.
                    "specie-code"   :   559292
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Fungi/",
                    "file"          :   "Saccharomyces_cerevisiae.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   559292
                    }
                ],
                 "uniprot"   :   [
                    {
                    "url"           :   "ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/by_organism/",
                    "file"          :   "YEAST_559292_idmapping_selected.tab.gz",
                    "output"        :   "uniprot_mapping.list",
                    "description"   :    "Source: UniProt idmapping_selected.tab. Downloaded from UniProt FTP. Tab-delimited table which includes the multiple mappings between UniProt Accession and external databases."
                    }
                ],
                "reactome": [
                    {
                        "url": "https://reactome.org/ContentService/data/pathways/top/4932",
                        "file": "",
                        "output": "reactome_top.json",
                        "description": "Source: Reactome top pathways in JSON. It contains the main pathways to be used to retrieve the others.."
                    }
                ]
        }
