import logging

from src.common.ServerErrorManager import handleException
from src.common.UserSessionManager import UserSessionManager
from src.common.DAO.AIInterpretDAO import AIInterpretDAO
from src.common.JobInformationManager import JobInformationManager
from src.classes.AIInterpret.pipeline import run_ai_pipeline, _cancel_flags
from src.common.PySiQ import JobStatus
from src.classes.AIInterpret.llm_client import LLMClient
from src.classes.AIInterpret.prompts import SYSTEM_PROMPT_CHAT
from src.classes.AIInterpret.tools import CHAT_TOOLS, execute_tool
from src.conf.serverconf import (AI_INTERPRETATION_ENABLED, AI_PROVIDERS,
    AI_LLM_PROVIDER, AI_TEMPERATURE)

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
        if existingJob is not None:
            if existingJob.status == JobStatus.FINISHED:
                RESPONSE.setContent({"success": True, "jobID": jobID, "status": "already_finished"})
                return RESPONSE
            elif existingJob.status == JobStatus.FAILED:
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
            RESPONSE.setContent({
                "success": True,
                "jobID": jobID,
                "status": record.get("status", "unknown"),
                "percent": record.get("percent", 0),
                "detail": record.get("detail", ""),
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

        # Build conversation context
        report = record.get("report", "")
        conversation = record.get("conversation", [])

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_CHAT},
            {"role": "user", "content": f"Here is the analysis report for context:\n\n{report}"},
            {"role": "assistant", "content": "I've reviewed the analysis report. What questions do you have?"},
        ]
        for msg in conversation:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": userMessage})

        # Save user message
        dao.append_chat(jobID, "user", userMessage)

        # Get LLM response (with tool access when job data is available)
        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
        job_instance = JobInformationManager().loadJobInstance(jobID)

        if job_instance is not None:
            tool_executor = lambda name, args: execute_tool(name, job_instance, args)
            reply = llm.complete_with_tools(
                messages, CHAT_TOOLS, tool_executor,
                max_tokens=2048, temperature=AI_TEMPERATURE,
            )
        else:
            reply = llm.complete(messages, max_tokens=2048, temperature=AI_TEMPERATURE)

        # Save assistant reply (only the final text, not intermediate tool messages)
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

        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
        suggestion = llm.complete([
            {"role": "system", "content": "You help researchers describe their experiment design concisely."},
            {"role": "user", "content": prompt}
        ], max_tokens=300, temperature=0.5)

        RESPONSE.setContent({"success": True, "jobID": jobID, "suggestion": suggestion})

    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiGenerateExpDesign", userID=userID)
    finally:
        return RESPONSE
