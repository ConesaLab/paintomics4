import logging
from datetime import datetime, timedelta

from src.common.ServerErrorManager import handleException
from src.common.UserSessionManager import UserSessionManager
from src.common.DAO.AIInterpretDAO import AIInterpretDAO
from src.common.JobInformationManager import JobInformationManager
from src.classes.AIInterpret.pipeline import run_ai_pipeline, _cancel_flags
from src.common.PySiQ import JobStatus
from src.classes.AIInterpret.llm_client import LLMClient, MissingAPIKeyError
from src.classes.AIInterpret.prompts import (SYSTEM_PROMPT_CHAT,
    SYSTEM_PROMPT_PATHWAY_FOCUS, build_pathway_focus_prompt)
from src.classes.AIInterpret.context_builder import (build_pathway_context,
    get_organism_name)
from src.classes.AIInterpret.tools import CHAT_TOOLS, execute_tool
from src.conf.serverconf import (AI_INTERPRETATION_ENABLED, AI_PROVIDERS,
    AI_LLM_PROVIDER, AI_TEMPERATURE, AI_MAX_PATHWAYS)

# Jobs stuck longer than this are considered dead (e.g. killed by server reload)
AI_STALE_JOB_TIMEOUT = timedelta(minutes=10)

def _requireLLMCredentials():
    """Refuse before spending anything if this server has no LLM token.

    `AI_INTERPRETATION_ENABLED` defaults to true, so a checkout that was never
    handed `AI_CSIC_API_KEY` advertises the feature and then fails at the
    gateway. Measured locally: the request was accepted, the pipeline queued,
    and 13.2s of PubMed and Europe PMC traffic went out against shared rate
    limits before the first LLM call returned 401. The key cannot appear
    mid-run, so the check belongs at the door -- and as a UserWarning, which is
    what this servlet renders as a readable message rather than a stack trace.

    Constructing the client is the check: it is where the validation lives, so
    the two cannot drift apart.
    """
    try:
        LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER], AI_LLM_PROVIDER)
    except MissingAPIKeyError as ex:
        raise UserWarning(str(ex))
    except KeyError:
        raise UserWarning(
            "AI provider '%s' is not defined in AI_PROVIDERS. Check "
            "AI_LLM_PROVIDER in the server configuration." % AI_LLM_PROVIDER)


# Hosts whose operator the interface can name. The consent notice has to say
# who receives the data, and "an external AI service" does not answer that --
# but the client cannot answer it either, because the provider is chosen by
# AI_LLM_PROVIDER on the server and three are shipped. So the server says.
#
# Anything not listed falls back to the bare hostname, which is still a true
# and useful statement ("sent to <host>") and degrades safely for a site that
# repoints AI_CSIC_API_BASE at its own gateway.
_PROVIDER_OPERATORS = {
    "llm.iiia.es": {
        "operator": "IIIA-CSIC",
        # Deliberately not "internal". The gateway resolves in public DNS and
        # answers requests from outside CSIC; it is guarded by a token, not by
        # a network boundary. Calling it internal would tell users their data
        # stays inside a perimeter that does not exist.
        "summary": "a gateway operated by IIIA-CSIC (the Artificial "
                   "Intelligence Research Institute of the Spanish National "
                   "Research Council), on hardware in Spain",
        "inEU": True,
    },
    "openrouter.ai": {
        "operator": "OpenRouter",
        "summary": "OpenRouter, a commercial LLM broker that forwards the "
                   "request to the model vendor",
        "inEU": False,
    },
    "coding-intl.dashscope.aliyuncs.com": {
        "operator": "Alibaba Cloud",
        "summary": "Alibaba Cloud's DashScope service",
        "inEU": False,
    },
}


def getAIProviderInfo():
    """Describe the LLM endpoint this server is configured to call.

    Returned to the browser so the consent notice can name the recipient
    instead of saying "an external AI service". Every field is derived from
    the live configuration rather than hardcoded in the client, because
    AI_LLM_PROVIDER, AI_CSIC_API_BASE and AI_CSIC_MODEL are all env-overridable
    -- a client that hardcoded "CSIC" would be lying on any site that changed
    them.

    Carries no secret: the API key is never read here, and `configured` reports
    only whether one is non-empty, which the browser can already infer from the
    feature failing.
    """
    provider = AI_PROVIDERS.get(AI_LLM_PROVIDER, {})
    apiBase = provider.get("api_base", "")

    # urlparse rather than a split: an api_base carrying a port or a path
    # ("https://host:8000/v1") must still yield the bare host.
    try:
        from urllib.parse import urlparse
        host = urlparse(apiBase).hostname or ""
    except Exception:
        host = ""

    known = _PROVIDER_OPERATORS.get(host, {})
    return {
        "enabled": bool(AI_INTERPRETATION_ENABLED),
        "configured": bool(provider.get("api_key")),
        "provider": AI_LLM_PROVIDER,
        "host": host,
        "model": provider.get("model", ""),
        "operator": known.get("operator", host),
        "summary": known.get("summary", host),
        # Whether Chapter V of the GDPR (Arts. 44-49, transfers outside the
        # EU) applies to this deployment. None where it cannot be determined,
        # so the client can stay silent rather than guess.
        "inEU": known.get("inEU", None),
    }


def _consented(jobID):
    """Whether this job's owner ticked "Enable AI pathway interpretation".

    Every route that sends anything outward asks this. A job that cannot be
    loaded counts as not consenting: the alternative is treating an unknown
    job as permission, which is the wrong way round for a question about
    someone else's data.
    """
    jobInstance = JobInformationManager().loadJobInstance(jobID)
    return bool(jobInstance is not None and jobInstance.getAIConsent())


def aiInterpretInitiate(REQUEST, RESPONSE, QUEUE_INSTANCE):
    """Start or re-check the AI interpretation pipeline for a job."""
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        if not AI_INTERPRETATION_ENABLED:
            raise UserWarning("AI interpretation is not enabled on this server.")
        _requireLLMCredentials()

        formFields = REQUEST.form
        jobID = formFields.get("jobID")
        experimentDesign = formFields.get("experimentDesign", "")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")

        # Verify the job exists
        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            raise UserWarning("Job " + jobID + " was not found.")

        # The consent the upload page asks for was collected, stored and echoed
        # back in four responses, and never checked before the pipeline ran.
        # Posting this endpoint a jobID was enough: measured against a job whose
        # record says aiConsent False, the request returned success and the
        # pipeline went through triage, search planning, 8.1s of literature
        # retrieval and synthesis, reaching out to
        # https://llm.iiia.es/v1/chat/completions. It stopped there only because
        # this machine has no API key; a deployment that has one would have sent
        # the job's analysis summary. The PubMed queries need no key and had
        # already gone out.
        #
        # The checkbox says "sends analysis summaries to external AI service",
        # so someone clearing it is declining exactly that. Job ids travel --
        # the results page prints a shareable URL -- so the decision has to be
        # enforced here rather than by the client choosing not to ask.
        if not jobInstance.getAIConsent():
            raise UserWarning(
                "AI interpretation was not enabled for this job. Re-run the "
                "analysis with 'Enable AI pathway interpretation' ticked if you "
                "want its summaries sent to the external AI service.")

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
                # Lets the client turn pathway names in the report prose into
                # links that open the pathway. Sent as id/name/source only.
                "pathways": record.get("pathwayIndex", []),
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
        _requireLLMCredentials()

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

        # Same consent the initiate endpoint checks. This one sends the
        # user's question and the job's context to the same external service,
        # so declining has to stop it here too -- gating only the pipeline
        # would leave three other ways out.
        if not _consented(jobID):
            raise UserWarning(
                "AI interpretation was not enabled for this job, so nothing "
                "about it can be sent to the external AI service.")

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
        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER], AI_LLM_PROVIDER)
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
        _requireLLMCredentials()

        formFields = REQUEST.form
        jobID = formFields.get("jobID")

        if not jobID:
            raise UserWarning("Missing jobID parameter.")

        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            raise UserWarning("Job " + jobID + " was not found.")

        # See _consented: this route sends job context outward as well.
        if not jobInstance.getAIConsent():
            raise UserWarning(
                "AI interpretation was not enabled for this job, so nothing "
                "about it can be sent to the external AI service.")

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

        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER], AI_LLM_PROVIDER)
        suggestion = llm.complete([
            {"role": "system", "content": "You help researchers describe their experiment design concisely."},
            {"role": "user", "content": prompt}
        ], max_tokens=300, temperature=0.5)

        RESPONSE.setContent({"success": True, "jobID": jobID, "suggestion": suggestion})

    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiGenerateExpDesign", userID=userID)
    finally:
        return RESPONSE


def aiInterpretPathway(REQUEST, RESPONSE):
    """Return a focused AI interpretation of one pathway.

    Backs the pathway citations in the main report: clicking one opens the
    pathway and asks for this. Generated lazily and cached, so only pathways a
    user actually opens cost an LLM call, and opening the same one twice is
    free.
    """
    dao = None
    userID = None
    try:
        userID = REQUEST.cookies.get('userID')
        sessionToken = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        if not AI_INTERPRETATION_ENABLED:
            raise UserWarning("AI interpretation is not enabled on this server.")
        _requireLLMCredentials()

        formFields = REQUEST.form
        jobID = formFields.get("jobID")
        pathwayID = formFields.get("pathwayID")
        regenerate = formFields.get("regenerate", "") == "true"

        if not jobID or not pathwayID:
            raise UserWarning("Missing jobID or pathwayID parameter.")

        dao = AIInterpretDAO()

        if not regenerate:
            cached = dao.get_pathway_report(jobID, pathwayID)
            if cached:
                RESPONSE.setContent({
                    "success": True, "jobID": jobID, "pathwayID": pathwayID,
                    "report": cached.get("report", ""),
                    "papers": cached.get("papers", []),
                    "cached": True,
                })
                return RESPONSE

        # The main pipeline must have run: its pathway index is what tells us
        # which pathways were analysed, and its papers are the only literature
        # we are allowed to cite.
        pathwayIndex = dao.get_pathway_index(jobID)
        if not pathwayIndex:
            raise UserWarning("Run the AI interpretation for this job first.")

        entry = next((p for p in pathwayIndex if p.get("id") == pathwayID), None)
        if entry is None:
            raise UserWarning("Pathway " + pathwayID + " was not part of the AI analysis. "
                              "Only the pathways the report covers can be interpreted.")

        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            raise UserWarning("Job " + jobID + " was not found.")

        # See _consented: this route sends job context outward as well.
        if not jobInstance.getAIConsent():
            raise UserWarning(
                "AI interpretation was not enabled for this job, so nothing "
                "about it can be sent to the external AI service.")

        record = dao.find_by_job_id(jobID) or {}
        experimentDesign = record.get("experimentDesign", "")

        # Rebuild the full context and pick this pathway out of it. The stored
        # index deliberately holds only display fields; the gene-level detail
        # the prompt needs has to be recomputed.
        allPathways = build_pathway_context(jobInstance, max_pathways=AI_MAX_PATHWAYS)
        pathway = next((p for p in allPathways if p.get("id") == pathwayID), None)
        if pathway is None:
            raise UserWarning("Pathway " + pathwayID + " is no longer present in this job's results.")

        # Papers are attributed to pathways by name (pipeline.py), so match on
        # the name rather than the ID.
        pathwayName = pathway.get("name")
        papers = [
            p for p in dao.get_papers_metadata(jobID)
            if pathwayName in (p.get("pathways") or [])
        ]

        organismName = get_organism_name(jobInstance.getOrganism())
        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER], AI_LLM_PROVIDER)
        prompt = build_pathway_focus_prompt(pathway, papers, experimentDesign, organismName)

        report = llm.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_PATHWAY_FOCUS},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=AI_TEMPERATURE,
        )

        citedPapers = [
            {k: v for k, v in p.items() if k != "sections"} for p in papers
        ]
        dao.save_pathway_report(jobID, pathwayID, report, citedPapers)

        RESPONSE.setContent({
            "success": True, "jobID": jobID, "pathwayID": pathwayID,
            "report": report, "papers": citedPapers, "cached": False,
        })
    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "aiInterpretPathway", userID=userID)
    finally:
        if dao is not None:
            dao.closeConnection()
        return RESPONSE
