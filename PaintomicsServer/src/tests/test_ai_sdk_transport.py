#!/usr/bin/env python3
"""The Agents SDK transport must stream, must own its retries, and must be bounded.

Why this exists
---------------
On 2026-08-17 two live interpretations on paintomics.uv.es sat at "Synthesizing
report... 78%" for over an hour and a half (jobs 4101fcI63x, Wj2Nc70376). The
citation top-up asks the model to return the whole report again; for the
105-pathway STATegra example that answer is ~17k tokens, and the CSIC gateway
gives each *non-streamed* attempt about 120 s before it gives up (measured:
14k tokens took 477 s = four internal attempts; the top-up got HTTP 408 after
489 s, three times in a row). Streaming does not have that ceiling -- a 25k
token generation streamed through in 203 s -- because the budget is per read,
not per response.

Three transport defects turned "one slow call" into "never finishes":

  1. Nothing streamed. Every SDK call went through ``create(stream=False)``.
  2. Retries multiplied. ``AsyncOpenAI`` retries 408 twice on its own, and
     ``_paced_create`` retried the whole thing four times: 12 attempts, each
     eight minutes long.
  3. Nothing bounded the call. ``run_hedged`` caps the short calls at 45 s, but
     synthesis, gap-fill, top-up and the correction rewrite were bare
     ``Runner.run`` awaits, and the heartbeat kept the job "alive" throughout.

The tests below pin the fixed contract:

  * ``_stream_to_completion`` folds a chunk stream (content, tool calls, usage)
    into a ``ChatCompletion`` the SDK can consume unchanged.
  * ``configure_sdk`` hands the SDK a client with ``max_retries=0`` and a
    finite timeout, and its ``create`` shim streams by default and passes a
    caller's ``stream=True`` straight through.
  * ``bounded`` cancels an awaitable at its deadline instead of waiting on it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_sdk_transport
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key")


def _chunk(**kw):
    """A ChatCompletionChunk with one choice, built from delta fields."""
    from openai.types.chat import ChatCompletionChunk
    delta = kw.pop("delta", {})
    finish = kw.pop("finish_reason", None)
    usage = kw.pop("usage", None)
    return ChatCompletionChunk.model_validate({
        "id": "chatcmpl-test", "object": "chat.completion.chunk",
        "created": 1, "model": "stub-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        "usage": usage,
    })


class _FakeStream:
    """Stands in for openai's AsyncStream: async-iterable, closable."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def __aiter__(self):
        async def _gen():
            for c in self._chunks:
                yield c
        return _gen()

    async def close(self):
        self.closed = True


class StreamReassemblyTest(unittest.TestCase):

    def test_content_and_usage_fold_into_a_chat_completion(self):
        from src.classes.AIInterpret.agent import _stream_to_completion
        from openai.types.chat import ChatCompletion
        stream = _FakeStream([
            _chunk(delta={"role": "assistant", "content": "Hel"}),
            _chunk(delta={"content": "lo"}),
            _chunk(delta={"content": " [1]"}, finish_reason="stop"),
            _chunk(usage={"prompt_tokens": 10, "completion_tokens": 3,
                          "total_tokens": 13}),
        ])
        done = asyncio.run(_stream_to_completion(stream))
        self.assertIsInstance(done, ChatCompletion)
        self.assertEqual(done.choices[0].message.content, "Hello [1]")
        self.assertEqual(done.choices[0].message.role, "assistant")
        self.assertEqual(done.choices[0].finish_reason, "stop")
        self.assertEqual(done.usage.completion_tokens, 3)
        self.assertEqual(done.usage.total_tokens, 13)
        self.assertEqual(done.id, "chatcmpl-test")
        self.assertEqual(done.object, "chat.completion")
        self.assertTrue(stream.closed, "the stream must be closed once folded")

    def test_tool_call_deltas_are_joined_by_index(self):
        from src.classes.AIInterpret.agent import _stream_to_completion
        stream = _FakeStream([
            _chunk(delta={"role": "assistant", "content": None,
                          "tool_calls": [{"index": 0, "id": "call_a",
                                          "type": "function",
                                          "function": {"name": "get_gene_timecourse",
                                                       "arguments": ""}}]}),
            _chunk(delta={"tool_calls": [{"index": 0,
                                          "function": {"arguments": "{\"gene_sym"}}]}),
            _chunk(delta={"tool_calls": [{"index": 0,
                                          "function": {"arguments": "bol\": \"Ccl2\"}"}}]}),
            _chunk(delta={"tool_calls": [{"index": 1, "id": "call_b",
                                          "type": "function",
                                          "function": {"name": "compare_genes",
                                                       "arguments": "{}"}}]}),
            _chunk(delta={}, finish_reason="tool_calls"),
        ])
        done = asyncio.run(_stream_to_completion(stream))
        calls = done.choices[0].message.tool_calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].id, "call_a")
        self.assertEqual(calls[0].function.name, "get_gene_timecourse")
        self.assertEqual(calls[0].function.arguments, '{"gene_symbol": "Ccl2"}')
        self.assertEqual(calls[1].id, "call_b")
        self.assertEqual(calls[1].function.name, "compare_genes")
        self.assertEqual(done.choices[0].finish_reason, "tool_calls")
        self.assertIsNone(done.choices[0].message.content)

    def test_no_usage_chunk_yields_no_usage(self):
        # vLLM only sends usage when stream_options asks for it; the SDK treats a
        # missing usage as zero rather than crashing, so None must survive.
        from src.classes.AIInterpret.agent import _stream_to_completion
        stream = _FakeStream([_chunk(delta={"content": "x"}, finish_reason="stop")])
        done = asyncio.run(_stream_to_completion(stream))
        self.assertIsNone(done.usage)
        self.assertEqual(done.choices[0].message.content, "x")

    def test_an_empty_stream_is_an_error_not_an_empty_answer(self):
        # A gateway that closes the stream without a single choice has not
        # answered; surfacing that as a retryable error beats handing the SDK
        # a blank message it would score as "the model said nothing".
        from src.classes.AIInterpret.agent import _stream_to_completion, _EmptyStream
        with self.assertRaises(_EmptyStream):
            asyncio.run(_stream_to_completion(_FakeStream([])))


class ClientConfigurationTest(unittest.TestCase):

    def setUp(self):
        import src.classes.AIInterpret.agent as agent
        self.agent = agent
        self._saved = (agent._sdk_configured, agent._MODEL_OBJ)
        agent._sdk_configured = False
        agent._MODEL_OBJ = None

    def tearDown(self):
        self.agent._sdk_configured, self.agent._MODEL_OBJ = self._saved

    def test_client_owns_no_retries_and_has_a_finite_timeout(self):
        self.agent.configure_sdk()
        client = self.agent._MODEL_OBJ._client
        self.assertEqual(client.max_retries, 0,
                         "the shim is the only retry policy; stacked retries "
                         "made one 408 cost twelve eight-minute attempts")
        timeout = client.timeout
        # httpx.Timeout or a float -- either way every phase must be finite.
        read = getattr(timeout, "read", timeout)
        self.assertIsNotNone(read)
        self.assertLess(float(read), 600.0)

    def test_create_streams_by_default_and_passes_stream_true_through(self):
        self.agent.configure_sdk()
        client = self.agent._MODEL_OBJ._client
        calls = []

        async def fake_orig(*args, **kwargs):
            calls.append(kwargs)
            if kwargs.get("stream") is True and kwargs.get("_passthrough_test"):
                return "raw-stream"
            return _FakeStream([_chunk(delta={"content": "ok"}, finish_reason="stop")])

        # The shim keeps the original under a known name so tests (and a
        # future provider that cannot stream) can reach it.
        client.chat.completions._pa_orig_create = fake_orig
        from openai.types.chat import ChatCompletion

        done = asyncio.run(client.chat.completions.create(model="m", messages=[]))
        self.assertIsInstance(done, ChatCompletion)
        self.assertEqual(done.choices[0].message.content, "ok")
        self.assertIs(calls[-1].get("stream"), True,
                      "a non-streaming call must be issued as a stream")
        self.assertEqual(calls[-1].get("stream_options"), {"include_usage": True})

        raw = asyncio.run(client.chat.completions.create(
            model="m", messages=[], stream=True, _passthrough_test=True))
        self.assertEqual(raw, "raw-stream")


class BoundedAwaitTest(unittest.TestCase):

    def test_bounded_cancels_at_the_deadline(self):
        from src.classes.AIInterpret.agent import bounded
        state = {"cancelled": False}

        async def hang():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        async def go():
            with self.assertRaises(asyncio.TimeoutError):
                await bounded(hang(), 0.05, label="hang")
        asyncio.run(go())
        self.assertTrue(state["cancelled"])

    def test_bounded_returns_the_value_in_time(self):
        from src.classes.AIInterpret.agent import bounded

        async def quick():
            return 42
        self.assertEqual(asyncio.run(bounded(quick(), 1.0, label="quick")), 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
