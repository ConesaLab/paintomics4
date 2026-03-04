import requests
import json
import logging
import time

logger = logging.getLogger(__name__)

class LLMClient:
    """OpenAI-compatible chat completion via requests. Thread-safe (no global state)."""

    def __init__(self, provider_config):
        self.api_base = provider_config["api_base"].rstrip("/")
        self.api_key = provider_config["api_key"]
        self.model = provider_config["model"]

    def complete(self, messages, max_tokens=4096, temperature=0.3):
        for attempt in range(2):  # 1 retry
            try:
                r = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "messages": messages,
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=300,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == 0:
                    logger.warning(f"LLM request failed (attempt 1), retrying in 5s: {e}")
                    time.sleep(5)
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
        for _ in range(max_iterations):
            for attempt in range(2):  # 1 retry on network errors
                try:
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
                        timeout=300,
                    )
                    r.raise_for_status()
                    break
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    if attempt == 0:
                        logger.warning(f"LLM tool request failed (attempt 1), retrying in 5s: {e}")
                        time.sleep(5)
                        continue
                    raise

            resp_msg = r.json()["choices"][0]["message"]
            tool_calls = resp_msg.get("tool_calls")

            if not tool_calls:
                # No more tool calls — return the final text answer
                return resp_msg.get("content", "")

            # Append the assistant message (with tool_calls) to conversation
            messages.append(resp_msg)

            # Execute each tool and append results
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}

                result_str = tool_executor(fn_name, fn_args)
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
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "max_tokens": max_tokens, "temperature": temperature, "stream": True},
            timeout=300, stream=True,
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
