#!/usr/bin/env python3
"""Real-data harness for AIInterpret using PaintOmics example omics tables.

Run from `PaintomicsServer/`:

    python -m src.classes.AIInterpret.test_example_dataset

Useful flags:

    --max-pathways 5
    --pathway "Apoptosis"
    --with-agent
    --databases KEGG Reactome
"""
import argparse
import asyncio
import os
import json
import uuid

from agents import Runner
from agents.tool import ToolContext
from pymongo.errors import PyMongoError

from src.classes.AIInterpret.agents import build_pathway_expert, build_pathway_expert_local_only, configure_sdk
from src.classes.AIInterpret.context_builder import (
    build_enrichment_table, build_feature_name_whitelist, detect_design_type, get_organism_name,
)
from src.classes.AIInterpret.models import PipelineContext
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.tools import (
    _format_omic_support,
    _get_relevant_omic_counts,
    build_pathway_evidence_bundle,
    format_pathway_evidence_bundle,
    get_gene_profile,
    get_compound_profile,
    get_pathway_features,
    get_pathway_neighbors,
    get_pathway_summary,
)
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.conf.serverconf import CLIENT_TMP_DIR


EXAMPLE_OMICS = {
    "Gene expression": "genes",
    "Metabolomics": "features",
    "Proteomics": "features",
    "miRNA-seq": "genes",
    "DNase-seq": "genes",
    "Transcription factor": "genes",
}


def _make_tool_ctx(ctx_data):
    return ToolContext(
        context=ctx_data,
        tool_name="example_dataset",
        tool_call_id="example_call",
        tool_arguments="{}",
    )


def _peak_abs(values):
    if not values:
        return 0.0
    return max(abs(v) for v in values)


def _feature_rank(feature):
    relevant_omic_counts = _get_relevant_omic_counts(feature)
    relevant_values = [ov for ov in feature.getOmicsValues() if ov.isRelevant()]
    omic_layers = len(relevant_omic_counts)
    peak = max((_peak_abs(ov.getValues() or []) for ov in relevant_values), default=0.0)
    return omic_layers, peak, relevant_omic_counts


def _select_seed_features(job_instance, pathway, max_seeds=3):
    seeds = []

    for gene_id in pathway.matchedGenes:
        gene = job_instance.getInputGenesData().get(gene_id)
        if gene is None:
            continue
        omic_layers, peak, relevant_omic_counts = _feature_rank(gene)
        seeds.append({
            "kind": "gene",
            "id": gene_id,
            "name": gene.getName() or gene_id,
            "omic_layers": omic_layers,
            "peak": peak,
            "omic_support": _format_omic_support(relevant_omic_counts),
        })

    for compound_id in pathway.matchedCompounds:
        compound = job_instance.getInputCompoundsData().get(compound_id)
        if compound is None:
            continue
        omic_layers, peak, relevant_omic_counts = _feature_rank(compound)
        seeds.append({
            "kind": "compound",
            "id": compound_id,
            "name": compound.getName() or compound_id,
            "omic_layers": omic_layers,
            "peak": peak,
            "omic_support": _format_omic_support(relevant_omic_counts),
        })

    seeds.sort(key=lambda item: (-item["omic_layers"], -item["peak"], item["name"].upper()))

    chosen = []
    have_compound = False
    for seed in seeds:
        if len(chosen) >= max_seeds:
            break
        if seed["omic_layers"] == 0 and chosen:
            continue
        chosen.append(seed)
        have_compound = have_compound or seed["kind"] == "compound"

    if pathway.matchedCompounds and not have_compound:
        for seed in seeds:
            if seed["kind"] == "compound" and seed not in chosen:
                if chosen:
                    chosen[-1] = seed
                else:
                    chosen.append(seed)
                break

    return chosen[:max_seeds]


def _build_example_job(databases, experiment_design, tmp_dir):
    job = PathwayAcquisitionJob(
        jobID="aiinterpret_example_" + uuid.uuid4().hex[:10],
        userID="codex",
        CLIENT_TMP_DIR=tmp_dir,
    )
    job.initializeDirectories()
    job.setOrganism("mmu")
    job.setDatabases(databases)
    job.setAIConsent(True)
    job.setExperimentDesign(experiment_design)
    job.setName("AIInterpret example dataset harness")

    # Resolved through the example catalogue rather than by rebuilding
    # filenames. This was one of three copies of the same name-mangling rule
    # ("DNase-seq" -> "dnase_values.tab"); all of them broke when the files
    # moved into examplefiles/datasets/, and none of them said so out loud.
    from src.common import ExampleDatasets

    example_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "examplefiles")) + os.sep
    ExampleDatasets.applyScenario(job, example_dir, "stategra-multiomics")

    return job


def _print_omic_summary(job_instance):
    print("Processed omics:")
    for omic in job_instance.getGeneBasedInputOmics():
        summary = omic.get("omicSummary") or []
        header = omic.get("omicHeader") or []
        mapped = summary[0] if summary else "?"
        unmapped = summary[1] if len(summary) > 1 else "?"
        print(f"  - {omic.get('omicName')}: mapped={mapped}, unmapped={unmapped}, columns={max(len(header) - 1, 0)}")
    for omic in job_instance.getCompoundBasedInputOmics():
        summary = omic.get("omicSummary") or []
        header = omic.get("omicHeader") or []
        mapped = summary[0] if summary else "?"
        unmapped = summary[1] if len(summary) > 1 else "?"
        print(f"  - {omic.get('omicName')}: mapped={mapped}, unmapped={unmapped}, columns={max(len(header) - 1, 0)}")


def _print_top_pathways(enrichment_table):
    print("\nTop pathways:")
    for idx, pw in enumerate(enrichment_table, 1):
        print(
            f"  {idx}. {pw['name']} [{pw['id']}] | combined={pw['combined_pvalue']:.3e} | "
            f"significant_omics={pw['significant_omic_count']} | genes={pw['matched_gene_count']} | "
            f"compounds={pw['matched_compound_count']}"
        )


async def _invoke_tool(tool, ctx_data, payload):
    ctx = _make_tool_ctx(ctx_data)
    return await tool.on_invoke_tool(ctx, json.dumps(payload))


async def _dump_pathway_details(job_instance, ctx_data, pathway_name, max_seeds):
    pathway = next(pw for pw in job_instance.getMatchedPathways().values() if pw.name == pathway_name)
    print("\n" + "=" * 100)
    print(f"Pathway: {pathway.name} [{pathway.ID}]")
    print("=" * 100)

    summary = await _invoke_tool(get_pathway_summary, ctx_data, {"pathway_name": pathway.name})
    print("\n[get_pathway_summary]")
    print(summary)

    features = await _invoke_tool(get_pathway_features, ctx_data, {"pathway_name": pathway.name})
    print("\n[get_pathway_features]")
    print(features)

    seeds = _select_seed_features(job_instance, pathway, max_seeds=max_seeds)
    print("\nSelected seeds:")
    if not seeds:
        print("  (none)")
    for seed in seeds:
        print(
            f"  - {seed['name']} [{seed['kind']}] | omic_layers={seed['omic_layers']} | "
            f"support={seed['omic_support']} | peak={seed['peak']:.3f}"
        )

    for seed in seeds:
        neighbor_output = await _invoke_tool(
            get_pathway_neighbors,
            ctx_data,
            {"pathway_name": pathway.name, "feature_name": seed["name"]},
        )
        print(f"\n[get_pathway_neighbors] seed={seed['name']}")
        print(neighbor_output)

        profile_tool = get_compound_profile if seed["kind"] == "compound" else get_gene_profile
        profile_key = "compound_name" if seed["kind"] == "compound" else "gene_name"
        profile_output = await _invoke_tool(profile_tool, ctx_data, {profile_key: seed["name"]})
        print(f"\n[{'get_compound_profile' if seed['kind'] == 'compound' else 'get_gene_profile'}] seed={seed['name']}")
        print(profile_output)


async def _run_agent(ctx_data, pathway_name, max_turns, local_only=False):
    configure_sdk()
    agent = (
        build_pathway_expert_local_only(pathway_name, ctx_data.design_type)
        if local_only else
        build_pathway_expert(pathway_name, ctx_data.design_type)
    )
    prompt = (
        f"Investigate: {pathway_name}\n"
        f"Experiment design: {ctx_data.experiment_design}\n"
        f"Design type: {ctx_data.design_type}\n"
        "Use the local-network workflow and keep observed facts separate from mechanistic inference."
    )
    result = await Runner.run(agent, prompt, context=ctx_data, max_turns=max_turns)
    print("\n[expert agent output]")
    print(str(result.final_output))


async def _run_full_pipeline(job, args):
    """Run the complete AI interpretation pipeline end-to-end and print results."""
    import os
    import tempfile
    from collections import OrderedDict

    from src.classes.AIInterpret.agents import (
        configure_sdk, triage_agent, build_pathway_expert,
        pathway_evaluator, report_writer, report_evaluator,
    )
    from src.classes.AIInterpret.models import (
        TriageResult, EvaluationResult, PathwayAnalysisResult,
    )
    from src.classes.AIInterpret.pipeline import (
        _run_triage, _expert_with_evaluation, _report_with_evaluation,
        _finalize_report_text, _collect_cited_papers, _build_references_section,
        _clone_pipeline_context, _merge_papers_by_pmid,
    )
    from src.classes.AIInterpret.prompts import format_enrichment_table as format_table
    from src.classes.AIInterpret.verification import (
        verify_report_v2, redact_unverified_v2, renumber_citations, convert_pmid_citations,
    )
    from src.conf.serverconf import (
        AI_TRIAGE_MAX_PATHWAYS, AI_MAX_SELECTED_PATHWAYS,
        AI_MAX_EVAL_ITERATIONS, AI_REPORT_MAX_EVAL_ITERATIONS,
    )

    configure_sdk()

    organism_name = get_organism_name(job.getOrganism())
    design_type = detect_design_type(job, job.getExperimentDesign())
    enrichment_table = build_enrichment_table(job, max_pathways=AI_TRIAGE_MAX_PATHWAYS)
    whitelist = build_feature_name_whitelist(job)
    experiment_design = job.getExperimentDesign()

    ctx = PipelineContext(
        job_instance=job,
        job_id=job.getJobID(),
        organism_name=organism_name,
        design_type=design_type,
        experiment_design=experiment_design,
        enrichment_table=enrichment_table,
        gene_whitelist=whitelist,
        compound_whitelist=whitelist,
        pubmed_client=PubMedClient(),
    )

    print(f"\n{'='*80}")
    print("FULL PIPELINE RUN")
    print(f"{'='*80}")
    print(f"  Organism: {organism_name}")
    print(f"  Design type: {design_type}")
    print(f"  Enrichment pathways: {len(enrichment_table)}")
    print(f"  Feature whitelist: {len(whitelist)} names")

    # Phase 1: Triage
    print(f"\n--- Phase 1: Triage ---")
    triage_prompt = format_table(enrichment_table, experiment_design, organism_name)
    triage_result = await _run_triage(ctx, triage_prompt)
    selected = [d for d in triage_result.decisions if d.investigate and d.pathway_name.strip()]
    selected.sort(key=lambda d: d.priority)
    max_pw = args.max_pathways if args.max_pathways else AI_MAX_SELECTED_PATHWAYS
    selected = selected[:max_pw]

    # Fallback: if triage returned no usable pathway names, pick from enrichment table
    if not selected:
        print("  Triage returned no pathway names — using top enrichment table entries.")
        from src.classes.AIInterpret.models import TriageDecision
        for i, pw in enumerate(enrichment_table[:max_pw]):
            selected.append(TriageDecision(
                pathway_id=pw["id"], pathway_name=pw["name"],
                investigate=True, priority=i + 1,
                reasoning="Fallback: triage returned empty names",
            ))

    print(f"  Selected {len(selected)} pathways:")
    for d in selected:
        print(f"    - {d.pathway_name} (priority={d.priority})")

    # Phase 2: Expert + Evaluator per pathway
    print(f"\n--- Phase 2: Per-Pathway Expert + Evaluator ---")
    pathway_results = []
    for i, pw_decision in enumerate(selected, 1):
        pw_name = pw_decision.pathway_name
        path_ctx = _clone_pipeline_context(ctx)
        pw_data = next((e for e in enrichment_table if e["name"] == pw_name), None)
        pval_str = ""
        if pw_data:
            pval_parts = [f"{k}: {v:.4f}" for k, v in pw_data.get("per_omic_pvalues", {}).items()]
            pval_str = "; ".join(pval_parts)

        print(f"  [{i}/{len(selected)}] Analyzing: {pw_name}...")
        try:
            report = await _expert_with_evaluation(
                path_ctx, pw_name, pval_str, experiment_design, design_type,
                max_iterations=AI_MAX_EVAL_ITERATIONS,
            )
            evidence = build_pathway_evidence_bundle(
                job, pw_name, design_type,
                pathway_papers=list(path_ctx.papers_used.values()),
                organism_name=ctx.organism_name,
            )
        except Exception as e:
            print(f"    FAILED: {e}")
            report = f"[Analysis of {pw_name} could not be completed: {type(e).__name__}]"
            evidence = build_pathway_evidence_bundle(
                job, pw_name, design_type, pathway_papers=[],
                organism_name=ctx.organism_name,
            )

        result = PathwayAnalysisResult(
            pathway_name=pw_name, report=report, evidence=evidence,
            papers=list(path_ctx.papers_used.values()),
        )
        pathway_results.append(result)
        _merge_papers_by_pmid(ctx.papers_used, result.papers, pw_name)
        print(f"    Done. Report length: {len(report)} chars, papers: {len(result.papers)}")

    # Phase 3: Report Writer + Evaluator
    print(f"\n--- Phase 3: Report Synthesis ---")
    valid_results = [r for r in pathway_results if not r.report.startswith("[Analysis of")]
    if not valid_results:
        print("  ERROR: All pathway analyses failed!")
        return

    try:
        report = await _report_with_evaluation(
            ctx, valid_results, experiment_design, organism_name,
            max_iterations=AI_REPORT_MAX_EVAL_ITERATIONS,
        )
    except Exception as e:
        print(f"  Report synthesis FAILED: {e}")
        print("  Falling back to concatenated pathway reports.")
        report = "\n\n---\n\n".join(r.report for r in valid_results)
    print(f"  Report length: {len(report)} chars")

    # Phase 4: Post-processing
    print(f"\n--- Phase 4: Post-Processing ---")
    papers = _collect_cited_papers(report, valid_results, ctx.papers_used)
    for idx, p in enumerate(papers, 1):
        p["ref_index"] = idx

    report = convert_pmid_citations(report, papers)
    final = verify_report_v2(report, ctx.gene_whitelist, papers, job)

    if final.get("failed_citations"):
        report, removed = redact_unverified_v2(report, final["failed_citations"])
        final["redacted_count"] = removed
        print(f"  Redacted {removed} unverified citation(s)")

    report, citation_mapping = renumber_citations(report)

    # Print results
    print(f"\n{'='*80}")
    print("RESULTS")
    print(f"{'='*80}")
    print(f"  Verification score: {final['score']}")
    print(f"  Gene accuracy:      {final['gene_accuracy']}")
    print(f"  Ref accuracy:       {final['ref_accuracy']}")
    print(f"  Citation count:     {final.get('citation_count', 0)}")
    print(f"  Reference entries:  {final.get('reference_entry_count', 0)}")
    print(f"  Papers cited:       {len(papers)}")

    if final.get("failed_citations"):
        print(f"\n  Failed citations:")
        for fc in final["failed_citations"]:
            print(f"    - [{fc['ref_index']}] {fc['reason']}")

    # Save report to file
    output_path = os.path.join(args.tmp_dir or CLIENT_TMP_DIR, f"ai_report_{job.getJobID()}.md")
    with open(output_path, "w") as f:
        f.write(report)
    print(f"\n  Report saved to: {output_path}")

    print(f"\n{'='*80}")
    print("FINAL REPORT")
    print(f"{'='*80}")
    print(report[:3000])
    if len(report) > 3000:
        print(f"\n... [{len(report) - 3000} more chars, see full report at {output_path}]")

    return final


async def main():
    parser = argparse.ArgumentParser(description="Run AIInterpret against the real example omics dataset.")
    parser.add_argument("--databases", nargs="+", default=["KEGG"], help="Databases to use, default: KEGG")
    parser.add_argument("--experiment-design", default="Time-series example dataset (Ikaros/Control 0h-24h)")
    parser.add_argument("--max-pathways", type=int, default=3, help="How many top pathways to inspect")
    parser.add_argument("--min-significant-omics", type=int, default=3, help="Filter for pathways with at least this many significant omics")
    parser.add_argument("--pathway", action="append", default=[], help="Specific pathway name to inspect; can be repeated")
    parser.add_argument("--max-seeds", type=int, default=3, help="Maximum seed features per pathway")
    parser.add_argument("--with-agent", action="store_true", help="Run the live pathway expert agent on the first selected pathway")
    parser.add_argument("--local-only-agent", action="store_true", help="Run a live local-only expert agent on the first selected pathway")
    parser.add_argument("--agent-turns", type=int, default=14, help="Max turns for the live expert agent")
    parser.add_argument("--full-pipeline", action="store_true", help="Run the complete AI pipeline (triage->expert->report->verify) end-to-end")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temp/output dirs for debugging")
    parser.add_argument("--tmp-dir", default=CLIENT_TMP_DIR, help="Temporary root for the job, default: server CLIENT_TMP_DIR")
    args = parser.parse_args()
    if args.with_agent and args.local_only_agent:
        parser.error("Choose only one of --with-agent or --local-only-agent.")
    if args.full_pipeline and (args.with_agent or args.local_only_agent):
        parser.error("--full-pipeline cannot be combined with --with-agent or --local-only-agent.")

    job = _build_example_job(args.databases, args.experiment_design, args.tmp_dir)

    try:
        print("Building example job...")
        print(f"  job_id={job.getJobID()}")
        print(f"  organism={job.getOrganism()}")
        print(f"  databases={job.getDatabases()}")

        job.validateInput()
        job.processFilesContent()
        _print_omic_summary(job)

        summary = job.generatePathwaysList()
        print("\nPathway generation summary:")
        print(f"  total_pathways={summary[0]}")
        print(f"  matched_pathways={summary[1]}")
        print(f"  input_genes={summary[2]}")
        print(f"  input_compounds={summary[3]}")

        if args.full_pipeline:
            await _run_full_pipeline(job, args)
            return

        organism_name = get_organism_name(job.getOrganism())
        design_type = detect_design_type(job, job.getExperimentDesign())
        ctx_data = PipelineContext(
            job_instance=job,
            job_id=job.getJobID(),
            organism_name=organism_name,
            design_type=design_type,
            experiment_design=job.getExperimentDesign(),
            pubmed_client=PubMedClient() if args.with_agent else None,
        )

        enrichment_table = build_enrichment_table(job, max_pathways=max(args.max_pathways * 4, 20))
        _print_top_pathways(enrichment_table[:args.max_pathways])

        if args.pathway:
            selected_names = args.pathway
        else:
            selected_names = [
                pw["name"] for pw in enrichment_table
                if pw["significant_omic_count"] >= args.min_significant_omics
            ][:args.max_pathways]
            if not selected_names:
                selected_names = [pw["name"] for pw in enrichment_table[:args.max_pathways]]

        print("\nSelected pathways for detailed inspection:")
        for pathway_name in selected_names:
            print(f"  - {pathway_name}")

        for pathway_name in selected_names:
            await _dump_pathway_details(job, ctx_data, pathway_name, args.max_seeds)

        if (args.with_agent or args.local_only_agent) and selected_names:
            await _run_agent(ctx_data, selected_names[0], args.agent_turns, local_only=args.local_only_agent)

    except PyMongoError as exc:
        print("\nMongoDB access failed while building the real example job.")
        print("The example dataset harness uses the same mapping/pathway databases as the main app.")
        print(f"PyMongo error: {exc}")
        raise
    finally:
        if args.keep_temp:
            print("\nKeeping temporary directories:")
            print(f"  temporal={job.getTemporalDir()}")
            print(f"  output={job.getOutputDir()}")
        else:
            job.cleanDirectories(remove_output=True, remove_input=False)


if __name__ == "__main__":
    asyncio.run(main())
