# Retrieve the information for each entity
# Look before if the file exists as cache.
entity_filename = REACTOME_DIR + "/" + str(entity_id) + ".cache"

# if not os.path.exists(entity_filename):
stderr.write("\nDownload entity url file " + str(entity_id))
entity_url = COMMON_RESOURCES['reactome'].get("entity_url").format(entity_id)
downloadJSONFile(entity_url, "", entity_filename,
                 SERVER_SETTINGS.DOWNLOAD_DELAY_1,
                 SERVER_SETTINGS.MAX_TRIES_1, reuseDownloadedFiles)
stderr.write("... Done!\n")

# The file will contain all the elements associated to the particular node.
with open(entity_filename) as entity_info:
    entity_data = json.load(entity_info)

    stderr.write("\nLoading entity id " + str(entity_id))

    # Each possible feature
    for feature in entity_data:
        # Retrieve special query data to have access to "referenceGene" property
        feature_id = feature.get("dbId")

        feature_details_filename = REACTOME_DIR + "/" + str(
            feature_id) + "_details.cache"

        if not os.path.exists(feature_details_filename):
            stderr.write(
                "\nDownload feature DETAILS url file " + str(feature_id))
            feature_details_url = COMMON_RESOURCES['reactome'].get(
                "details_url").format(feature_id)
            downloadJSONFile(feature_details_url, "",
                             feature_details_filename,
                             SERVER_SETTINGS.DOWNLOAD_DELAY_1,
                             SERVER_SETTINGS.MAX_TRIES_1,
                             reuseDownloadedFiles)
            stderr.write("... Done!\n")

        with open(feature_details_filename) as feature_info:
            feature_data = json.load(feature_info)

            # Select the first gene as starting point
            gene_ids = list(
                feature.get("geneName", feature.get("name", [])))

            if len(gene_ids) < 1:
                stderr.write(
                    "NO LEN IN PATHWAY DATA OR EVENTS WITH REACTOME FEATURE ID " + str(
                        feature_id) + "\n")
                continue

            # Select the first one as default
            gene_id = gene_ids.pop(0)

            stderr.write("\n\tEntering gene id " + str(gene_id))

            pathway2gene[pathway_id].update([gene_id] + gene_ids)

            for gene in [gene_id] + gene_ids:
                gene2pathway[gene].add(pathway_id)

            entryAux = entry.copy()
            entryAux["id"] = gene_id

            # Other names
            reference_genes = [gene.get("identifier") for gene in
                               feature_data.get("referenceGene", [])]

            other_ids = set(reference_genes + gene_ids + [
                feature_data.get("identifier", "")])

            # schemaClass
            compoundTypes = ["ReferenceMolecule"]

            if feature.get("schemaClass") in compoundTypes:

                # Merge all compound IDs
                reactome_cpds = set([gene_id]).union(other_ids)
                common_cpds = set(KEGG_COMPOUNDS.keys()).intersection(
                    reactome_cpds)

                # Reuse the KEGG id
                if len(common_cpds):
                    reactome_cpd_id = KEGG_COMPOUNDS[list(common_cpds)[0]]

                    entryAux["id"] = reactome_cpd_id

                    # Add the remaining ids as synonyms
                    synonym_cpds = reactome_cpds.difference(common_cpds)
                else:
                    reactome_cpd_id = "RC" + str(
                        feature_data.get("identifier"))

                    entryAux["id"] = reactome_cpd_id

                    synonym_cpds = reactome_cpds

                # Add all the synonym identifiers under the same CPD id
                for synonym_cpd in synonym_cpds:
                    REACTOME_COMPOUNDS[synonym_cpd] = reactome_cpd_id

                ALL_PATHWAYS[pathway_id]["compounds"].append(entryAux)
            else:
                ALL_PATHWAYS[pathway_id]["genes"].append(entryAux)

                # Reactome may use as gene id symbols already provided by KEGG
                # or other linked databases. As Paintomics uses the database id
                # to properly identify which symbol to display, we need to have
                # a copy for reactome database, using an empty string so as to avoid
                # conflictions.
                previous_symbol_item = findXREFByEntry(gene_id)

                reactome_gi = insertXREF(
                    XREF_Entry(gene_id, reactome_gene_db_id,
                               reactome_gene_desc), dbname)

                if previous_symbol_item:
                    transcript_id = previous_symbol_item.getID()
                else:
                    # Generate a random ID for the reactome identifier
                    transcript_id = reactome_id_2_refseq_tid.get(
                        reactome_gi,
                        generateRandomID(dbname))  # Try to reuse the ids for random transcripts
                    reactome_id_2_refseq_tid[reactome_gi] = transcript_id

                # Save the reference
                insertTR_XREF(reactome_gi, transcript_id, dbname)

                for synonym_id in other_ids:
                    # Check if the id already exists as a previous XREF.
                    # Note: this requires KEGG mapping to be done BEFORE inserting
                    # reactome pathways.
                    stderr.write("\n\t\tSynonym " + str(synonym_id))

                    entity_item = findXREFByEntry(synonym_id)

                    if not entity_item:
                        entity_gi = insertXREF(XREF_Entry(synonym_id,
                                                          reactome_gene_db_id_other,
                                                          reactome_gene_desc_other),
                                               dbname)
                    else:
                        entity_gi = entity_item.getID()

                    insertTR_XREF(entity_gi, transcript_id, dbname)