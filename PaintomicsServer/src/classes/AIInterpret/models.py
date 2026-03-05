"""Pydantic models and shared data structures for the AI pipeline."""
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class PipelineContext:
    """Shared context passed to all agents and tools via RunContextWrapper."""
    job_instance: Any
    job_id: str
    organism_name: str
    design_type: str  # time_series | case_control | dose_response | single_condition | multi_group
    experiment_design: str
    enrichment_table: list = field(default_factory=list)
    gene_whitelist: set = field(default_factory=set)
    compound_whitelist: set = field(default_factory=set)
    papers_used: dict = field(default_factory=dict)  # pmid -> paper_dict
    pubmed_client: Any = None


class TriageDecision(BaseModel):
    pathway_id: str
    pathway_name: str
    investigate: bool
    priority: int = Field(ge=1, le=5, description="1=highest priority, 5=lowest")
    reasoning: str


class TriageResult(BaseModel):
    decisions: list[TriageDecision]


class EvaluationResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list, description="Specific problems found")
    suggestions: list[str] = Field(default_factory=list, description="How to improve")
    feedback: str = Field(default="", description="Formatted feedback for revision")
