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
    """Ask the model what to do next. Returns a normalised action, or None."""
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
        reply = client.complete(messages, max_tokens=6000, temperature=0.1)
    except Exception as exc:
        logger.warning("input-convert turn failed: %s", exc)
        return None

    return normalise_action(_extract_json(reply))


if __name__ == "__main__":
    # Used by the corpus harness: state JSON on stdin, action JSON on stdout.
    payload = json.load(sys.stdin)
    action = next_action(payload)
    sys.stdout.write(json.dumps(action) if action else "null")
