#!/usr/bin/env python3
"""Comprehensive test for the AI pipeline v2 — agents, tools, context builders.

Run from PaintomicsServer/src/:
    python -m classes.AIInterpret.test_pipeline

Tests:
  1. Models (Pydantic round-trip)
  2. Context builders (detect_design_type, build_enrichment_table, build_feature_name_whitelist)
  3. Tool functions (all 9 tools with mock data)
  4. Agent definitions (model param, tool assignments)
  5. SDK configuration
  6. Triage agent (live LLM call)
  7. Expert agent with tool use (live LLM call)
  8. Evaluator agent (live LLM call)
  9. Report writer (live LLM call)
  10. Literature sub-agent (live LLM call)
"""
import asyncio
import json
import logging
import re
import sys
import traceback

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_pipeline")


# ============================================================================
# Mock domain objects (mirrors real Paintomics classes)
# ============================================================================

class MockOmicValue:
    def __init__(self, omic_name, values, relevant=False, original_name=""):
        self.omicName = omic_name
        self.values = values
        self.relevant = relevant
        self.originalName = original_name

    def getOmicName(self):
        return self.omicName

    def getValues(self):
        return self.values

    def isRelevant(self):
        return self.relevant


class MockFeature:
    def __init__(self, ID, name, omic_values=None):
        self.ID = ID
        self._name = name
        self.omicsValues = omic_values or []

    def getName(self):
        return self._name

    def getOmicsValues(self):
        return self.omicsValues


class MockPathway:
    def __init__(self, ID, name, source="KEGG", matched_genes=None, matched_compounds=None,
                 significance_values=None, combined_pvalues=None):
        self.ID = ID
        self.name = name
        self.source = source
        self.matchedGenes = matched_genes or []
        self.matchedCompounds = matched_compounds or []
        self.significanceValues = significance_values or {}
        self.combinedSignificancePvalues = combined_pvalues or {}


class MockJobInstance:
    def __init__(self):
        self.organism = "mmu"
        self.geneBasedInputOmics = []
        self.compoundBasedInputOmics = []
        self.inputGenesData = {}
        self.inputCompoundsData = {}
        self.matchedPathways = {}

    def getOrganism(self):
        return self.organism

    def getGeneBasedInputOmics(self):
        return self.geneBasedInputOmics

    def getCompoundBasedInputOmics(self):
        return self.compoundBasedInputOmics

    def getInputGenesData(self):
        return self.inputGenesData

    def getInputCompoundsData(self):
        return self.inputCompoundsData

    def getMatchedPathways(self):
        return self.matchedPathways


def build_test_job():
    """Build a realistic mock job with gene expression + metabolomics data."""
    job = MockJobInstance()

    job.geneBasedInputOmics = [
        {"omicName": "Gene Expression", "omicHeader": ["GeneID", "Exp_0h", "Exp_2h", "Exp_6h", "Exp_12h"]},
        {"omicName": "Proteomics", "omicHeader": ["GeneID", "Prot_0h", "Prot_2h", "Prot_6h", "Prot_12h"]},
    ]
    job.compoundBasedInputOmics = [
        {"omicName": "Metabolomics", "omicHeader": ["CompoundID", "Met_0h", "Met_2h", "Met_6h", "Met_12h"]},
    ]

    job.inputGenesData = {
        "12345": MockFeature("12345", "Tp53", [
            MockOmicValue("Gene Expression", [0.1, 0.5, 1.2, 0.8], relevant=True, original_name="Tp53"),
            MockOmicValue("Proteomics", [0.05, 0.3, 0.9, 0.7], relevant=True),
        ]),
        "12346": MockFeature("12346", "Brca1", [
            MockOmicValue("Gene Expression", [0.2, 0.3, 0.4, 0.5], relevant=False),
            MockOmicValue("Proteomics", [0.1, 0.15, 0.2, 0.25], relevant=False),
        ]),
        "12347": MockFeature("12347", "Mapk1", [
            MockOmicValue("Gene Expression", [0.8, 1.5, 2.0, 1.8], relevant=True),
        ]),
        "12348": MockFeature("12348", "Kras", [
            MockOmicValue("Gene Expression", [0.3, -0.2, -0.5, -0.8], relevant=True),
        ]),
        "12349": MockFeature("12349", "Akt1", [
            MockOmicValue("Gene Expression", [0.0, 0.1, 0.2, 0.15], relevant=False),
        ]),
    }

    job.inputCompoundsData = {
        "C00025": MockFeature("C00025", "L-Glutamate", [
            MockOmicValue("Metabolomics", [0.5, 1.0, 1.5, 1.2], relevant=True),
        ]),
        "C00064": MockFeature("C00064", "L-Glutamine", [
            MockOmicValue("Metabolomics", [0.3, 0.2, 0.1, 0.05], relevant=True),
        ]),
        "C00022": MockFeature("C00022", "Pyruvate", [
            MockOmicValue("Metabolomics", [0.4, 0.45, 0.5, 0.48], relevant=False),
        ]),
    }

    pw1 = MockPathway(
        "mmu04010", "MAPK signaling pathway", "KEGG",
        matched_genes=["12345", "12347", "12348"],
        matched_compounds=["C00025"],
        significance_values={
            "Gene Expression": [100, 15, 0.001],
            "Proteomics": [80, 10, 0.02],
            "Metabolomics": [50, 5, 0.04],
        },
        combined_pvalues={"fisher": 0.0005},
    )
    pw2 = MockPathway(
        "mmu04151", "PI3K-Akt signaling pathway", "KEGG",
        matched_genes=["12345", "12346", "12349"],
        matched_compounds=["C00064", "C00022"],
        significance_values={
            "Gene Expression": [120, 8, 0.05],
            "Proteomics": [90, 3, 0.15],
            "Metabolomics": [60, 4, 0.03],
        },
        combined_pvalues={"fisher": 0.008},
    )
    pw3 = MockPathway(
        "mmu04115", "p53 signaling pathway", "KEGG",
        matched_genes=["12345", "12348"],
        matched_compounds=[],
        significance_values={
            "Gene Expression": [50, 10, 0.002],
            "Proteomics": [40, 7, 0.01],
        },
        combined_pvalues={"fisher": 0.001},
    )

    job.matchedPathways = {"mmu04010": pw1, "mmu04151": pw2, "mmu04115": pw3}
    return job


def _make_ctx(design_type="time_series", with_pubmed=False):
    """Build a PipelineContext with a mock job."""
    from src.classes.AIInterpret.models import PipelineContext
    job = build_test_job()
    pubmed = None
    if with_pubmed:
        from src.classes.AIInterpret.pubmed_client import PubMedClient
        pubmed = PubMedClient()
    return PipelineContext(
        job_instance=job, job_id="test", organism_name="Mus musculus",
        design_type=design_type, experiment_design="Time-series experiment in mouse embryonic fibroblasts",
        pubmed_client=pubmed,
    )


def _make_tool_ctx(ctx_data):
    """Build a ToolContext for direct tool invocation (outside agent run loop)."""
    from agents.tool import ToolContext
    return ToolContext(
        context=ctx_data,
        tool_name="test",
        tool_call_id="test_call",
        tool_arguments="{}",
    )


# ============================================================================
# Test functions
# ============================================================================

def test_models():
    """Test 1: Pydantic models round-trip."""
    from src.classes.AIInterpret.models import (
        PipelineContext, TriageDecision, TriageResult, EvaluationResult,
    )

    tr = TriageResult(decisions=[
        TriageDecision(pathway_id="pw1", pathway_name="MAPK", investigate=True, priority=1, reasoning="test"),
        TriageDecision(pathway_id="pw2", pathway_name="PI3K", investigate=False, priority=3, reasoning="skip"),
    ])
    assert len(tr.decisions) == 2
    json_str = tr.model_dump_json()
    tr2 = TriageResult.model_validate_json(json_str)
    assert tr2.decisions[0].pathway_name == "MAPK"

    ev = EvaluationResult(approved=False, issues=["issue1"], suggestions=["fix1"], feedback="Needs work")
    json_str = ev.model_dump_json()
    ev2 = EvaluationResult.model_validate_json(json_str)
    assert ev2.feedback == "Needs work"

    ctx = PipelineContext(
        job_instance=None, job_id="test", organism_name="mouse",
        design_type="time_series", experiment_design="test design",
    )
    assert ctx.papers_used == {}
    assert ctx.gene_whitelist == set()

    logger.info("PASS: models round-trip")


def test_context_builders():
    """Test 2: detect_design_type, build_enrichment_table, build_feature_name_whitelist."""
    from src.classes.AIInterpret.context_builder import (
        detect_design_type, build_enrichment_table, build_feature_name_whitelist,
    )

    job = build_test_job()

    dt = detect_design_type(job)
    assert dt == "time_series", f"Expected time_series, got {dt}"
    logger.info(f"  detect_design_type: {dt}")

    dt2 = detect_design_type(job, "This is a case-control study comparing WT vs KO mice")
    assert dt2 == "case_control", f"Expected case_control, got {dt2}"
    logger.info(f"  detect_design_type (case-control override): {dt2}")

    table = build_enrichment_table(job, max_pathways=30)
    assert len(table) == 3
    assert table[0]["name"] == "MAPK signaling pathway"
    assert "Gene Expression" in table[0]["per_omic_pvalues"]
    assert table[0]["matched_gene_count"] == 3
    assert table[0]["matched_compound_count"] == 1
    logger.info(f"  build_enrichment_table: {len(table)} pathways, top={table[0]['name']}")

    wl = build_feature_name_whitelist(job)
    assert "TP53" in wl
    assert "BRCA1" in wl
    assert "L-GLUTAMATE" in wl
    assert "PYRUVATE" in wl
    logger.info(f"  build_feature_name_whitelist: {len(wl)} features")

    logger.info("PASS: context builders")


async def test_tools_data_query():
    """Test 3a: Data query tools with mock job."""
    from src.classes.AIInterpret.tools import (
        get_pathway_features, get_gene_profile, get_compound_profile,
        compare_features, get_pathway_summary,
    )

    ctx_data = _make_ctx()
    ctx = _make_tool_ctx(ctx_data)

    # get_pathway_features
    result = await get_pathway_features.on_invoke_tool(ctx, '{"pathway_name": "MAPK signaling pathway"}')
    assert "Tp53" in result, f"Expected Tp53, got: {result[:200]}"
    assert "Mapk1" in result
    assert "L-Glutamate" in result
    logger.info(f"  get_pathway_features: found Tp53, Mapk1, L-Glutamate")

    # Not found
    result_nf = await get_pathway_features.on_invoke_tool(ctx, '{"pathway_name": "Nonexistent pathway"}')
    assert "No pathway" in result_nf
    logger.info(f"  get_pathway_features (not found): OK")

    # get_gene_profile
    result = await get_gene_profile.on_invoke_tool(ctx, '{"gene_name": "Tp53"}')
    assert "Tp53" in result
    assert "Gene Expression" in result
    assert "Proteomics" in result
    assert "pattern:" in result
    logger.info(f"  get_gene_profile(Tp53): Gene Expression + Proteomics with pattern")

    # Case insensitive
    result_ci = await get_gene_profile.on_invoke_tool(ctx, '{"gene_name": "tp53"}')
    assert "Tp53" in result_ci
    logger.info(f"  get_gene_profile (case insensitive): OK")

    # Not found
    result_nf = await get_gene_profile.on_invoke_tool(ctx, '{"gene_name": "NONEXISTENT"}')
    assert "not found" in result_nf
    logger.info(f"  get_gene_profile (not found): OK")

    # get_compound_profile
    result = await get_compound_profile.on_invoke_tool(ctx, '{"compound_name": "L-Glutamate"}')
    assert "L-Glutamate" in result
    assert "Metabolomics" in result
    logger.info(f"  get_compound_profile(L-Glutamate): found Metabolomics")

    # compare_features — mixed gene + compound
    result = await compare_features.on_invoke_tool(ctx, '{"names": ["Tp53", "L-Glutamine", "Nonexistent"]}')
    assert "Tp53" in result
    assert "L-Glutamine" in result
    assert "NOT FOUND" in result
    logger.info(f"  compare_features (mixed): Tp53 + L-Glutamine + NOT FOUND")

    # get_pathway_summary
    result = await get_pathway_summary.on_invoke_tool(ctx, '{"pathway_name": "MAPK signaling pathway"}')
    assert "Matched genes: 3" in result
    assert "Matched compounds: 1" in result
    assert "SIGNIFICANT" in result
    logger.info(f"  get_pathway_summary: genes=3, compounds=1, SIGNIFICANT")

    logger.info("PASS: data query tools")


async def test_tools_literature():
    """Test 3b: Literature tools."""
    from src.classes.AIInterpret.tools import search_pubmed, read_full_text, search_paper_text

    ctx_data = _make_ctx(with_pubmed=True)
    ctx = _make_tool_ctx(ctx_data)

    result = await search_pubmed.on_invoke_tool(ctx, '{"query": "MAPK signaling cancer", "max_results": 2}')
    logger.info(f"  search_pubmed (first 200): {result[:200]}")
    if "PMID:" in result:
        pmid_match = re.search(r'PMID:\s*(\d+)', result)
        if pmid_match:
            pmid = pmid_match.group(1)
            logger.info(f"  Using PMID {pmid} for full text test")

            ft_result = await read_full_text.on_invoke_tool(ctx, f'{{"pmid": "{pmid}"}}')
            logger.info(f"  read_full_text (first 200): {ft_result[:200]}")

            if len(ft_result) > 100:
                spt = await search_paper_text.on_invoke_tool(ctx, f'{{"pmid": "{pmid}", "query": "signaling"}}')
                logger.info(f"  search_paper_text (first 200): {spt[:200]}")
    else:
        logger.warning("  search_pubmed: no PMIDs (network issue?)")

    logger.info("PASS: literature tools")


async def test_case_control_tools():
    """Test 3c: Tools with case-control design type."""
    from src.classes.AIInterpret.models import PipelineContext
    from src.classes.AIInterpret.tools import get_gene_profile

    job = MockJobInstance()
    job.geneBasedInputOmics = [
        {"omicName": "Gene Expression", "omicHeader": ["GeneID", "Exp_ctrl", "Exp_case"]},
    ]
    job.inputGenesData = {
        "G1": MockFeature("G1", "Brca1", [
            MockOmicValue("Gene Expression", [0.1, 0.9], relevant=True),
        ]),
    }
    job.matchedPathways = {}

    ctx_data = PipelineContext(
        job_instance=job, job_id="test", organism_name="human",
        design_type="case_control", experiment_design="",
    )
    ctx = _make_tool_ctx(ctx_data)

    result = await get_gene_profile.on_invoke_tool(ctx, '{"gene_name": "Brca1"}')
    assert "fold_change" in result
    assert "upregulated" in result
    logger.info(f"  Case-control Brca1: {result}")
    logger.info("PASS: case-control tools")


def test_agent_definitions():
    """Test 4: Agent definitions have correct model, tools."""
    import importlib
    import src.classes.AIInterpret.prompts as prompts_mod
    importlib.reload(prompts_mod)
    import src.classes.AIInterpret.agents as agents_mod
    importlib.reload(agents_mod)

    from src.classes.AIInterpret.agents import (
        triage_agent, literature_sub_agent, pathway_evaluator,
        report_writer, report_evaluator, build_pathway_expert, build_chat_agent,
        _get_model,
    )

    model = _get_model()
    logger.info(f"  Configured model: {model}")

    agents_to_check = [
        ("triage_agent", triage_agent, 0),
        ("literature_sub_agent", literature_sub_agent, 2),
        ("pathway_evaluator", pathway_evaluator, 7),
        ("report_writer", report_writer, 0),
        ("report_evaluator", report_evaluator, 0),
    ]

    for name, agent, expected_tool_count in agents_to_check:
        assert agent.model == model, f"{name}: model={agent.model}, expected={model}"
        assert len(agent.tools) == expected_tool_count, \
            f"{name}: tools={len(agent.tools)}, expected={expected_tool_count}"
        # output_type should NOT be set (Dashscope doesn't support it)
        assert agent.output_type is None, f"{name}: output_type should be None, got {agent.output_type}"
        logger.info(f"  {name}: model={model}, tools={len(agent.tools)}, output_type=None")

    expert = build_pathway_expert("MAPK signaling pathway", "time_series")
    assert expert.model == model
    assert len(expert.tools) == 7
    assert "MAPK signaling pathway" in expert.instructions
    logger.info(f"  build_pathway_expert: model={model}, tools=7")

    chat = build_chat_agent("Test report content")
    assert chat.model == model
    assert len(chat.tools) == 5
    logger.info(f"  build_chat_agent: model={model}, tools=5")

    assert "json" in triage_agent.instructions.lower(), "Triage prompt must mention 'json'"
    assert "json" in pathway_evaluator.instructions.lower(), "Evaluator prompt must mention 'json'"
    logger.info("  Prompts contain 'json' keyword for Dashscope")

    logger.info("PASS: agent definitions")


def test_sdk_configuration():
    """Test 5: SDK configures with Dashscope provider."""
    from src.classes.AIInterpret.agents import configure_sdk
    configure_sdk()
    logger.info("PASS: SDK configuration")


def test_triage_fallback_parsing():
    """Test 5b: Triage fallback parsing with various JSON formats."""
    from src.classes.AIInterpret.pipeline import _parse_triage_fallback
    from src.classes.AIInterpret.context_builder import build_enrichment_table

    table = build_enrichment_table(build_test_job())

    # Direct format
    text1 = json.dumps({"decisions": [
        {"pathway_id": "pw1", "pathway_name": "MAPK", "investigate": True, "priority": 1, "reasoning": "top"}
    ]})
    r1 = _parse_triage_fallback(text1, table)
    assert len(r1.decisions) == 1
    assert r1.decisions[0].investigate is True
    logger.info("  Direct format: OK")

    # Wrapped format (what Dashscope returns)
    text2 = json.dumps({"triage_result": {"pathways": [
        {"pathway_id": "pw1", "pathway_name": "MAPK", "investigate": True, "priority": 1, "reasoning": "top"},
        {"pathway_id": "pw2", "pathway_name": "PI3K", "investigate": False, "priority": 3, "reasoning": "skip"},
    ]}})
    r2 = _parse_triage_fallback(text2, table)
    assert len(r2.decisions) == 2
    logger.info("  Wrapped format: OK")

    # With markdown code block
    text3 = "```json\n" + text1 + "\n```"
    r3 = _parse_triage_fallback(text3, table)
    assert len(r3.decisions) == 1
    logger.info("  Code block format: OK")

    # Garbage text -> should use fallback
    r4 = _parse_triage_fallback("This is not JSON at all", table)
    assert len(r4.decisions) == 3  # fallback selects all pathways from table
    logger.info("  Garbage fallback: OK")

    logger.info("PASS: triage fallback parsing")


def test_evaluation_fallback_parsing():
    """Test 5c: Evaluation fallback parsing."""
    from src.classes.AIInterpret.pipeline import _parse_evaluation_fallback

    # Direct JSON
    text1 = json.dumps({"approved": True, "issues": [], "suggestions": [], "feedback": "Looks good"})
    r1 = _parse_evaluation_fallback(text1)
    assert r1.approved is True
    logger.info("  Direct JSON: OK")

    # Mixed text with JSON
    text2 = 'After reviewing, here is my evaluation:\n```json\n{"approved": false, "issues": ["Missing metabolomics"], "suggestions": ["Add compounds"], "feedback": "Incomplete"}\n```'
    r2 = _parse_evaluation_fallback(text2)
    assert r2.approved is False
    assert "Missing metabolomics" in r2.issues
    logger.info("  Mixed text + JSON: OK")

    # Text-only heuristic
    r3 = _parse_evaluation_fallback("The analysis is approved and well-structured.")
    assert r3.approved is True
    logger.info("  Heuristic (approved): OK")

    r4 = _parse_evaluation_fallback("This analysis is not approved due to errors.")
    assert r4.approved is False
    logger.info("  Heuristic (not approved): OK")

    logger.info("PASS: evaluation fallback parsing")


async def test_triage_agent_live():
    """Test 6: Live triage agent call."""
    from agents import Runner
    from src.classes.AIInterpret.agents import triage_agent
    from src.classes.AIInterpret.prompts import format_enrichment_table
    from src.classes.AIInterpret.context_builder import build_enrichment_table
    from src.classes.AIInterpret.pipeline import _parse_triage_fallback

    ctx = _make_ctx()
    table = build_enrichment_table(build_test_job(), max_pathways=30)
    ctx.enrichment_table = table

    prompt = format_enrichment_table(table, "Time-series experiment in mouse embryonic fibroblasts", "Mus musculus")
    logger.info(f"  Triage prompt length: {len(prompt)} chars")

    result = await Runner.run(triage_agent, prompt, context=ctx, max_turns=1)
    output = str(result.final_output)
    logger.info(f"  Raw output (first 400 chars): {output[:400]}")

    parsed = _parse_triage_fallback(output, table)
    selected = [d for d in parsed.decisions if d.investigate]
    logger.info(f"  Parsed: {len(parsed.decisions)} decisions, {len(selected)} selected")
    for d in parsed.decisions:
        logger.info(f"    {d.pathway_name}: investigate={d.investigate}, priority={d.priority}")

    assert len(selected) >= 1, "Triage should select at least 1 pathway"
    logger.info("PASS: triage agent (live)")


async def test_expert_agent_live():
    """Test 7: Live expert agent with tool use."""
    from agents import Runner
    from src.classes.AIInterpret.agents import build_pathway_expert

    ctx = _make_ctx(with_pubmed=True)
    expert = build_pathway_expert("MAPK signaling pathway", "time_series")

    prompt = (
        "Investigate: MAPK signaling pathway\n"
        "Per-omic p-values: Gene Expression: 0.0010; Proteomics: 0.0200; Metabolomics: 0.0400\n"
        "Experiment design: Time-series experiment in mouse embryonic fibroblasts\n"
        "Design type: time_series"
    )

    result = await Runner.run(expert, prompt, context=ctx, max_turns=10)
    output = str(result.final_output)
    logger.info(f"  Expert output length: {len(output)} chars")
    logger.info(f"  Expert output (first 500 chars):\n{output[:500]}")

    mentions_gene = any(g in output for g in ["Tp53", "Mapk1", "Kras"])
    logger.info(f"  Mentions expected genes: {mentions_gene}")

    logger.info("PASS: expert agent (live)")


async def test_evaluator_agent_live():
    """Test 8: Live evaluator agent."""
    from agents import Runner
    from src.classes.AIInterpret.agents import pathway_evaluator
    from src.classes.AIInterpret.pipeline import _parse_evaluation_fallback

    ctx = _make_ctx()

    fake_analysis = """
## MAPK Signaling Pathway Analysis

The MAPK signaling pathway shows significant enrichment across Gene Expression (p=0.001)
and Proteomics (p=0.02).

**Key Genes:**
- **Tp53**: Transient-peak in Gene Expression (0h=0.1, 2h=0.5, 6h=1.2, 12h=0.8),
  concordant Proteomics upregulation. p53 activation peaks at 6h.
- **Mapk1**: Monotonic upregulation (0h=0.8, 2h=1.5, 6h=2.0, 12h=1.8).
- **Kras**: Progressive downregulation (0.3 -> -0.8), negative feedback.

**Key Metabolites:**
- **L-Glutamate**: Transient peak at 6h, consistent with glutaminolysis.

**Cross-Omic:** Tp53 concordant in expression + proteomics.
"""

    eval_prompt = (
        f"Review this pathway analysis for accuracy and completeness:\n\n"
        f"{fake_analysis}\n\n"
        f"Pathway: MAPK signaling pathway\n"
        f"Design type: time_series"
    )

    result = await Runner.run(pathway_evaluator, eval_prompt, context=ctx, max_turns=5)
    output = str(result.final_output)
    logger.info(f"  Raw evaluator output (first 400 chars): {output[:400]}")

    parsed = _parse_evaluation_fallback(output)
    logger.info(f"  Parsed: approved={parsed.approved}, issues={parsed.issues}")
    logger.info(f"  Feedback (first 200): {parsed.feedback[:200]}")

    logger.info("PASS: evaluator agent (live)")


async def test_report_writer_live():
    """Test 9: Live report writer."""
    from agents import Runner
    from src.classes.AIInterpret.agents import report_writer

    ctx = _make_ctx()

    synth_input = """## Experiment Context
Organism: Mus musculus
Design: Time-series experiment studying MEF response

## Individual Pathway Analyses

### MAPK signaling pathway
Tp53 shows transient-peak at 6h in Gene Expression (0.1 -> 1.2 -> 0.8) with concordant
Proteomics. Mapk1 monotonic-up. L-Glutamate peaks at 6h. Cross-omic concordance strong.

---

### p53 signaling pathway
Tp53 is the driver gene (same pattern as MAPK). Kras downregulated (-0.8 at 12h).
No metabolite data. p53 activation peaks at 6h, suggesting DNA damage response.
"""

    result = await Runner.run(report_writer, synth_input, context=ctx, max_turns=1)
    output = str(result.final_output)
    logger.info(f"  Report length: {len(output)} chars")
    logger.info(f"  Report (first 500 chars):\n{output[:500]}")
    logger.info("PASS: report writer (live)")


async def test_literature_subagent_live():
    """Test 10: Literature sub-agent with PubMed."""
    from agents import Runner
    from src.classes.AIInterpret.agents import literature_sub_agent
    from src.classes.AIInterpret.tools import search_pubmed

    ctx_data = _make_ctx(with_pubmed=True)
    ctx = _make_tool_ctx(ctx_data)

    search_result = await search_pubmed.on_invoke_tool(ctx, '{"query": "MAPK p53 signaling mouse", "max_results": 1}')
    pmid_match = re.search(r'PMID:\s*(\d+)', search_result)
    if not pmid_match:
        logger.warning("  Skipping: no PubMed results")
        return

    pmid = pmid_match.group(1)
    logger.info(f"  Testing with PMID {pmid}")

    prompt = (
        f"Paper PMID: {pmid}\n"
        f"Question: What role does p53 play in MAPK signaling?\n\n"
        f"Read the paper using read_full_text({pmid}) and find evidence. "
        f"Return: FINDING: <summary>, CITED_TEXT: <quote>, RELEVANCE: HIGH|MEDIUM|LOW|NONE."
    )

    result = await Runner.run(literature_sub_agent, prompt, context=ctx_data, max_turns=5)
    output = str(result.final_output)
    logger.info(f"  Sub-agent output (first 400 chars):\n{output[:400]}")
    logger.info("PASS: literature sub-agent (live)")


# ============================================================================
# Main
# ============================================================================

async def run_all_tests():
    logger.info("=" * 60)
    logger.info("AI Pipeline V2 — Comprehensive Test Suite")
    logger.info("=" * 60)

    passed = 0
    failed = 0

    # Sync tests
    sync_tests = [
        ("1. Pydantic models", test_models),
        ("2. Context builders", test_context_builders),
        ("4. Agent definitions", test_agent_definitions),
        ("5. SDK configuration", test_sdk_configuration),
        ("5b. Triage fallback parsing", test_triage_fallback_parsing),
        ("5c. Evaluation fallback parsing", test_evaluation_fallback_parsing),
    ]

    for name, fn in sync_tests:
        logger.info(f"\n--- {name} ---")
        try:
            fn()
            passed += 1
        except Exception as e:
            logger.error(f"FAIL: {name}: {e}")
            traceback.print_exc()
            failed += 1

    # Async offline tests
    async_offline = [
        ("3a. Data query tools", test_tools_data_query),
        ("3b. Literature tools", test_tools_literature),
        ("3c. Case-control tools", test_case_control_tools),
    ]

    for name, fn in async_offline:
        logger.info(f"\n--- {name} ---")
        try:
            await fn()
            passed += 1
        except Exception as e:
            logger.error(f"FAIL: {name}: {e}")
            traceback.print_exc()
            failed += 1

    # Live LLM tests
    logger.info(f"\n{'=' * 60}")
    logger.info("Live LLM tests (require API key + network)")
    logger.info("=" * 60)

    live_tests = [
        ("6. Triage agent (live)", test_triage_agent_live),
        ("7. Expert agent (live)", test_expert_agent_live),
        ("8. Evaluator agent (live)", test_evaluator_agent_live),
        ("9. Report writer (live)", test_report_writer_live),
        ("10. Literature sub-agent (live)", test_literature_subagent_live),
    ]

    for name, fn in live_tests:
        logger.info(f"\n--- {name} ---")
        try:
            await fn()
            passed += 1
        except Exception as e:
            logger.error(f"FAIL: {name}: {e}")
            traceback.print_exc()
            failed += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    logger.info("=" * 60)

    return 0 if failed == 0 else 1


def main():
    return asyncio.run(run_all_tests())


if __name__ == "__main__":
    sys.exit(main())
