EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "http://www.ensembl.org/biomart/martservice/",
                    "file"          :   "bta_resources/ensembl_mapping.xml",
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
                    "specie-code"   :   9913
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Mammalia/",
                    "file"          :   "Bos_taurus.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   9913
                    }
                ],
        }
