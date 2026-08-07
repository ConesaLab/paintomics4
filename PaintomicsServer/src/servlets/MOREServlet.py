#***************************************************************
#  This file is part of Paintomics v4
#**************************************************************

import json
import logging
import os
import subprocess
import shutil
from src.classes.JobInstances.MOREJob import MOREJob
from src.common.UserSessionManager import UserSessionManager
from src.common.JobInformationManager import JobInformationManager
from src.servlets.DataManagementServlet import saveFile
from src.common.ServerErrorManager import handleException
from src.conf.serverconf import CLIENT_TMP_DIR, ROOT_DIRECTORY

def _toFloat(rawValue, default):
    """Coerce one submitted form field to a float, falling back to ``default``.

    ``dict.get(key, default)`` only yields the default when the key is
    *absent*. An HTML form posts fields that are present and empty, and this
    endpoint is reachable by any HTTP client regardless of what the ExtJS
    ``allowBlank: false`` enforces, so ``""``, ``None`` and junk must all land
    on the default instead of raising ValueError out of the request handler.
    """
    if rawValue is None:
        return default
    text = str(rawValue).strip()
    if not text:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _parseMinVariation(rawValue):
    """Per-omic low-variation filter for MORE's ``minVariation`` argument.

    Blank / "auto" / "NA" become the "NA" sentinel, which MORE reads as "use
    10% of the maximum observed variability across conditions". Anything else
    must parse as a non-negative float; malformed input falls back to 0.0
    (MORE's documented default) rather than aborting the job.
    """
    text = str(rawValue or "").strip()
    if text.lower() in ("", "auto", "na"):
        return "NA"
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        return 0.0


def _nonEmpty(rawValue, default):
    """A present-but-blank choice field must fall back to its default too."""
    text = str(rawValue or "").strip()
    return text or default


def fromMOREtoGenes_STEP1(REQUEST, RESPONSE, QUEUE_INSTANCE, JOB_ID):
    """
    Step 1: Receive the MORE submission form, save files, and initialize the job.
    JOB_ID is a randomly generated ID for this pre-processing job.
    """
    jobInstance = None
    userID = None

    try:
        # 1. Validate User
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        # 2. Initialize MORE Job (with its own unique ID)
        jobInstance = MOREJob(JOB_ID, userID, CLIENT_TMP_DIR)
        jobInstance.initializeDirectories()
        logging.info(f"MORE_STEP1 - NEW MORE JOB {JOB_ID}")

        formFields = REQUEST.form
        uploadedFiles = REQUEST.files

        # 3. Save Gene Expression Dataset
        rnaseq_file = uploadedFiles.get("rnaseqaux_file")
        if rnaseq_file:
            fields = {"omicType": "Gene Expression", "dataType": "Target Data"}
            jobInstance.targetExpressionFile = saveFile(userID, rnaseq_file.filename, fields, rnaseq_file, jobInstance.getInputDir())
        else:
            jobInstance.targetExpressionFile = formFields.get("rnaseqaux_filelocation", "").replace("[MyData]/", "")
            if not jobInstance.targetExpressionFile: jobInstance.targetExpressionFile = None

        # 4. Save Experimental Design (Conditions)
        cond_file = uploadedFiles.get("conditions_file")
        if cond_file:
            fields = {"omicType": "Experimental Design", "dataType": "Conditions file"}
            jobInstance.conditionsFile = saveFile(userID, cond_file.filename, fields, cond_file, jobInstance.getInputDir())
        else:
            # Check if it was already uploaded (fast-track/re-run)
            jobInstance.conditionsFile = formFields.get("conditions_filelocation", "").replace("[MyData]/", "")
            if not jobInstance.conditionsFile: jobInstance.conditionsFile = None

        # 5. Save Regulatory Omics
        # We expect a dynamic list of omics from the UI
        # For simplicity in this rewrite, we look for 'omic_name_X' fields
        i = 0
        while f"omic_name_{i}" in formFields:
            name = formFields.get(f"omic_name_{i}").strip()
            data_file = uploadedFiles.get(f"file_{i}_file")
            assoc_file = uploadedFiles.get(f"assoc_file_{i}_file")
            rel_file = uploadedFiles.get(f"relevant_file_{i}_file")

            data_path = None
            assoc_path = None
            rel_path = None

            if data_file:
                fields = {"omicType": name, "dataType": "Regulatory Data"}
                data_path = saveFile(userID, data_file.filename, fields, data_file, jobInstance.getInputDir())
            else:
                data_path = formFields.get(f"file_{i}_filelocation", "").replace("[MyData]/", "")
                if not data_path: data_path = None

            if assoc_file:
                fields = {"omicType": name, "dataType": "Associations"}
                assoc_path = saveFile(userID, assoc_file.filename, fields, assoc_file, jobInstance.getInputDir())
            else:
                assoc_path = formFields.get(f"assoc_file_{i}_filelocation", "").replace("[MyData]/", "")
                if not assoc_path: assoc_path = None

            if rel_file:
                fields = {"omicType": name, "dataType": "Relevant Features"}
                rel_path = saveFile(userID, rel_file.filename, fields, rel_file, jobInstance.getInputDir())
            else:
                rel_path = formFields.get(f"relevant_file_{i}_filelocation", "").replace("[MyData]/", "")
                if not rel_path: rel_path = None

            min_variation = _parseMinVariation(formFields.get(f"more_minvar_{i}"))

            jobInstance.addRegulatoryOmic(
                name, data_path, formFields.get(f"omic_type_{i}"),
                assoc_path, rel_path, minVariation=min_variation
            )
            i += 1

        # 6. Model Parameters
        # Every one of these goes through a blank-tolerant coercion: the client
        # hides the alpha/VIP fields when the method is not PLS1, and a hidden
        # ExtJS field still posts its (possibly cleared) value.
        jobInstance.method = _nonEmpty(formFields.get("more_method"), "PLS1")
        jobInstance.alpha = _toFloat(formFields.get("more_alpha"), 0.05)
        jobInstance.vip = _toFloat(formFields.get("more_vip"), 0.8)
        jobInstance.filter_r2 = _toFloat(formFields.get("more_filter_r2"), 0.0)
        jobInstance.enrichment = _nonEmpty(formFields.get("more_enrichment"), "genes")

        # 7. Queue job
        QUEUE_INSTANCE.enqueue(
            fn=fromMOREtoGenes_STEP2,
            args=(jobInstance, userID, RESPONSE, formFields),
            timeout=1800,  # 30 minutes
            job_id=JOB_ID
        )

        RESPONSE.setContent({
            "success": True,
            "jobID": JOB_ID
        })

    except Exception as e:
        logging.error(f"MORE_STEP1 - ERROR: {str(e)}")
        RESPONSE.setContent({"success": False, "message": str(e)})

    finally:
        return RESPONSE

def fromMOREtoGenes_STEP2(jobInstance, userID, RESPONSE, formFields):
    """
    Step 2: Run the R backend and return results.
    """
    try:
        logging.info(f"MORE_STEP2 - RUNNING R SCRIPT for {jobInstance.getJobID()}")
        
        # 1. Pre-flight Validation
        target_file = jobInstance.targetExpressionFile
        input_dir = jobInstance.getInputDir()
        output_dir = jobInstance.getOutputDir()
        temporal_dir = jobInstance.getTemporalDir()

        if not target_file or not os.path.exists(os.path.join(input_dir, target_file)):
             raise ValueError("Target Gene Expression file is missing. Please ensure it was uploaded in Step 1.")
        
        if not jobInstance.conditionsFile or not os.path.exists(os.path.join(input_dir, jobInstance.conditionsFile)):
             raise ValueError("Experimental Design (Conditions) file is missing.")

        # --omic_names is a COMMA-JOINED list that runMORE.R splits on comma to
        # pair each name with its data file, association file and minVariation
        # by position. A name that is empty or contains a comma desynchronises
        # those lists, and every failure mode is silent or unreadable:
        #
        #   "TF, ChIP"  -> R sees 2 omics and 1 data file, indexes past the end,
        #                  and dies with "missing value where TRUE/FALSE needed"
        #   ""  (last)  -> strsplit drops a trailing empty field entirely, so the
        #                  last omic vanishes and its data file is never read
        #   duplicates  -> both omics write MORE_output_<name>_<date>.tab and the
        #                  second silently overwrites the first
        #
        # Cheaper to refuse here, naming the omic, than to debug any of those.
        seenNames = set()
        for omic in jobInstance.regulatoryOmics:
            rawName = (omic.get("name") or "").strip()
            if not rawName:
                raise ValueError("Every regulatory omic needs a name; one was left blank.")
            if "," in rawName:
                raise ValueError(
                    f"Regulatory omic name '{rawName}' contains a comma, which is used "
                    "to separate omics internally. Please rename it.")
            # Collisions are decided on the SANITISED name, because that is what
            # both sides put in the filename: runMORE.R writes
            # gsub(" ", "_", trimws(name)) and STEP2 below reconstructs
            # name.strip().replace(" ", "_"). "TF A" and "TF_A" are distinct
            # names that produce the same file.
            safeName = rawName.replace(" ", "_")
            if safeName in seenNames:
                raise ValueError(
                    f"Regulatory omic '{rawName}' collides with another omic: both map "
                    f"to the file name '{safeName}', so one set of results would "
                    "overwrite the other. Please give them distinct names.")
            seenNames.add(safeName)

        for omic in jobInstance.regulatoryOmics:
            # STEP1 leaves "file" as None when neither an upload nor a
            # [MyData] location was given. os.path.join would then raise a bare
            # TypeError before the message below could explain what to fix.
            omicName = omic.get("name") or "(unnamed)"
            if not omic.get("file"):
                raise ValueError(f"No regulatory data file was provided for '{omicName}'.")
            omic_path = os.path.join(input_dir, omic["file"])
            if not os.path.exists(omic_path):
                raise ValueError(f"Regulatory data file for '{omicName}' not found: {omic['file']}")
            if os.path.getsize(omic_path) == 0:
                raise ValueError(f"Regulatory data file for '{omicName}' is empty.")

        # 2. Prepare Command
        # Derive server root from CLIENT_TMP_DIR, which is always an absolute path in serverconf.
        server_root = os.path.dirname(CLIENT_TMP_DIR.rstrip('/'))
        r_script = os.path.join(server_root, "src", "common", "bioscripts", "runMORE.R")
        
        cmd = [
            "Rscript", r_script,
            "--target_file", os.path.join(input_dir, target_file),
            "--condition_file", os.path.join(input_dir, jobInstance.conditionsFile),
            "--omic_names", ",".join([o['name'] for o in jobInstance.regulatoryOmics]),
            "--data_files", ",".join([os.path.join(input_dir, o['file']) for o in jobInstance.regulatoryOmics]),
            "--assoc_files", ",".join([os.path.join(input_dir, o['associations']) if o['associations'] else "NULL" for o in jobInstance.regulatoryOmics]),
            # Per-omic minVariation, comma-separated in the SAME order as --omic_names.
            # "NA" tokens are honoured by runMORE.R (auto threshold); missing values
            # default to MORE's 0.0. Backward-compatible with older jobs lacking the key.
            "--min_variation", ",".join([str(o.get('minVariation', 0.0)) for o in jobInstance.regulatoryOmics]),
            "--method", jobInstance.method,
            "--alpha", str(jobInstance.alpha),
            "--vip", str(jobInstance.vip),
            "--filter_r2", str(jobInstance.filter_r2),
            "--output_dir", output_dir,
            "--date_seed", jobInstance.date
        ]

        logging.info(f"MORE_STEP2 - Executing command: {' '.join(cmd)}")

        # 3. Execute R — stream output line-by-line so the operator can see exactly
        # where MORE is in the pipeline (data load, sample alignment, model fitting,
        # output writing). subprocess.check_output buffers everything until exit,
        # which makes a long PLS1+Jackknife fit on real data look like a hang. Each
        # R line is mirrored to the Flask log AND captured for the error response.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )
        captured = []
        # bufsize=1 + iter() on the line-buffered stream gives us live output.
        # MORE's progress bar uses \r within one line, so it won't appear until
        # the line ends — that's acceptable: every cat() message still streams.
        for line in iter(proc.stdout.readline, ''):
            line = line.rstrip()
            if line:
                logging.info(f"MORE-R | {line}")
                captured.append(line)
        proc.stdout.close()
        return_code = proc.wait()
        if return_code != 0:
            error_text = "\n".join(captured) if captured else f"(no output captured, exit {return_code})"
            logging.error(f"MORE_STEP2 - R Script failed with exit code {return_code}. Output:\n{error_text}")
            raise RuntimeError(f"The MORE R analysis failed. Details:\n{error_text}")

        
        # 3. Process Outputs and Prepare Summary
        # Copy each omic's result files from the R output dir into inputData/ so that
        # JobInformationManager.saveFiles (which prepends inputDir/ to filenames) can
        # find them when the user proceeds to PA Step 1. Return only the basename.
        results_summary = {}
        for omic in jobInstance.regulatoryOmics:
            name = omic["name"].strip()
            safe_name = name.replace(" ", "_")
            rel_assoc_name  = f"MORE_relevant_assoc_{safe_name}_{jobInstance.date}.tab"
            rel_pairs_name  = f"MORE_relevant_pairs_{safe_name}_{jobInstance.date}.tab"
            out_file_name   = f"MORE_output_{safe_name}_{jobInstance.date}.tab"

            # Build the relevant features file (red-star source) in GENE:::REGULATOR format.
            # Contract mirrors miRNA2Genes (MiRNA2GeneJob.fromMiRNA2Genes lines 277/321/432-435):
            # red stars are USER-driven, not algorithm-driven. If the user does NOT supply a
            # "Significant regulators" file, this file MUST be empty so that no red stars are
            # painted and pathway enrichment for this omic correctly produces p-value = 1.
            # parseGeneBasedFiles looks up relevance with the full GENE:::REGULATOR key from
            # the values file, so the file must contain those pairs (not bare regulator IDs).
            rel_reg_name = f"MORE_relevant_reg_{safe_name}_{jobInstance.date}.tab"
            rel_reg_path = os.path.join(output_dir, rel_reg_name)

            user_rel_file = os.path.join(input_dir, omic["relevant"]) if omic.get("relevant") else None
            if user_rel_file and os.path.exists(user_rel_file):
                # User supplied a list of relevant regulator IDs (e.g. TFs with FDR < 0.05).
                # Expand those IDs to all GENE:::REGULATOR pairs present in the values file
                # (regardless of MORE significance) so that any gene regulated by a
                # user-flagged TF gets a red star.
                relevant_tfs = set()
                with open(user_rel_file) as f:
                    for line in f:
                        v = line.strip()
                        if v:
                            relevant_tfs.add(v.lower())

                values_src = os.path.join(output_dir, out_file_name)
                pairs = set()
                if os.path.exists(values_src) and relevant_tfs:
                    with open(values_src) as f:
                        for line in f:
                            if line.startswith('#') or not line.strip():
                                continue
                            first_col = line.split('\t')[0]
                            if ':::' in first_col:
                                tf = first_col.split(':::', 1)[1].lower()
                                if tf in relevant_tfs:
                                    pairs.add(first_col)

                with open(rel_reg_path, 'w') as f:
                    for pair in pairs:
                        f.write(pair + '\n')
                logging.info(f"MORE_STEP2 - Built {len(pairs)} GENE:::REGULATOR relevant pairs from user file for omic '{name}'")
            else:
                # No user file → no red stars for this omic (matches miRNA2Genes behavior).
                open(rel_reg_path, 'w').close()
                logging.info(f"MORE_STEP2 - No user relevant-regulator file for omic '{name}' → empty {rel_reg_name} (no red stars)")

            # Copy R outputs into inputData/ so PA Step 1 can reference them by basename
            for fname in [out_file_name, rel_reg_name, rel_assoc_name, rel_pairs_name]:
                src_path = os.path.join(output_dir, fname)
                if os.path.exists(src_path):
                    shutil.copy2(src_path, os.path.join(input_dir, fname))

            results_summary[name] = {
                "outputFile": out_file_name,
                "associationsFile": rel_assoc_name,
                "relevantFeaturesFile": rel_reg_name,
                "relevantAssociationsFile": rel_pairs_name
            }

        # Combined RegulationPerCondition table (single file, all omics). The R
        # script wrote it to output_dir; copy into inputData/ so the
        # PathwayAcquisitionJob can read it by basename in Step 4 (parse step).
        # If the R script didn't produce it (e.g. zero relevant regulations),
        # rpc_file_name is set to None and the response omits the field — the
        # Step 3 panel then stays hidden, matching the contract for absent data.
        rpc_file_name = f"MORE_rpc_{jobInstance.date}.tab"
        rpc_src = os.path.join(output_dir, rpc_file_name)
        if os.path.exists(rpc_src):
            shutil.copy2(rpc_src, os.path.join(input_dir, rpc_file_name))

            # Sidecar metadata: the MORE filter settings the user picked at
            # configuration time. PathwayAcquisitionJob.parseRegulationPerCondition
            # picks this up and embeds it inside regulationPerConditionData so the
            # Step-3 Regulator-Target Network view can lock its R2 slider to the
            # floor the user originally chose. MOREJob is a separate Job class —
            # this file is the only channel by which its settings reach the PA job.
            filters_meta = {
                "filter_r2": jobInstance.filter_r2,
                "alpha":     jobInstance.alpha,
                "vip":       jobInstance.vip,
                "method":    jobInstance.method,
            }
            filters_name = f"MORE_filters_{jobInstance.date}.json"
            try:
                with open(os.path.join(input_dir, filters_name), "w") as fh:
                    json.dump(filters_meta, fh)
            except OSError as ex:
                # Non-fatal: client view falls back to defaults if sidecar missing.
                logging.warning(
                    f"MORE_STEP2 - could not write {filters_name}: {ex}"
                )
        else:
            logging.warning(
                f"MORE_STEP2 - {rpc_file_name} not produced by R; "
                "Step 3 regulation panel will be hidden."
            )
            rpc_file_name = None

        # 4. Bundle outputs for the "Download files" link (matches miRNA2Genes contract).
        # Fix recursion bug: create the archive in the temporal directory, then move it to output_dir.
        compressed_basename = f"more_results_{jobInstance.date}"
        archive_temp_path = os.path.join(temporal_dir, compressed_basename)
        
        logging.info(f"MORE_STEP2 - Creating results archive at {archive_temp_path}.zip")
        shutil.make_archive(archive_temp_path, "zip", output_dir)
        
        compressed_filename = compressed_basename + ".zip"
        shutil.move(archive_temp_path + ".zip", os.path.join(output_dir, compressed_filename))


        # 5. Finalize Response for UI — return basenames so saveFiles/parseGeneBasedFiles
        # can prepend inputDir/ to get the full path.
        response_data = {
            "success": True,
            "jobID": jobInstance.getJobID(),
            "description": f"MORE Analysis ({jobInstance.method})",
            "featureEnrichment": jobInstance.enrichment,
            "omicsCount": len(results_summary),
            "compressedFileName": compressed_filename
        }

        # Single combined RegulationPerCondition table (all omics) for the Step 3 panel.
        # Optional — present only when MORE produced relevant regulations.
        if rpc_file_name:
            response_data["regulationPerConditionFile"] = rpc_file_name

        for index, name in enumerate(results_summary.keys()):
            response_data[f"mainOutputFileName_{index}"]   = results_summary[name]["outputFile"]
            response_data[f"secondOutputFileName_{index}"] = results_summary[name]["relevantFeaturesFile"]
            response_data[f"thirdOutputFileName_{index}"]  = results_summary[name]["associationsFile"]
            response_data[f"fourthOutputFileName_{index}"] = results_summary[name]["relevantAssociationsFile"]
            response_data[f"omicName_{index}"] = name

        RESPONSE.setContent(response_data)

        # 5. Save MORE Job via the shared manager (makes it listable and removable)
        JobInformationManager().storeJobInstance(jobInstance, 1)

    except Exception as ex:
        jobInstance.cleanDirectories(remove_output=True)
        # Ensure we capture as much detail as possible in the response.
        handleException(RESPONSE, ex, __file__, "fromMOREtoGenes_STEP2")

    finally:
        return RESPONSE
