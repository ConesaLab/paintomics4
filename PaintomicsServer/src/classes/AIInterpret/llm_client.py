import requests
import json
import logging
import time

logger = logging.getLogger(__name__)

# Timeout as (connect, read) tuple.
# - connect: 15s is generous for DNS + TLS handshake
# - read: 180s per chunk — if the API hasn't sent any data in 3 min, it's hung
DEFAULT_TIMEOUT = (15, 180)


class LLMClient:
    """OpenAI-compatible chat completion via requests. Thread-safe (no global state)."""

    def __init__(self, provider_config):
        self.api_base = provider_config["api_base"].rstrip("/")
        self.api_key = provider_config["api_key"]
        self.model = provider_config["model"]

    def complete(self, messages, max_tokens=4096, temperature=0.3):
        for attempt in range(3):  # 2 retries
            try:
                logger.info(f"LLM complete: model={self.model}, "
                            f"msgs={len(messages)}, max_tokens={max_tokens} "
                            f"(attempt {attempt + 1})")
                r = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json={"model": self.model, "messages": messages,
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=DEFAULT_TIMEOUT,
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
                # Don't retry 4xx errors (auth, bad request) — they won't self-heal
                if e.response is not None and 400 <= e.response.status_code < 500:
                    logger.error(f"LLM HTTP {e.response.status_code}: {e.response.text[:500]}")
                    raise
                logger.warning(f"LLM server error (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise

    def complete_with_tools(self, messages, tools, tool_executor,
                            max_tokens=4096, temperature=0.3, max_iterations=5):
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
                        timeout=DEFAULT_TIMEOUT,
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
