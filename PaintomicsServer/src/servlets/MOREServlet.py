#***************************************************************
#  This file is part of Paintomics v4
#**************************************************************

import logging
import os
import subprocess
import shutil
from src.classes.JobInstances.MOREJob import MOREJob
from src.common.UserSessionManager import UserSessionManager
from src.common.JobInformationManager import JobInformationManager
from src.servlets.DataManagementServlet import saveFile
from src.conf.serverconf import CLIENT_TMP_DIR, ROOT_DIRECTORY

def fromMOREtoGenes_STEP1(REQUEST, RESPONSE, QUEUE_INSTANCE, JOB_ID, EXAMPLE_FILES_DIR, exampleMode=False):
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
            
            jobInstance.addRegulatoryOmic(name, data_path, formFields.get(f"omic_type_{i}"), assoc_path, rel_path)
            i += 1

        # 6. Model Parameters
        jobInstance.method = formFields.get("more_method", "PLS1")
        jobInstance.alpha = float(formFields.get("more_alpha", 0.05))
        jobInstance.vip = float(formFields.get("more_vip", 0.8))
        jobInstance.filter_r2 = float(formFields.get("more_filter_r2", 0.0))

        # 7. Queue job
        QUEUE_INSTANCE.enqueue(
            fn=fromMOREtoGenes_STEP2,
            args=(jobInstance, userID, exampleMode, RESPONSE, formFields),
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

def fromMOREtoGenes_STEP2(jobInstance, userID, exampleMode, RESPONSE, formFields):
    """
    Step 2: Run the R backend and return results.
    """
    try:
        logging.info(f"MORE_STEP2 - RUNNING R SCRIPT for {jobInstance.getJobID()}")
        
        # 1. Prepare Command
        target_file = jobInstance.targetExpressionFile
        input_dir = jobInstance.getInputDir()
        output_dir = jobInstance.getOutputDir()

        # Derive server root from CLIENT_TMP_DIR, which is always an absolute path in serverconf.
        # os.path.abspath(__file__) is unreliable when the server is started from inside src/,
        # causing __file__ to resolve as a relative path and producing a spurious src/src/ prefix.
        server_root = os.path.dirname(CLIENT_TMP_DIR.rstrip('/'))
        r_script = os.path.join(server_root, "src", "common", "bioscripts", "runMORE.R")
        
        cmd = [
            "Rscript", r_script,
            "--target_file", os.path.join(input_dir, target_file) if target_file else "NULL",
            "--condition_file", os.path.join(input_dir, jobInstance.conditionsFile),
            "--omic_names", ",".join([o['name'] for o in jobInstance.regulatoryOmics]),
            "--data_files", ",".join([os.path.join(input_dir, o['file']) for o in jobInstance.regulatoryOmics]),
            "--assoc_files", ",".join([os.path.join(input_dir, o['associations']) if o['associations'] else "NULL" for o in jobInstance.regulatoryOmics]),
            "--method", jobInstance.method,
            "--alpha", str(jobInstance.alpha),
            "--vip", str(jobInstance.vip),
            "--filter_r2", str(jobInstance.filter_r2),
            "--output_dir", output_dir,
            "--date_seed", jobInstance.date
        ]

        logging.info(f"MORE_STEP2 - Executing command: {' '.join(cmd)}")

        # 2. Execute R — check_output captures stdout+stderr so CalledProcessError.output is non-None
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        
        # 3. Process Outputs and Prepare Summary
        # Copy each omic's result files from the R output dir into inputData/ so that
        # JobInformationManager.saveFiles (which prepends inputDir/ to filenames) can
        # find them when the user proceeds to PA Step 1. Return only the basename.
        results_summary = {}
        for omic in jobInstance.regulatoryOmics:
            name = omic["name"].strip()
            safe_name = name.replace(" ", "_")
            rel_assoc_name = f"MORE_relevant_assoc_{safe_name}_{jobInstance.date}.tab"
            out_file_name   = f"MORE_output_{safe_name}_{jobInstance.date}.tab"

            if omic.get("relevant"):
                user_rel_file = os.path.join(input_dir, omic["relevant"])
                rel_reg_name = os.path.basename(user_rel_file)
                if not os.path.exists(user_rel_file):
                    logging.warning(f"MORE_STEP2 - User relevant file not found: {user_rel_file}. Using R output.")
                    rel_reg_name = f"MORE_relevant_reg_{safe_name}_{jobInstance.date}.tab"
            else:
                rel_reg_name = f"MORE_relevant_reg_{safe_name}_{jobInstance.date}.tab"

            # Copy R outputs into inputData/ so PA Step 1 can reference them by basename
            for fname in [out_file_name, rel_reg_name, rel_assoc_name]:
                src_path = os.path.join(output_dir, fname)
                if os.path.exists(src_path):
                    shutil.copy2(src_path, os.path.join(input_dir, fname))

            results_summary[name] = {
                "outputFile": out_file_name,
                "relevantAssociationsFile": rel_assoc_name,
                "relevantFeaturesFile": rel_reg_name
            }

        # 4. Finalize Response for UI — return basenames so saveFiles/parseGeneBasedFiles
        # can prepend inputDir/ to get the full path.
        response_data = {
            "success": True,
            "jobID": jobInstance.getJobID(),
            "description": f"MORE Analysis ({jobInstance.method})",
            "featureEnrichment": "associations",
            "omicsCount": len(results_summary)
        }

        for index, name in enumerate(results_summary.keys()):
            response_data[f"mainOutputFileName_{index}"] = results_summary[name]["outputFile"]
            response_data[f"secondOutputFileName_{index}"] = results_summary[name]["relevantFeaturesFile"]
            response_data[f"thirdOutputFileName_{index}"] = results_summary[name]["relevantAssociationsFile"]
            response_data[f"omicName_{index}"] = name
        
        RESPONSE.setContent(response_data)

        # 5. Save MORE Job via the shared manager (makes it listable and removable)
        JobInformationManager().storeJobInstance(jobInstance, 1)

    except subprocess.CalledProcessError as e:
        logging.error(f"MORE_STEP2 - R Script failed: {e.output}")
        RESPONSE.setContent({"success": False, "message": "The MORE R analysis failed. Please check your input data formatting."})
    except Exception:
        logging.exception("MORE_STEP2 - CRITICAL ERROR")
        RESPONSE.setContent({"success": False, "message": "An internal error occurred during result processing. Please check the server logs."})
    finally:
        return RESPONSE
