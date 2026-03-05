import logging
from datetime import datetime, timedelta

from src.common.ServerErrorManager import handleException
from src.common.UserSessionManager import UserSessionManager
from src.common.DAO.AIInterpretDAO import AIInterpretDAO
from src.common.JobInformationManager import JobInformationManager
from src.classes.AIInterpret.pipeline import run_ai_pipeline, _cancel_flags
from src.common.PySiQ import JobStatus
from src.conf.serverconf import AI_INTERPRETATION_ENABLED

# Jobs stuck longer than this are considered dead (e.g. killed by server reload)
AI_STALE_JOB_TIMEOUT = timedelta(minutes=10)

def aiInterpretInitiate(REQUEST, RESPONSE, QUEUE_INSTANCE):
    """Start or re-check the AI interpretation pipeline for a job."""
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        if not AI_INTERPRETATION_ENABLED:
            raise UserWarning("AI interpretation is not enabled on this server.")

        formFields = REQUEST.form
        jobID = formFields.get("jobID")
        experimentDesign = formFields.get("experimentDesign", "")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")

        # Verify the job exists
        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            raise UserWarning("Job " + jobID + " was not found.")

        # Check idempotency: is the AI pipeline already queued/running?
        ai_job_id = "ai_" + jobID
        existingJob = QUEUE_INSTANCE.fetch_job(ai_job_id)

        # Also check if the DB record shows an error (stale job detected by status endpoint)
        dao_check = AIInterpretDAO()
        try:
            db_record = dao_check.find_by_job_id(jobID)
            db_status = db_record.get("status") if db_record else None
        finally:
            dao_check.closeConnection()

        if existingJob is not None:
            if existingJob.status == JobStatus.FINISHED and db_status != "error":
                RESPONSE.setContent({"success": True, "jobID": jobID, "status": "already_finished"})
                return RESPONSE
            elif existingJob.status == JobStatus.FAILED or db_status == "error":
                # Allow retry: clear old state and re-queue below
                dao = AIInterpretDAO()
                try:
                    dao.save_progress(jobID, {"status": "queued", "percent": 0,
                        "detail": "Retrying...", "report": None, "verification": None})
                finally:
                    dao.closeConnection()
                QUEUE_INSTANCE.get_result(ai_job_id, remove=True)
            else:
                RESPONSE.setContent({"success": True, "jobID": jobID, "status": "already_running"})
                return RESPONSE

        # Enqueue the AI pipeline
        QUEUE_INSTANCE.enqueue(
            fn=run_ai_pipeline,
            args=(jobID, experimentDesign, RESPONSE),
            timeout=900,
            job_id=ai_job_id
        )

        RESPONSE.setContent({"success": True, "jobID": jobID, "status": "queued"})

    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiInterpretInitiate", userID=userID)
    finally:
        return RESPONSE


def aiInterpretStatus(REQUEST, RESPONSE):
    """Return current progress of the AI interpretation pipeline."""
    dao = None
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        formFields = REQUEST.form
        jobID = formFields.get("jobID")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")

        dao = AIInterpretDAO()
        record = dao.find_by_job_id(jobID)

        if record is None:
            RESPONSE.setContent({"success": True, "jobID": jobID,
                "status": "not_started", "percent": 0, "detail": "Not started"})
        else:
            status = record.get("status", "unknown")

            # Detect stale/dead jobs: if a non-terminal status hasn't been
            # updated in AI_STALE_JOB_TIMEOUT, the worker thread is dead
            # (e.g. killed by Flask debug reloader or crash without cleanup).
            if status not in ("done", "error", "cancelled", "not_started"):
                updated_at = record.get("updatedAt")
                if updated_at and (datetime.utcnow() - updated_at) > AI_STALE_JOB_TIMEOUT:
                    logging.warning(
                        f"AI job {jobID} stale (status={status}, "
                        f"updatedAt={updated_at}). Marking as error."
                    )
                    dao.save_progress(jobID, {
                        "status": "error", "percent": 0,
                        "detail": "Pipeline interrupted (no progress for 10 min). Click Retry.",
                    })
                    status = "error"

            RESPONSE.setContent({
                "success": True,
                "jobID": jobID,
                "status": status,
                "percent": record.get("percent", 0) if status != "error" else 0,
                "detail": record.get("detail", "") if status != "error"
                    else "Pipeline interrupted (no progress for 10 min). Click Retry.",
            })
    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiInterpretStatus", userID=userID)
    finally:
        if dao is not None:
            dao.closeConnection()
        return RESPONSE


def aiInterpretReport(REQUEST, RESPONSE):
    """Return the completed AI interpretation report."""
    dao = None
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        formFields = REQUEST.form
        jobID = formFields.get("jobID")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")

        dao = AIInterpretDAO()
        record = dao.find_by_job_id(jobID)

        if record is None:
            RESPONSE.setContent({"success": False, "jobID": jobID,
                "message": "Report not ready yet."})
        elif record.get("status") == "error":
            RESPONSE.setContent({"success": False, "jobID": jobID,
                "message": "AI interpretation failed: " + record.get("detail", "Unknown error"),
                "status": "error"})
        elif record.get("status") != "done":
            RESPONSE.setContent({"success": False, "jobID": jobID,
                "message": "AI interpretation is still in progress (" + str(record.get("percent", 0)) + "%).",
                "status": record.get("status", "unknown")})
        else:
            RESPONSE.setContent({
                "success": True,
                "jobID": jobID,
                "report": record.get("report", ""),
                "verification": record.get("verification", {}),
                "papers": record.get("papers", []),
            })
    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiInterpretReport", userID=userID)
    finally:
        if dao is not None:
            dao.closeConnection()
        return RESPONSE


def aiInterpretChat(REQUEST, RESPONSE):
    """Handle follow-up chat with the AI about interpretation results."""
    dao = None
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        if not AI_INTERPRETATION_ENABLED:
            raise UserWarning("AI interpretation is not enabled on this server.")

        formFields = REQUEST.form
        jobID = formFields.get("jobID")
        userMessage = formFields.get("message", "")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")
        if not userMessage.strip():
            raise UserWarning("Empty message.")

        dao = AIInterpretDAO()
        record = dao.find_by_job_id(jobID)

        if record is None or record.get("status") != "done":
            raise UserWarning("Report must be completed before chatting.")

        # Save user message
        dao.append_chat(jobID, "user", userMessage)

        report = record.get("report", "")
        conversation = record.get("conversation", [])
        job_instance = JobInformationManager().loadJobInstance(jobID)

        # Use Agents SDK for chat
        from agents import Runner
        from src.classes.AIInterpret.agents import configure_sdk, build_chat_agent
        from src.classes.AIInterpret.models import PipelineContext
        from src.classes.AIInterpret.context_builder import get_organism_name, detect_design_type
        from src.classes.AIInterpret.pubmed_client import PubMedClient

        configure_sdk()
        chat_agent = build_chat_agent(report)

        # Build context
        ctx = PipelineContext(
            job_instance=job_instance,
            job_id=jobID,
            organism_name=get_organism_name(job_instance.getOrganism()) if job_instance else "",
            design_type=detect_design_type(job_instance) if job_instance else "multi_group",
            experiment_design="",
            pubmed_client=PubMedClient(),
        )

        # Build input from conversation history
        input_parts = []
        for msg in conversation:
            role = "User" if msg["role"] == "user" else "Assistant"
            input_parts.append(f"{role}: {msg['content']}")
        input_parts.append(f"User: {userMessage}")
        full_input = "\n\n".join(input_parts)

        result = Runner.run_sync(chat_agent, full_input, context=ctx, max_turns=10)
        reply = str(result.final_output)

        # Save assistant reply
        dao.append_chat(jobID, "assistant", reply)

        RESPONSE.setContent({"success": True, "jobID": jobID, "response": reply})

    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiInterpretChat", userID=userID)
    finally:
        if dao is not None:
            dao.closeConnection()
        return RESPONSE


def aiGenerateExpDesign(REQUEST, RESPONSE):
    """Use LLM to help user draft an experiment design description from their omics data."""
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        if not AI_INTERPRETATION_ENABLED:
            raise UserWarning("AI interpretation is not enabled on this server.")

        formFields = REQUEST.form
        jobID = formFields.get("jobID")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")

        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            raise UserWarning("Job " + jobID + " was not found.")

        # Build a summary of uploaded omics
        omics_summary = []
        for omic in jobInstance.getGeneBasedInputOmics():
            omics_summary.append(omic.get("omicName", "Unknown omic"))
        for omic in jobInstance.getCompoundBasedInputOmics():
            omics_summary.append(omic.get("omicName", "Unknown omic"))

        organism = jobInstance.getOrganism()

        prompt = (
            f"The user uploaded these omics data types: {', '.join(omics_summary)}.\n"
            f"Organism: {organism}.\n\n"
            "Based on these data types, draft a brief experiment design description (2-3 sentences) "
            "that the user can edit. Focus on what biological question these data types typically address together."
        )

        from agents import Agent, Runner, ModelSettings
        from src.classes.AIInterpret.agents import configure_sdk, _get_model
        configure_sdk()

        design_agent = Agent(
            name="Design Helper",
            model=_get_model(),
            instructions="You help researchers describe their experiment design concisely.",
            model_settings=ModelSettings(temperature=0.5),
        )
        result = Runner.run_sync(design_agent, prompt, max_turns=1)
        suggestion = str(result.final_output)

        RESPONSE.setContent({"success": True, "jobID": jobID, "suggestion": suggestion})

    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiGenerateExpDesign", userID=userID)
    finally:
        return RESPONSE
