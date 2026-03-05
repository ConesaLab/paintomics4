---
name: openai-agents-sdk
description: Build agentic AI applications using the OpenAI Agents SDK (Python). Use this skill whenever the user wants to create, configure, or debug agents built with the `openai-agents` package, including defining agents with instructions/tools/handoffs, running agents with Runner, streaming responses, multi-agent orchestration (handoffs or manager pattern), guardrails (input/output/tool), sessions and memory persistence (SQLite, SQLAlchemy, OpenAI Conversations, encrypted), human-in-the-loop tool approval flows, MCP server integration, tracing and observability, context management and dependency injection, structured output types, voice pipelines (STT/TTS), realtime voice agents (WebSocket), LiteLLM integration for non-OpenAI models, function tools, hosted tools (web search, file search, code interpreter, image generation), agents-as-tools, REPL demo loops, or any workflow involving `from agents import ...`. Trigger this skill even for partial mentions like "agents SDK", "openai agents", "handoff", "guardrail agent", "voice pipeline", "realtime agent", or questions about RunConfig, RunResult, RunState, or the agent loop.
---

# OpenAI Agents SDK — Skill Reference

> **Package**: `pip install openai-agents`
> **Import**: `from agents import Agent, Runner, function_tool, ...`
> **Docs**: https://openai.github.io/openai-agents-python/
> **Repo**: https://github.com/openai/openai-agents-python

---

## 1. Core Concepts

The SDK has three primitives: **Agents** (LLMs with instructions + tools), **Handoffs** (delegation between agents), and **Guardrails** (input/output validation). Everything else is built on top.

### 1.1 Hello World

```python
from agents import Agent, Runner

agent = Agent(name="Assistant", instructions="You are a helpful assistant")
result = Runner.run_sync(agent, "Hello!")
print(result.final_output)
```

Set `OPENAI_API_KEY` env var before running.

---

## 2. Agents

```python
from agents import Agent, ModelSettings, function_tool

@function_tool
def get_weather(city: str) -> str:
    """Returns weather for the city."""
    return f"Sunny in {city}"

agent = Agent(
    name="Weather Bot",
    instructions="Help with weather queries.",  # static or dynamic function
    model="gpt-4.1",                            # optional, default gpt-4.1
    model_settings=ModelSettings(temperature=0.5),
    tools=[get_weather],
    handoffs=[],           # list of Agent or Handoff objects
    output_type=str,       # or Pydantic model, dataclass, TypedDict
    input_guardrails=[],
    output_guardrails=[],
)
```

**Key Agent parameters**: `name`, `instructions` (str or callable), `model`, `model_settings`, `tools`, `mcp_servers`, `mcp_config`, `handoffs`, `output_type`, `input_guardrails`, `output_guardrails`, `prompt` (for OpenAI prompt templates), `reset_tool_choice`, `tool_use_behavior`.

**Dynamic instructions**:
```python
def dynamic_instructions(context: RunContextWrapper[MyCtx], agent: Agent) -> str:
    return f"User is {context.context.name}."

agent = Agent(instructions=dynamic_instructions, ...)
```

**Structured output**:
```python
from pydantic import BaseModel

class Event(BaseModel):
    name: str
    date: str

agent = Agent(name="Extractor", output_type=Event, ...)
```

**Lifecycle hooks**: Use `RunHooks` (whole workflow) or `AgentHooks` (per-agent) for `on_agent_start`, `on_llm_end`, `on_tool_start`, `on_tool_end`, `on_agent_end`, etc.

---

## 3. Tools

### 3.1 Function Tools

```python
from agents import function_tool

@function_tool
async def fetch_data(query: str, limit: int = 10) -> str:
    """Fetch data from API.

    Args:
        query: Search query.
        limit: Max results.
    """
    return f"Results for {query}"
```

- Name, description, and schema auto-extracted from function signature and docstring.
- Override with `@function_tool(name_override="...", description_override="...")`.
- First arg can be `RunContextWrapper` for context access (not sent to LLM).
- Supports `timeout=2.0`, `timeout_behavior="error_as_result"|"raise_exception"`.
- `failure_error_function` for custom error handling.
- Return types: `str`, `ToolOutputImage`, `ToolOutputFileContent`, or lists thereof.

### 3.2 Hosted Tools (Responses API only)

```python
from agents import Agent, WebSearchTool, FileSearchTool, CodeInterpreterTool, ImageGenerationTool, HostedMCPTool

agent = Agent(
    tools=[
        WebSearchTool(),
        FileSearchTool(vector_store_ids=["vs_..."], max_num_results=3),
        CodeInterpreterTool(),
        ImageGenerationTool(),
        HostedMCPTool(tool_config={...}),
    ]
)
```

### 3.3 Agents as Tools

```python
specialist = Agent(name="Translator", instructions="Translate to Spanish")
orchestrator = Agent(
    name="Manager",
    tools=[
        specialist.as_tool(
            tool_name="translate_spanish",
            tool_description="Translate text to Spanish",
        )
    ],
)
```

Options: `custom_output_extractor`, `needs_approval`, `parameters`, `input_builder`, `max_turns`, `run_config`, `session`.

### 3.4 Local Runtime Tools

- `ShellTool(executor=run_shell_fn)` — local shell execution
- `ShellTool(environment={"type": "container_auto", ...})` — hosted container
- `ComputerTool` — implement `Computer`/`AsyncComputer` interface
- `ApplyPatchTool` — implement `ApplyPatchEditor` interface

### 3.5 Experimental: Codex Tool

Workspace-scoped Codex tasks from tool calls.

---

## 4. Running Agents

### 4.1 Runner Methods

```python
from agents import Runner

# Async
result = await Runner.run(agent, "input", context=my_ctx, max_turns=10)

# Sync
result = Runner.run_sync(agent, "input")

# Streaming
result = Runner.run_streamed(agent, "input")
async for event in result.stream_events():
    ...
```

All accept: `starting_agent`, `input` (str, list, or RunState), `context`, `max_turns`, `hooks`, `run_config`, `previous_response_id`, `conversation_id`, `session`, `error_handlers`.

### 4.2 The Agent Loop

1. Agent invoked with input → LLM called
2. If final output (matching `output_type`, no tool calls) → done
3. If handoff → switch agent, re-run loop
4. If tool calls → execute tools, append results, re-run loop
5. Exceeding `max_turns` → `MaxTurnsExceeded` (unless `error_handlers` handles it)

### 4.3 RunConfig

```python
from agents import RunConfig

config = RunConfig(
    model="gpt-4.1",                    # global model override
    model_settings=ModelSettings(...),   # global settings override
    model_provider=my_provider,          # custom model provider
    tracing_disabled=False,
    input_guardrails=[...],
    output_guardrails=[...],
    handoff_input_filter=my_filter,
    nest_handoff_history=False,          # opt-in beta
    session_settings=SessionSettings(limit=50),
    session_input_callback=my_callback,
    tool_error_formatter=my_formatter,
)
result = await Runner.run(agent, "input", run_config=config)
```

### 4.4 Carrying State Across Turns

Pick **one** strategy per conversation:

| Strategy | Type | How |
|---|---|---|
| `result.to_input_list()` | Client-managed | Pass as input to next `Runner.run()` |
| `Session` | Client-managed | Pass `session=` param |
| `conversation_id` | OpenAI-managed | Responses API only |
| `previous_response_id` | OpenAI-managed | Responses API only |

Do not mix client-managed and server-managed in the same run.

---

## 5. Streaming

```python
from openai.types.responses import ResponseTextDeltaEvent

result = Runner.run_streamed(agent, "Tell me a joke")
async for event in result.stream_events():
    if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
        print(event.data.delta, end="", flush=True)
    elif event.type == "run_item_stream_event":
        # Higher-level: message_output_item, tool_call_item, tool_call_output_item, etc.
        pass
    elif event.type == "agent_updated_stream_event":
        print(f"Switched to: {event.new_agent.name}")
```

Event types: `RawResponsesStreamEvent`, `RunItemStreamEvent`, `AgentUpdatedStreamEvent`.

---

## 6. Multi-Agent Orchestration

Two patterns:

### 6.1 Handoffs (decentralized)

Agent hands off control to a specialist who takes over the conversation.

```python
triage = Agent(
    name="Triage",
    handoffs=[billing_agent, support_agent],
    instructions="Route to the right specialist.",
)
```

### 6.2 Manager / Agents-as-Tools (centralized)

Orchestrator calls sub-agents as tools and retains control.

```python
manager = Agent(
    name="Manager",
    tools=[
        billing_agent.as_tool(tool_name="billing", tool_description="..."),
        support_agent.as_tool(tool_name="support", tool_description="..."),
    ],
)
```

### 6.3 Code-Based Orchestration

Use `asyncio.gather()`, structured outputs for routing, chaining agent outputs as inputs.

---

## 7. Handoffs

```python
from agents import handoff, Handoff

h = handoff(
    agent=refund_agent,
    tool_name_override="escalate_to_refunds",
    tool_description_override="For refund requests",
    on_handoff=my_callback,       # called on handoff with input_type data
    input_type=MyHandoffArgs,     # schema for handoff tool-call arguments
    input_filter=my_filter,       # filter/transform input for next agent
    is_enabled=True,              # bool or callable
)
agent = Agent(handoffs=[h])
```

- `input_filter` controls what the receiving agent sees (e.g., remove tool calls).
- Common filters in `agents.extensions.handoff_filters`.
- `nest_handoff_history` (RunConfig or per-handoff) collapses prior transcript.

---

## 8. Guardrails

### 8.1 Input Guardrails

Run on user input, in parallel with agent execution (or blocking if `run_in_parallel=False`). Only the first agent's input guardrails run.

```python
from agents import input_guardrail, GuardrailFunctionOutput, Agent, Runner

@input_guardrail
async def check_safety(ctx, agent, input) -> GuardrailFunctionOutput:
    result = await Runner.run(safety_agent, input, context=ctx.context)
    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_unsafe,
    )

agent = Agent(input_guardrails=[check_safety], ...)
```

### 8.2 Output Guardrails

Run after the agent that produces the final output.

```python
from agents import output_guardrail

@output_guardrail
async def check_output(ctx, agent, output) -> GuardrailFunctionOutput:
    ...
```

### 8.3 Tool Guardrails

Run before/after every custom function-tool invocation. Configured on the tool itself.

Tripwires raise `InputGuardrailTripwireTriggered` or `OutputGuardrailTripwireTriggered`.

---

## 9. Sessions (Persistent Memory)

```python
from agents import Agent, Runner, SQLiteSession

session = SQLiteSession("user_123", "conversations.db")
result = await Runner.run(agent, "Hi", session=session)
# Next turn automatically includes history
result = await Runner.run(agent, "Follow up", session=session)
```

**Built-in session backends**:
- `SQLiteSession` — lightweight, file-based
- `SQLAlchemySession` — any SQLAlchemy-supported DB
- `OpenAIConversationsSession` — OpenAI-hosted storage
- `OpenAIResponsesCompactionSession` — auto-compact history
- `EncryptedSession` — wraps any session with encryption + TTL
- `AdvancedSQLiteSession` — async SQLite with more features
- `RedisSession`, `DaprSession` — community backends

`session.pop_item()` to remove items (e.g., for correction flows).

Session cannot be combined with `conversation_id`/`previous_response_id` in the same run.

---

## 10. Human-in-the-Loop

### 10.1 Function Tool Approval

```python
@function_tool(needs_approval=True)  # or a callable
async def delete_files(path: str) -> str:
    ...
```

### 10.2 Pause / Resume Flow

```python
result = await Runner.run(agent, "Delete temp files")

if result.interruptions:
    state = result.to_state()
    # Persist state: state.to_string() → save to DB/file
    
    for interruption in result.interruptions:
        if user_approves(interruption):
            state.approve(interruption)  # or always_approve=True
        else:
            state.reject(interruption)
    
    # Resume
    result = await Runner.run(agent, state)
```

`RunState` is serializable via `to_string()` / `from_string()`.

Also supported on: `ShellTool`, `ApplyPatchTool`, MCP servers (`require_approval`), hosted MCP (`HostedMCPTool`), `Agent.as_tool(..., needs_approval=...)`.

---

## 11. Context Management

Context is dependency injection — any Python object passed to `Runner.run(..., context=obj)`.

```python
from dataclasses import dataclass

@dataclass
class AppContext:
    user_id: str
    db: Database

agent = Agent[AppContext](name="Bot", ...)
result = await Runner.run(agent, "query", context=AppContext(user_id="123", db=db))
```

- Accessed via `RunContextWrapper.context` in tools, hooks, guardrails, instructions.
- `ToolContext` extends `RunContextWrapper` with tool-level metadata (`.tool_name`, `.call_id`, `.tool_input`).
- Context is **not** sent to the LLM. To expose data to the LLM, put it in instructions or tool results.
- Same context type required for all agents/tools in a run.

---

## 12. Results

```python
result = await Runner.run(agent, "query")

result.final_output          # The final output (typed)
result.final_output_as(MyType)  # Cast with optional type check
result.new_items             # Items generated during the run
result.to_input_list()       # For multi-turn: original input + new items
result.last_response_id      # Latest model response ID
result.input                 # Original input
result.raw_responses         # Raw ModelResponse objects
result.input_guardrail_results
result.output_guardrail_results
result.interruptions         # Pending tool approvals (HITL)
result.to_state()            # Convert to RunState for pause/resume
```

---

## 13. Models

### 13.1 Default: OpenAI

```python
agent = Agent(model="gpt-4.1", ...)        # Responses API (default)
agent = Agent(model="gpt-5-nano", ...)
```

### 13.2 Non-OpenAI via LiteLLM

```bash
pip install "openai-agents[litellm]"
```

```python
from agents.extensions.models.litellm_model import LitellmModel

agent = Agent(
    model=LitellmModel(model="anthropic/claude-3-5-sonnet-20240620", api_key="..."),
    ...
)
```

Or prefix-based: `agent = Agent(model="litellm/anthropic/claude-3-5-sonnet-20240620", ...)`

### 13.3 Custom Providers

- `set_default_openai_client(AsyncOpenAI(base_url=..., api_key=...))` — global
- `ModelProvider` via `RunConfig(model_provider=...)` — per-run
- `Agent(model=MyModelImpl(...))` — per-agent

### 13.4 WebSocket Transport

```python
from agents import set_default_openai_responses_transport
set_default_openai_responses_transport("websocket")
```

Use `responses_websocket_session()` for connection reuse across turns.

### 13.5 Chat Completions API

```python
from agents import set_default_openai_api
set_default_openai_api("chat_completions")
```

---

## 14. MCP (Model Context Protocol)

### 14.1 Local MCP Servers

```python
from agents.mcp import MCPServerStdio, MCPServerStreamableHttp, MCPServerSse

# Stdio
server = MCPServerStdio(name="FS", params={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]})

# Streamable HTTP
server = MCPServerStreamableHttp(name="Remote", params={"url": "http://localhost:8000/mcp"})

# SSE (deprecated, prefer Streamable HTTP)
server = MCPServerSse(name="Legacy", params={"url": "http://localhost:8000/sse"})
```

Usage:
```python
async with server:
    agent = Agent(name="Bot", mcp_servers=[server])
    result = await Runner.run(agent, "List files")
```

### 14.2 Hosted MCP

```python
from agents import HostedMCPTool

agent = Agent(tools=[
    HostedMCPTool(tool_config={
        "type": "mcp",
        "server_label": "gitmcp",
        "server_url": "https://gitmcp.io/openai/codex",
        "require_approval": "always",  # or "never"
    })
])
```

### 14.3 Tool Filters

Filter which MCP tools are exposed: static list, dynamic callable, or `ToolFilterContext`.

### 14.4 Approval

`require_approval` on MCP servers + optional `on_approval_request` callback.

---

## 15. Tracing

Enabled by default. Traces go to OpenAI's Traces dashboard.

```python
from agents import set_tracing_disabled, trace, custom_span

# Disable globally
set_tracing_disabled(True)

# Or per-run
config = RunConfig(tracing_disabled=True)

# Custom traces
with trace("My workflow"):
    result = await Runner.run(agent, "query")

# Custom spans
with custom_span("my_step"):
    do_work()
```

Auto-created spans: `agent_span`, `generation_span`, `function_span`, `guardrail_span`, `handoff_span`, `transcription_span`, `speech_span`.

Configure tracing API key: `set_tracing_export_api_key("sk-...")`.
Sensitive data: `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA=0`.
Custom processors: implement trace processor interface for third-party destinations.

---

## 16. Realtime Agents (Voice, WebSocket)

Server-side, low-latency agents on the OpenAI Realtime API. **Beta.**

```python
from agents.realtime import RealtimeAgent, RealtimeRunner

agent = RealtimeAgent(
    name="Voice Assistant",
    instructions="Keep responses short.",
    tools=[get_weather],
    handoffs=[other_realtime_agent],
)

runner = RealtimeRunner(
    starting_agent=agent,
    config={
        "model_settings": {
            "model_name": "gpt-realtime",
            "audio": {
                "input": {"format": "pcm16", "transcription": {"model": "gpt-4o-mini-transcribe"}, "turn_detection": {"type": "semantic_vad"}},
                "output": {"format": "pcm16", "voice": "alloy"},
            },
        },
    },
)

async with runner.run() as session:
    session.send_audio(audio_bytes)
    async for event in session:
        if event.type == "audio":
            play(event.audio)
        elif event.type == "audio_interrupted":
            stop_playback()
```

Supports: function tools, handoffs between RealtimeAgents, output guardrails, `require_approval`, SIP telephony via `OpenAIRealtimeSIPModel`.

---

## 17. Voice Pipeline (STT → Agent → TTS)

```python
from agents.voice import VoicePipeline, AudioInput, StreamedAudioInput, SingleAgentVoiceWorkflow

workflow = SingleAgentVoiceWorkflow(agent)
pipeline = VoicePipeline(workflow=workflow)

# Full audio
result = await pipeline.run(AudioInput(buffer=audio_bytes))

# Streaming audio
input = StreamedAudioInput()
result = await pipeline.run(input)
input.add_audio(chunk)  # push chunks
input.close()

async for event in result.stream():
    if event.type == "voice_stream_event_audio":
        play(event.data)
```

---

## 18. Configuration

```python
from agents import (
    set_default_openai_key,
    set_default_openai_client,
    set_default_openai_api,
    set_tracing_export_api_key,
    enable_verbose_stdout_logging,
)

set_default_openai_key("sk-...")
set_default_openai_api("responses")  # or "chat_completions"
enable_verbose_stdout_logging()
```

Env vars: `OPENAI_API_KEY`, `OPENAI_AGENTS_DISABLE_TRACING`, `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA`.

---

## 19. Usage Tracking

```python
result = await Runner.run(agent, "query")
print(result.context_wrapper.usage)  # Usage object with token counts
```

---

## 20. REPL / Demo Loop

```python
from agents import Agent, run_demo_loop
import asyncio

agent = Agent(name="Bot", instructions="Be helpful.")
asyncio.run(run_demo_loop(agent))
```

Interactive terminal loop with streaming and conversation history.

---

## 21. Error Handling

Key exceptions:
- `MaxTurnsExceeded` — agent exceeded `max_turns`
- `InputGuardrailTripwireTriggered` / `OutputGuardrailTripwireTriggered`
- `ModelBehaviorError` — invalid LLM output
- `UserError` — incorrect SDK usage
- `ToolTimeoutError` — function tool timeout

Use `error_handlers={"max_turns": handler_fn}` on `Runner.run()` for graceful handling.

---

## 22. Common Patterns

### Multi-turn chatbot
```python
agent = Agent(name="Chat", instructions="Be helpful.")
session = SQLiteSession("user_1")

while True:
    user_input = input("> ")
    result = await Runner.run(agent, user_input, session=session)
    print(result.final_output)
```

### Structured extraction
```python
class Invoice(BaseModel):
    vendor: str
    amount: float
    date: str

agent = Agent(name="Extractor", instructions="Extract invoice data.", output_type=Invoice)
result = await Runner.run(agent, "Invoice from Acme, $500, 2025-01-15")
print(result.final_output.vendor)  # "Acme"
```

### Parallel agents
```python
import asyncio
results = await asyncio.gather(
    Runner.run(agent_a, "task A"),
    Runner.run(agent_b, "task B"),
)
```

---

## Quick Reference: Imports

```python
from agents import (
    Agent, Runner, RunConfig, RunState,
    function_tool, FunctionTool,
    handoff, Handoff,
    input_guardrail, output_guardrail,
    GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    WebSearchTool, FileSearchTool, CodeInterpreterTool,
    ImageGenerationTool, HostedMCPTool,
    ShellTool, ComputerTool, ApplyPatchTool,
    ModelSettings, RunContextWrapper, ToolContext,
    ItemHelpers,
    SQLiteSession,
    trace, custom_span,
    run_demo_loop,
    set_default_openai_key, set_default_openai_client,
    set_default_openai_api, set_tracing_disabled,
    enable_verbose_stdout_logging,
)
from agents.mcp import MCPServerStdio, MCPServerStreamableHttp, MCPServerSse
from agents.realtime import RealtimeAgent, RealtimeRunner
from agents.voice import VoicePipeline, SingleAgentVoiceWorkflow, AudioInput, StreamedAudioInput
from agents.extensions.models.litellm_model import LitellmModel
```
