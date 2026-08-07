import requests
import json
import os
import logging
import threading
import time

logger = logging.getLogger(__name__)

# Timeout as (connect, read) tuple.
# - connect: 15s is generous for DNS + TLS handshake
# - read: 180s per chunk — if the API hasn't sent any data in 3 min, it's hung
DEFAULT_TIMEOUT = (15, 180)

# Read timeout for short, high-fan-out calls -- per-citation verification,
# quote lookup, paper filtering. Measured on the CSIC gateway: the median such
# call returns in ~3.5s while roughly one in sixteen stalls for ~60s, and a
# ThreadPoolExecutor waits for the slowest. At the 180s default a single
# straggler holds a phase for three minutes before the retry below (which
# usually succeeds in seconds) even begins. Cutting the read timeout turns the
# existing retry into straggler hedging without new machinery.
SHORT_CALL_TIMEOUT = (15, int(os.getenv("AI_SHORT_CALL_READ_TIMEOUT", "45")))

# Not every OpenAI-compatible gateway implements response_format. Verified
# working on the CSIC gateway (vLLM 0.26.0, guided decoding) on 2026-08-07;
# a self-hosted server behind the same API can still reject it with a 400.
# Probe once per endpoint, remember the answer, and fall back to free-text
# parsing rather than failing the run.
_SCHEMA_SUPPORT = {}       # api_base -> bool
_SCHEMA_SUPPORT_LOCK = threading.Lock()


def json_schema_format(name, schema):
    """Build the response_format payload for a strict JSON schema."""
    return {"type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema}}


class LLMClient:
    """OpenAI-compatible chat completion via requests. Thread-safe (no global state)."""

    def __init__(self, provider_config):
        self.api_base = provider_config["api_base"].rstrip("/")
        self.api_key = provider_config["api_key"]
        self.model = provider_config["model"]

    def supports_schema(self):
        """Whether this endpoint has accepted response_format so far.

        Optimistic until proven otherwise: unknown endpoints are tried once,
        and a 400 demotes them permanently for the process lifetime.
        """
        with _SCHEMA_SUPPORT_LOCK:
            return _SCHEMA_SUPPORT.get(self.api_base, True)

    def _demote_schema(self):
        with _SCHEMA_SUPPORT_LOCK:
            if _SCHEMA_SUPPORT.get(self.api_base, True):
                logger.warning(
                    "Endpoint %s rejected response_format; falling back to "
                    "free-text parsing for the rest of this process.",
                    self.api_base)
            _SCHEMA_SUPPORT[self.api_base] = False

    def complete(self, messages, max_tokens=4096, temperature=0.3,
                 response_format=None, timeout=None):
        # Drop the schema up front on an endpoint already known to reject it,
        # so we pay the 400 once per process rather than once per call.
        if response_format is not None and not self.supports_schema():
            response_format = None

        for attempt in range(3):  # 2 retries
            try:
                logger.info(f"LLM complete: model={self.model}, "
                            f"msgs={len(messages)}, max_tokens={max_tokens} "
                            f"(attempt {attempt + 1})")
                payload = {"model": self.model, "messages": messages,
                           "max_tokens": max_tokens, "temperature": temperature}
                if response_format is not None:
                    payload["response_format"] = response_format
                r = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                    timeout=timeout or DEFAULT_TIMEOUT,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                logger.info(f"LLM complete: got {len(content)} chars")
                return content
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.warning(f"LLM request failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))  # 5s, 10s backoff
                    continue
                raise
            except requests.exceptions.HTTPError as e:
                # A 400 while we were asking for a schema is the signature of a
                # gateway that doesn't implement response_format. Retry once
                # without it so the caller's text parser can still run, instead
                # of failing a job over an optional feature.
                if (e.response is not None and e.response.status_code == 400
                        and response_format is not None):
                    self._demote_schema()
                    response_format = None
                    continue
                # 429 is the one 4xx that DOES self-heal. It was being lumped in
                # with auth/bad-request and raised immediately, so a moment of
                # rate limiting on a shared gateway killed a whole multi-minute
                # job at the last phase. Back off and retry, honouring
                # Retry-After when the server sends one.
                if e.response is not None and e.response.status_code == 429:
                    if attempt < 2:
                        wait = 5 * (attempt + 1)
                        try:
                            wait = max(wait, int(e.response.headers.get("Retry-After", 0)))
                        except (AttributeError, TypeError, ValueError):
                            pass  # missing or unusable Retry-After: keep the backoff
                        logger.warning("LLM rate limited (429), retrying in %ss "
                                       "(attempt %d/3)", wait, attempt + 1)
                        time.sleep(wait)
                        continue
                    logger.error("LLM rate limited (429) after 3 attempts")
                    raise
                # Don't retry other 4xx errors (auth, bad request) — they won't self-heal
                if e.response is not None and 400 <= e.response.status_code < 500:
                    logger.error(f"LLM HTTP {e.response.status_code}: {e.response.text[:500]}")
                    raise
                logger.warning(f"LLM server error (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise

    def complete_json(self, messages, schema_name, schema, fallback_parser,
                      max_tokens=4096, temperature=0.3, timeout=None):
        """Schema-enforced JSON with the hand-rolled parser as a safety net.

        Returns the parsed dict. The schema does the work wherever the gateway
        supports it; ``fallback_parser`` covers gateways that don't and the
        residual case of a model emitting valid-but-unexpected JSON.

        This is deliberately additive: every caller keeps its parser, so the
        worst case is exactly today's behaviour.
        """
        text = self.complete(
            messages, max_tokens=max_tokens, temperature=temperature,
            response_format=json_schema_format(schema_name, schema), timeout=timeout)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return fallback_parser(text)

    def complete_with_tools_json(self, messages, tools, tool_executor,
                                 schema_name, schema, fallback_parser,
                                 max_tokens=4096, temperature=0.3,
                                 max_iterations=5, timeout=None):
        """Tool loop that ends in schema-enforced JSON.

        Why this is two steps rather than one flag on the loop: passing
        ``response_format`` alongside ``tools`` is accepted by the gateway but
        silently defeats it. Grammar-constrained decoding forces the very first
        token to open the JSON object, so the model can never emit a tool call
        -- it answers immediately from priors and returns a confident,
        unevidenced verdict. Verified against the CSIC gateway on 2026-08-07.

        So: run the tool loop unconstrained, let the agent gather its evidence,
        then spend one extra cheap call to coerce the finished answer into the
        schema.
        """
        text = self.complete_with_tools(
            messages, tools, tool_executor, max_tokens=max_tokens,
            temperature=temperature, max_iterations=max_iterations, timeout=timeout)

        # Spend nothing when the model already answered in clean JSON, which is
        # the common case. The coercion call exists to rescue the malformed
        # tail, not to be paid on every citation -- billing a second request per
        # verification is how this phase started tripping the gateway's rate
        # limit.
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = "\n".join(l for l in stripped.split("\n")
                                 if not l.strip().startswith("```")).strip()
        try:
            direct = json.loads(stripped)
            if isinstance(direct, dict):
                return direct
        except (json.JSONDecodeError, ValueError):
            pass

        if not self.supports_schema():
            return fallback_parser(text)

        try:
            coerced = self.complete(
                messages=[
                    {"role": "system",
                     "content": "Convert the analysis below into the required "
                                "JSON object. Do not add, drop, or soften any "
                                "finding -- report exactly what it concluded."},
                    {"role": "user", "content": text},
                ],
                max_tokens=max_tokens, temperature=0.0,
                response_format=json_schema_format(schema_name, schema), timeout=timeout)
            parsed = json.loads(coerced)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("Schema coercion failed, using text parser: %s", e)
        except requests.exceptions.RequestException as e:
            logger.warning("Schema coercion request failed, using text parser: %s", e)
        return fallback_parser(text)

    def complete_with_tools(self, messages, tools, tool_executor,
                            max_tokens=4096, temperature=0.3, max_iterations=5,
                            timeout=None):
        """Chat completion with function-calling tool loop.

        Args:
            messages: Conversation messages (will be mutated with tool interactions).
            tools: List of tool definitions in OpenAI function-calling format.
            tool_executor: Callable(tool_name: str, args: dict) -> str.
            max_iterations: Safety cap on tool-call round-trips.

        Returns:
            Final text content from the assistant (after all tool calls resolved).
        """
        for iteration in range(max_iterations):
            for attempt in range(3):  # 2 retries on network errors
                try:
                    logger.info(f"LLM tool loop iter={iteration + 1}/{max_iterations}, "
                                f"msgs={len(messages)} (attempt {attempt + 1})")
                    r = requests.post(
                        f"{self.api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": tools,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                        },
                        timeout=timeout or DEFAULT_TIMEOUT,
                    )
                    r.raise_for_status()
                    break
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(f"LLM tool request failed (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise
                except requests.exceptions.HTTPError as e:
                    if e.response is not None and 400 <= e.response.status_code < 500:
                        logger.error(f"LLM HTTP {e.response.status_code}: {e.response.text[:500]}")
                        raise
                    logger.warning(f"LLM server error (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise

            resp_msg = r.json()["choices"][0]["message"]
            tool_calls = resp_msg.get("tool_calls")

            if not tool_calls:
                # No more tool calls — return the final text answer
                content = resp_msg.get("content", "")
                logger.info(f"LLM tool loop done at iter={iteration + 1}, got {len(content)} chars")
                return content

            # Append the assistant message (with tool_calls) to conversation
            messages.append(resp_msg)

            # Execute each tool and append results
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}

                logger.info(f"LLM tool call: {fn_name}({fn_args})")
                result_str = tool_executor(fn_name, fn_args)
                logger.info(f"LLM tool result: {fn_name} -> {len(result_str)} chars")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

        # Safety: if we exhausted iterations, do one final call without tools
        logger.warning("Tool loop reached max_iterations, making final call without tools")
        return self.complete(messages, max_tokens=max_tokens, temperature=temperature)

    def complete_streaming(self, messages, max_tokens=4096, temperature=0.3):
        """Yields text chunks. Used for MongoDB text-buffer approach."""
        r = requests.post(
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "max_tokens": max_tokens, "temperature": temperature, "stream": True},
            timeout=DEFAULT_TIMEOUT, stream=True,
        )
        r.raise_for_status()
        for line in r.iter_lines():
            if line and line.startswith(b"data: ") and line != b"data: [DONE]":
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
                except json.JSONDecodeError:
                    continue
