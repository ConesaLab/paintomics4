"""One turn of the conversion agent: state in, next action out.

Deliberately a plain function rather than a servlet method, so the same code
path serves the HTTP route and the corpus harness. A measurement taken through
a different code path than production is a measurement of something else.
"""

import json
import logging
import os
import re
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:                       # under the Flask app, packages resolve from src/
    from src.classes.InputConvert.prompts import SYSTEM_PROMPT, build_user_message
except ImportError:        # standalone (the corpus harness runs this directly)
    from classes.InputConvert.prompts import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

VALID_TYPES = ("code", "question", "done")

# Budget for one turn -- wall clock, retries included. convert-drawer.js polls
# a ticket 240 times a second apart (plus the round trip), so the server has
# to give up FIRST, with a reason, or it keeps spending on an answer nobody is
# waiting for while holding one of the two conversion slots. Measured on
# paintomics.uv.es 2026-08-21, when the gateway hung for an hour: on the old
# unbounded, non-streamed path every turn took 3 x 180 s, every browser gave
# up at four minutes with a bare "timed out", and the next click found both
# slots taken. Healthy turns take 1-11 s (same log, that morning).
TURN_BUDGET_SECONDS = int(os.getenv("AI_CONVERT_TURN_SECONDS", "150"))

# Per socket read. The answer is streamed, so this means "no token for N
# seconds", not "the whole answer within N seconds"; the first token of a
# healthy turn arrives in about a second.
READ_TIMEOUT_SECONDS = int(os.getenv("AI_CONVERT_READ_TIMEOUT", "60"))


class GatewayUnavailable(Exception):
    """The model gateway did not deliver an answer for this turn.

    Distinct from `None` (the gateway answered; the answer did not parse).
    The agent loop retries a None -- the model may do better next time -- but
    a gateway that is not answering will not answer the retry either, and the
    browser stops listening after about four minutes. The servlet turns this
    into a failed ticket carrying the message, so the user reads "the AI
    service did not answer" inside the budget instead of "timed out" after it.

    `fact` is the one-clause statement of what happened, kept separately so a
    later refusal can quote it ("... did not answer a moment ago") without
    repeating the advice.
    """

    def __init__(self, fact, advice="It may be busy or down; please try again in a few minutes."):
        self.fact = str(fact).rstrip(".")
        super().__init__((self.fact + ". " + advice).strip())


def _describe_failure(exc):
    """(fact, advice) for the user, from whatever the transport raised."""
    import requests
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return ("The AI service did not answer within %d seconds" % TURN_BUDGET_SECONDS,
                "It may be busy or down; please try again in a few minutes.")
    if status == 429:
        return ("The AI service is rate-limiting requests",
                "Please try again in a minute.")
    if status:
        return ("The AI service refused the request (HTTP %d)" % status,
                "Please try again later.")
    return ("The AI service failed: %s" % (str(exc)[:200] or type(exc).__name__),
            "Please try again later.")


def _extract_json(text):
    """Pull the action object out of whatever the model wrapped it in.

    Schema mode is not available on every gateway (llm_client probes and
    demotes), so the reply can arrive as bare JSON, fenced JSON, or JSON with
    prose either side. All three are recoverable; guessing is not, so anything
    else returns None and the loop retries.
    """
    if not text:
        return None
    text = text.strip()

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


def normalise_action(raw):
    """Reject anything that is not one of the three actions.

    The model has no tool registry to reach past, and this is what enforces
    that: an unknown `type`, or a `code` action with no source, is a parse
    failure rather than something the loop tries to interpret.
    """
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind not in VALID_TYPES:
        return None
    if kind == "code":
        source = raw.get("python") or raw.get("code")
        if not source or not str(source).strip():
            return None
        return {"type": "code", "python": str(source),
                "summary": str(raw.get("summary", ""))[:200]}
    if kind == "question":
        text = raw.get("text")
        if not text:
            return None
        options = raw.get("options") or []
        return {"type": "question", "text": str(text)[:600],
                "field": str(raw.get("field", "answer"))[:40],
                "options": [str(o)[:120] for o in options][:6]}
    return {"type": "done"}


def next_action(state, client=None):
    """Ask the model what to do next.

    Returns a normalised action, or None when the model answered with
    something that is not one. Raises GatewayUnavailable when the gateway did
    not answer inside TURN_BUDGET_SECONDS -- the two are different failures
    and the loop must treat them differently (retry the first, stop on the
    second).
    """
    if client is None:
        try:
            from src.classes.AIInterpret.llm_client import LLMClient
            from src.conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER
        except ImportError:
            from classes.AIInterpret.llm_client import LLMClient
            from conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER
        client = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER], AI_LLM_PROVIDER)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(state)},
    ]

    try:
        # Streamed and bounded, like every other long call to this gateway:
        # see csic-gateway-120s-per-attempt-budget. A transient 503 or 429
        # comes back at once and is retried inside the budget; a hang costs at
        # most one read timeout per attempt and the budget cuts the rest.
        reply = client.complete(messages, max_tokens=6000, temperature=0.1,
                                stream=True, timeout=(15, READ_TIMEOUT_SECONDS),
                                max_attempts=3, budget_seconds=TURN_BUDGET_SECONDS)
    except Exception as exc:
        logger.warning("input-convert turn failed: %s", exc)
        fact, advice = _describe_failure(exc)
        raise GatewayUnavailable(fact, advice) from exc

    return normalise_action(_extract_json(reply))


if __name__ == "__main__":
    # Used by the corpus harness: state JSON on stdin, action JSON on stdout.
    # A gateway failure goes to stderr and is answered with null, so the
    # harness keeps the contract it had; the servlet is the caller that turns
    # GatewayUnavailable into a user-facing failure.
    payload = json.load(sys.stdin)
    try:
        action = next_action(payload)
    except GatewayUnavailable as exc:
        sys.stderr.write("input-convert: %s\n" % exc)
        action = None
    sys.stdout.write(json.dumps(action) if action else "null")
