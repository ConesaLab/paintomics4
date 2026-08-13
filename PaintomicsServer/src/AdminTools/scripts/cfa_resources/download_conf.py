EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "https://ftp.ensembl.org/pub/",
                    "species-dir"   :   "canis_lupus_familiaris",
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
                    "specie-code"   :   9615
                    },{
                    "url"           :   "ftp://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Mammalia/",
                    "file"          :   "Canis_familiaris.gene_info.gz",
                    "output"        :   "refseq_gene2genesymbol.gz",
                    "description"   :   "Source: NCBI Gene. Downloaded from NCBI FTP. Tab-delimited one line per gene id/gene symbol/.../synonyms/... from RefSeqs",
                    "specie-code"   :   9615
                    }
                ]
        }
