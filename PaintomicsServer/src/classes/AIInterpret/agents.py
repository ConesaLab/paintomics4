"""Agent definitions for the AI pipeline using OpenAI Agents SDK.

Agents:
  - triage_agent: select ~8 pathways from 30
  - pathway_expert: investigate one pathway deeply (dynamic instructions)
  - literature_sub_agent: read full papers, extract evidence
  - pathway_evaluator: verify pathway analysis accuracy
  - report_writer: synthesize pathway reports
  - report_evaluator: check report coherence
  - chat_agent: post-pipeline follow-up Q&A
"""
import logging

from agents import Agent, ModelSettings, set_default_openai_api, set_default_openai_client, set_tracing_disabled
from openai import AsyncOpenAI

from src.classes.AIInterpret.models import PipelineContext
from src.classes.AIInterpret.tools import EXPERT_TOOLS, SUB_AGENT_TOOLS, CHAT_TOOLS
from src.classes.AIInterpret.prompts import (
    SYSTEM_PROMPT_TRIAGE,
    SYSTEM_PROMPT_LITERATURE_SUB_AGENT,
    SYSTEM_PROMPT_PATHWAY_EVALUATOR,
    SYSTEM_PROMPT_REPORT_WRITER,
    SYSTEM_PROMPT_REPORT_EVALUATOR,
    SYSTEM_PROMPT_CHAT,
    build_pathway_expert_instructions,
)

logger = logging.getLogger(__name__)

_sdk_configured = False


def configure_sdk():
    """Configure the OpenAI Agents SDK to use our LLM provider.
    Safe to call multiple times — only configures once."""
    global _sdk_configured
    if _sdk_configured:
        return

    from src.conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER

    provider = AI_PROVIDERS[AI_LLM_PROVIDER]
    set_default_openai_api("chat_completions")
    set_default_openai_client(AsyncOpenAI(
        base_url=provider["api_base"],
        api_key=provider["api_key"],
    ))
    set_tracing_disabled(True)  # Don't send traces to OpenAI
    _sdk_configured = True
    logger.info(f"Agents SDK configured: provider={AI_LLM_PROVIDER}, model={provider['model']}")


def _get_model():
    """Return the model name from server config."""
    from src.conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER
    return AI_PROVIDERS[AI_LLM_PROVIDER]["model"]


# ---------------------------------------------------------------------------
# Agent Definitions
# ---------------------------------------------------------------------------

triage_agent = Agent[PipelineContext](
    name="Triage Agent",
    model=_get_model(),
    instructions=SYSTEM_PROMPT_TRIAGE,
    model_settings=ModelSettings(temperature=0.3),
    tools=[],
)


def build_pathway_expert(pathway_name, design_type):
    """Build a Pathway Expert agent with dynamic instructions for a specific pathway."""
    return Agent[PipelineContext](
        name="Pathway Expert",
        model=_get_model(),
        instructions=build_pathway_expert_instructions(pathway_name, design_type),
        model_settings=ModelSettings(temperature=0.3),
        tools=EXPERT_TOOLS,
    )


literature_sub_agent = Agent[PipelineContext](
    name="Literature Sub-Agent",
    model=_get_model(),
    instructions=SYSTEM_PROMPT_LITERATURE_SUB_AGENT,
    model_settings=ModelSettings(temperature=0.1),
    tools=SUB_AGENT_TOOLS,
)


pathway_evaluator = Agent[PipelineContext](
    name="Pathway Evaluator",
    model=_get_model(),
    instructions=SYSTEM_PROMPT_PATHWAY_EVALUATOR,
    model_settings=ModelSettings(temperature=0.1),
    tools=EXPERT_TOOLS,
)


report_writer = Agent[PipelineContext](
    name="Report Writer",
    model=_get_model(),
    instructions=SYSTEM_PROMPT_REPORT_WRITER,
    model_settings=ModelSettings(temperature=0.3),
    tools=[],
)


report_evaluator = Agent[PipelineContext](
    name="Report Evaluator",
    model=_get_model(),
    instructions=SYSTEM_PROMPT_REPORT_EVALUATOR,
    model_settings=ModelSettings(temperature=0.1),
    tools=[],
)


def build_chat_agent(report_text):
    """Build a Chat agent with the analysis report in its instructions."""
    instructions = (
        f"{SYSTEM_PROMPT_CHAT}\n\n"
        f"## Analysis Report\n\n{report_text}"
    )
    return Agent[PipelineContext](
        name="Chat Assistant",
        model=_get_model(),
        instructions=instructions,
        model_settings=ModelSettings(temperature=0.3),
        tools=CHAT_TOOLS,
    )
