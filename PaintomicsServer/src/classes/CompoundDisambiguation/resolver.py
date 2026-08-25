#***************************************************************
#  This file is part of Paintomics v4
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************
"""Tier 2: put the residual sets to a model as a closed-set choice.

The contract, and the whole reason this module is separate from the prompt that
states it:

    An answer is applied only if it names a KEGG id that was in that input
    name's own candidate list.

:func:`validateChoice` is where that is enforced. It is a pure function over
one answer and one decision, so the guarantee can be tested without a gateway,
a job or a network. Everything it turns down -- an invented id, an id borrowed
from a different input name in the same batch, a name that was never asked
about, a low-confidence guess -- becomes an abstention, and an abstention leaves
the user's existing ticks exactly as they were.

Nothing here writes to the job. The return value is advice; the user confirms
it, and ``pathwayAcquisitionStep2`` remains the only writer of a selection.
"""

import json
import logging
import re

from src.classes.CompoundDisambiguation import prompts

#: Residual sets per gateway call. Sets are independent, so this trades prompt
#: size against round trips: the STATegra example's 18 residuals are one call,
#: and a job whose residual list runs to hundreds is still a handful.
DEFAULT_BATCH_SIZE = 30

#: Wall clock for one batch, across every attempt and backoff. Someone is
#: watching a spinner; this call must give up and say so rather than hold a
#: queue slot until the gateway decides to.
DEFAULT_BATCH_BUDGET_SECONDS = 180

#: A selection that changes which pathways a user publishes should not change
#: between two runs of the same job if it can be helped.
TEMPERATURE = 0.0

#: The literal the prompt tells the model to use when it will not choose.
ABSTAIN_TOKEN = "ABSTAIN"


def parseChoices(text):
    """Pull the choices array out of a model reply.

    The gateway honours ``response_format`` when it can and falls back to free
    text when it cannot (``LLMClient.supports_schema``), so both shapes have to
    parse. Anything unparseable yields an empty list, which the caller reports
    as a batch that abstained rather than as a batch that succeeded.
    """
    body = (text or "").strip()
    if not body:
        return []

    if body.startswith("```"):
        body = "\n".join(line for line in body.split("\n")
                         if not line.strip().startswith("```")).strip()

    payload = None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        # A model that wrapped the object in prose. Take the outermost braces.
        match = re.search(r"\{.*\}", body, re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group())
            except (ValueError, TypeError):
                payload = None

    if isinstance(payload, list):
        choices = payload
    elif isinstance(payload, dict):
        choices = payload.get("choices")
    else:
        choices = None

    if not isinstance(choices, list):
        return []
    return [choice for choice in choices if isinstance(choice, dict)]


def validateChoice(choice, decision):
    """Decide whether one model answer may be applied to one compound set.

    This is the closed-set gate. It never trusts ``kegg_id`` further than
    membership of ``decision["candidates"]``.

    @param {Dict} choice, one entry of the model's ``choices`` array
    @param {Dict} decision, the residual decision the choice claims to answer
    @returns {Dict} {"outcome": "accepted"|"abstained"|"rejected",
                     "keggID", "confidence", "reason", "detail"}
    """
    candidateIDs = {candidate["keggID"] for candidate in decision.get("candidates", [])}

    keggID = str(choice.get("kegg_id") or "").strip()
    confidence = str(choice.get("confidence") or "").strip().lower()
    reason = str(choice.get("reason") or "").strip()

    if not keggID or keggID.upper() == ABSTAIN_TOKEN:
        return {"outcome": "abstained", "keggID": None, "confidence": confidence,
                "reason": reason, "detail": "the model abstained"}

    if keggID not in candidateIDs:
        # Either invented, or lifted from another input name in the same batch.
        # Both are the same failure from here: an id this name never matched.
        return {"outcome": "rejected", "keggID": None, "confidence": confidence,
                "reason": reason,
                "detail": "%s was not one of the candidates for %r"
                          % (keggID, decision.get("title", ""))}

    if confidence == "low":
        return {"outcome": "abstained", "keggID": None, "confidence": confidence,
                "reason": reason, "detail": "the model was not confident"}

    return {"outcome": "accepted", "keggID": keggID, "confidence": confidence or "medium",
            "reason": reason, "detail": ""}


def _indexByTitle(decisions):
    """Titles to decisions, so a reply can be matched by name rather than order."""
    exact, lowered = {}, {}
    for decision in decisions:
        title = decision.get("title", "")
        exact.setdefault(title, decision)
        lowered.setdefault(title.strip().lower(), decision)
    return exact, lowered


def applyChoices(decisions, choices):
    """Match a batch's answers to its questions and validate each one.

    Answers are matched on ``input_name``, never on position: a model that
    drops or reorders an entry would otherwise shift every later answer onto
    the wrong metabolite -- the one failure mode in this whole feature that
    produces confident, plausible, uniformly wrong output.

    @returns {Tuple} (accepted, abstained, rejected) lists
    """
    exact, lowered = _indexByTitle(decisions)
    answered = set()
    accepted, abstained, rejected = [], [], []

    for choice in choices:
        name = str(choice.get("input_name") or "").strip()
        decision = exact.get(name) or lowered.get(name.lower())
        if decision is None:
            rejected.append({"title": name, "detail": "no such input name in this batch"})
            continue

        title = decision["title"]
        if title in answered:
            rejected.append({"title": title, "detail": "answered twice in one batch"})
            continue
        answered.add(title)

        verdict = validateChoice(choice, decision)
        entry = {"title": title, "keggID": verdict["keggID"],
                 "confidence": verdict["confidence"], "reason": verdict["reason"],
                 "detail": verdict["detail"], "tier": "ai",
                 "candidates": decision.get("candidates", [])}

        if verdict["outcome"] == "accepted":
            accepted.append(entry)
        elif verdict["outcome"] == "rejected":
            rejected.append(entry)
        else:
            abstained.append(entry)

    # A set the model simply did not mention is an abstention, not a silent
    # drop: it still needs to appear in the count the user is shown.
    for decision in decisions:
        if decision["title"] not in answered:
            abstained.append({"title": decision["title"], "keggID": None,
                              "confidence": "", "reason": "",
                              "detail": "the model did not answer for this name",
                              "tier": "ai", "candidates": decision.get("candidates", [])})

    return accepted, abstained, rejected


def _chunk(items, size):
    for start in range(0, len(items), max(1, size)):
        yield items[start:start + size]


def buildClient():
    """An LLMClient for the configured provider.

    Raises ``MissingAPIKeyError`` when this deployment has no token, which the
    servlet turns into "the button is unavailable" rather than into a failure
    the user is asked to interpret.
    """
    from src.conf.serverconf import AI_LLM_PROVIDER, AI_PROVIDERS
    from src.classes.AIInterpret.llm_client import LLMClient
    return LLMClient(AI_PROVIDERS.get(AI_LLM_PROVIDER, {}), AI_LLM_PROVIDER)


def suggestCompounds(decisions, context, client=None, batchSize=DEFAULT_BATCH_SIZE,
                     budgetSeconds=DEFAULT_BATCH_BUDGET_SECONDS, jobID=""):
    """Ask the model to choose for every residual set, batched.

    @param {List} decisions, residual decisions from the ranker
    @param {Dict} context, as accepted by :func:`prompts.buildContextBlock`
    @param client, an LLMClient; built from configuration when omitted
    @returns {Dict} {"accepted", "abstained", "rejected", "model", "batches"}
    """
    if not decisions:
        return {"accepted": [], "abstained": [], "rejected": [], "model": "", "batches": 0}

    if client is None:
        client = buildClient()

    from src.classes.AIInterpret.llm_client import json_schema_format

    accepted, abstained, rejected = [], [], []
    batches = 0

    for batch in _chunk(decisions, batchSize):
        batches += 1
        messages = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.buildBatchPrompt(batch, context)},
        ]
        try:
            # Streamed: a non-streamed request to the CSIC gateway is given
            # about 120s before LiteLLM retries the backend itself, and a
            # 30-set batch can outrun that.
            reply = client.complete(
                messages,
                max_tokens=4096,
                temperature=TEMPERATURE,
                response_format=json_schema_format("compound_choices", prompts.CHOICE_SCHEMA),
                stream=True,
                budget_seconds=budgetSeconds)
        except Exception as ex:
            logging.warning("COMPOUND DISAMBIGUATION - batch of %d failed for job "
                            "%s (%s); those names are left to the user",
                            len(batch), jobID, ex)
            for decision in batch:
                abstained.append({"title": decision["title"], "keggID": None,
                                  "confidence": "", "reason": "",
                                  "detail": "the AI service could not be reached",
                                  "tier": "ai", "candidates": decision.get("candidates", [])})
            continue

        batchAccepted, batchAbstained, batchRejected = applyChoices(batch, parseChoices(reply))
        accepted.extend(batchAccepted)
        abstained.extend(batchAbstained)
        rejected.extend(batchRejected)

    # The audit trail. Nothing about these choices is written to the job, so
    # the log is where "which compound did the model pick for job X, and what
    # did it refuse" is recoverable afterwards.
    for entry in accepted:
        logging.info("COMPOUND DISAMBIGUATION - job %s: %r -> %s (%s) %s",
                     jobID, entry["title"], entry["keggID"], entry["confidence"],
                     entry["reason"])
    for entry in rejected:
        logging.warning("COMPOUND DISAMBIGUATION - job %s: REJECTED an answer for "
                        "%r: %s", jobID, entry.get("title", ""), entry.get("detail", ""))

    return {"accepted": accepted, "abstained": abstained, "rejected": rejected,
            "model": getattr(client, "model", ""), "batches": batches}
